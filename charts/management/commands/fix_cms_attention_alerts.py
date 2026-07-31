"""Repair source-backed CMS attention alerts.

This command is intentionally conservative:
  * Dry-run by default; pass --apply to write.
  * Researched country fields only fill blanks unless a row says overwrite=true.
  * Featured artist credits are linked only when every name resolves exactly.
  * Cover artwork is downloaded only with --apply --download-covers.
  * Duplicate artist candidates are reported, not merged.
"""

import json
import os
import re
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from charts.artist_credits import format_artist_list, split_artist_names
from charts.cms_utils import sync_release_chart_entry_snapshots
from charts.management.commands.update_artist_countries import ARTIST_COUNTRIES
from charts.models import (
    Artist,
    AuditLog,
    ChartUpload,
    MonthlyChart,
    Release,
    ReleaseArtistCredit,
)


DEFAULT_PATH = os.path.join(
    "scripts",
    "metadata_research_cms_attention_20260731.json",
)

ARTIST_FIELDS = (
    "country",
    "country_code",
    "city_region",
    "genre",
    "biography",
)

RELEASE_FIELDS = (
    "country",
    "country_code",
    "genre",
    "label",
    "distributor",
    "release_date",
    "release_year",
    "number_of_tracks",
    "songwriters",
    "producers",
)


def _blank(value):
    return value is None or str(value).strip() == ""


def _clean_code(value):
    return str(value or "").strip().upper()


def _fold(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _display(value):
    return str(value or "").encode("ascii", "replace").decode("ascii")


def _truthy(value):
    return value is True or str(value).strip().lower() in {"1", "true", "yes", "y"}


def _row_source(row):
    return row.get("source_url") or row.get("source") or ""


class Command(BaseCommand):
    help = (
        "Backfill researched CMS attention-alert data, link featured credits, "
        "attach known missing covers, and backfill published upload records."
    )

    def add_arguments(self, parser):
        parser.add_argument("--path", default=DEFAULT_PATH, help="Path to the sourced metadata JSON file.")
        parser.add_argument("--apply", action="store_true", help="Write changes. Without this flag, reports a dry-run.")
        parser.add_argument(
            "--download-covers",
            action="store_true",
            help="Download and save cover artwork. Requires --apply.",
        )
        parser.add_argument(
            "--skip-existing-country-map",
            action="store_true",
            help="Do not also apply the repository's existing ARTIST_COUNTRIES map to blank artists.",
        )
        parser.add_argument(
            "--skip-featured-auto-link",
            action="store_true",
            help="Only process featured_links from the JSON file; do not scan all text-only featured credits.",
        )
        parser.add_argument(
            "--skip-country-propagation",
            action="store_true",
            help="Do not copy lead artist country/code to active releases.",
        )

    def handle(self, *args, **options):
        path = options["path"]
        if not os.path.exists(path):
            raise CommandError(f"Metadata file not found: {path}")

        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)

        apply_changes = options["apply"]
        download_covers = options["download_covers"]
        if download_covers and not apply_changes:
            raise CommandError("--download-covers only makes sense with --apply")

        report = {
            "artists_updated": 0,
            "artists_skipped": 0,
            "artist_misses": [],
            "release_rows_updated": 0,
            "release_rows_skipped": 0,
            "release_misses": [],
            "release_countries_propagated": 0,
            "featured_links_updated": 0,
            "featured_links_skipped": 0,
            "featured_link_misses": [],
            "covers_updated": 0,
            "covers_skipped": 0,
            "cover_misses": [],
            "uploads_created": 0,
            "uploads_skipped": 0,
            "upload_misses": [],
            "duplicate_notes": payload.get("duplicate_review_notes", []),
        }

        if apply_changes:
            with transaction.atomic():
                self._run_repairs(payload, options, report)
                self._write_audit_log(payload, report)
        else:
            self._run_repairs(payload, options, report)

        self._print_report(report, apply_changes)

    def _run_repairs(self, payload, options, report):
        artist_rows = list(payload.get("artists", []))
        if not options["skip_existing_country_map"]:
            artist_rows.extend(self._existing_country_map_rows())

        self._apply_artist_rows(artist_rows, options["apply"], report)
        self._apply_release_rows(payload.get("songs", []), options["apply"], report)
        self._apply_release_rows(payload.get("albums", []), options["apply"], report)

        if not options["skip_country_propagation"]:
            self._propagate_lead_artist_countries(options["apply"], report)

        self._link_featured_rows(payload.get("featured_links", []), options["apply"], report)
        if not options["skip_featured_auto_link"]:
            self._auto_link_text_featured(options["apply"], report)

        self._apply_cover_rows(
            payload.get("covers", []),
            options["apply"],
            options["download_covers"],
            report,
        )
        self._backfill_upload_rows(payload.get("chart_upload_backfills", []), options["apply"], report)

    def _existing_country_map_rows(self):
        rows = []
        for name, (country, code) in ARTIST_COUNTRIES.items():
            rows.append({
                "name": name,
                "country": country,
                "country_code": code,
                "source_url": "charts.management.commands.update_artist_countries.ARTIST_COUNTRIES",
                "confidence": "existing-map",
            })
        return rows

    def _artist_index(self):
        index = {}
        artists = Artist.objects.exclude(status="archived")
        for artist in artists:
            values = [artist.name, artist.display_name, *(artist.aliases or [])]
            for value in values:
                key = _fold(value)
                if key:
                    index.setdefault(key, {})[artist.pk] = artist
        return {key: list(matches.values()) for key, matches in index.items()}

    def _release_index(self):
        index = {}
        releases = Release.objects.exclude(status="archived").select_related("artist")
        for release in releases:
            key = (
                _fold(release.title or release.canonical_title),
                _fold(release.artist.name),
                release.chart_type,
            )
            index.setdefault(key, []).append(release)
        return index

    def _resolve_artist(self, row, index=None):
        if row.get("id"):
            artist = Artist.objects.filter(pk=row["id"]).first()
            if artist:
                return artist, ""

        index = index or self._artist_index()
        key = _fold(row.get("name") or row.get("artist"))
        matches = index.get(key, [])
        if len(matches) == 1:
            return matches[0], ""
        if len(matches) > 1:
            return None, f"ambiguous artist match for {row.get('name')}: {[a.pk for a in matches]}"
        return None, f"artist not found: {row.get('id') or row.get('name')}"

    def _resolve_release(self, row, index=None):
        if row.get("id"):
            release = Release.objects.filter(pk=row["id"]).select_related("artist").first()
            if release:
                return release, ""

        index = index or self._release_index()
        chart_type = row.get("chart_type") or row.get("type") or ""
        key = (_fold(row.get("title")), _fold(row.get("artist")), chart_type)
        matches = index.get(key, [])
        if len(matches) == 1:
            return matches[0], ""
        if len(matches) > 1:
            return None, f"ambiguous release match for {row.get('title')} - {row.get('artist')}: {[r.pk for r in matches]}"
        return None, f"release not found: {row.get('id') or row.get('title')}"

    def _apply_artist_rows(self, rows, apply_changes, report):
        index = self._artist_index()
        touched = set()
        for row in rows:
            artist, miss = self._resolve_artist(row, index)
            if miss:
                report["artist_misses"].append(miss)
                continue
            if artist.pk in touched and row.get("confidence") == "existing-map":
                continue

            updates = []
            overwrite = _truthy(row.get("overwrite"))
            for field in ARTIST_FIELDS:
                if field not in row:
                    continue
                value = row.get(field)
                if _blank(value):
                    continue
                if field == "country_code":
                    value = _clean_code(value)
                current = getattr(artist, field, "")
                if _blank(current) or overwrite:
                    if current != value:
                        setattr(artist, field, value)
                        updates.append(field)

            if updates:
                touched.add(artist.pk)
                report["artists_updated"] += 1
                if apply_changes:
                    artist.save(update_fields=[*updates, "updated_at"])
            else:
                report["artists_skipped"] += 1

    def _apply_release_rows(self, rows, apply_changes, report):
        index = self._release_index()
        for row in rows:
            release, miss = self._resolve_release(row, index)
            if miss:
                report["release_misses"].append(miss)
                continue

            updates = []
            overwrite = _truthy(row.get("overwrite"))
            for field in RELEASE_FIELDS:
                if field not in row:
                    continue
                value = row.get(field)
                if _blank(value):
                    continue
                if field == "country_code":
                    value = _clean_code(value)
                current = getattr(release, field, None)
                if _blank(current) or overwrite:
                    if current != value:
                        setattr(release, field, value)
                        updates.append(field)

            if updates:
                report["release_rows_updated"] += 1
                if apply_changes:
                    release.save(update_fields=[*updates, "updated_at"])
            else:
                report["release_rows_skipped"] += 1

    def _propagate_lead_artist_countries(self, apply_changes, report):
        releases = Release.objects.exclude(status="archived").select_related("artist")
        for release in releases:
            country = release.artist.country or ""
            code = _clean_code(release.artist.country_code)
            if not country or not code:
                continue
            updates = []
            if release.country != country:
                release.country = country
                updates.append("country")
            if _clean_code(release.country_code) != code:
                release.country_code = code
                updates.append("country_code")
            if updates:
                report["release_countries_propagated"] += 1
                if apply_changes:
                    release.save(update_fields=[*updates, "updated_at"])

    def _link_featured_rows(self, rows, apply_changes, report):
        artist_index = self._artist_index()
        release_index = self._release_index()
        for row in rows:
            release, miss = self._resolve_release(row, release_index)
            if miss:
                report["featured_link_misses"].append(miss)
                continue
            ids = row.get("featured_artist_ids") or []
            names = row.get("featured_artist_names") or []
            self._link_featured_for_release(release, names, ids, artist_index, apply_changes, report, force=True)

    def _auto_link_text_featured(self, apply_changes, report):
        artist_index = self._artist_index()
        releases = Release.objects.exclude(status="archived").exclude(featured_artists="")
        releases = releases.prefetch_related("artist_credits").select_related("artist")
        for release in releases:
            if release.featured_artist_ids:
                text_names = split_artist_names(release.featured_artists)
                existing = {
                    credit.artist_id
                    for credit in release.artist_credits.all()
                    if credit.role == "featured"
                }
                resolved = [
                    artist.pk
                    for artist in self._resolve_featured_artists(text_names, [], artist_index)[0]
                ]
                if resolved and set(resolved).issubset(existing):
                    continue
            self._link_featured_for_release(
                release,
                split_artist_names(release.featured_artists),
                [],
                artist_index,
                apply_changes,
                report,
                force=False,
            )

    def _resolve_featured_artists(self, names, ids, artist_index):
        artists = []
        misses = []
        for artist_id in ids:
            artist = Artist.objects.filter(pk=artist_id).first()
            if artist:
                artists.append(artist)
            else:
                misses.append(f"featured artist id not found: {artist_id}")

        seen = {artist.pk for artist in artists}
        for name in names:
            key = _fold(name)
            matches = artist_index.get(key, [])
            if len(matches) == 1:
                if matches[0].pk not in seen:
                    artists.append(matches[0])
                    seen.add(matches[0].pk)
            elif len(matches) > 1:
                misses.append(f"ambiguous featured artist {name}: {[a.pk for a in matches]}")
            else:
                misses.append(f"featured artist not found: {name}")
        return artists, misses

    def _link_featured_for_release(self, release, names, ids, artist_index, apply_changes, report, force=False):
        artists, misses = self._resolve_featured_artists(names, ids, artist_index)
        if misses:
            report["featured_link_misses"].extend(
                f"{release.pk} {release.title}: {miss}" for miss in misses
            )
            report["featured_links_skipped"] += 1
            return
        if not artists:
            report["featured_links_skipped"] += 1
            return

        primary_ids = set(release.primary_artist_ids)
        artists = [artist for artist in artists if artist.pk not in primary_ids]
        if not artists:
            if release.featured_artists:
                report["featured_links_updated"] += 1
                if apply_changes:
                    release.featured_artists = ""
                    release.save(update_fields=["featured_artists", "updated_at"])
                    sync_release_chart_entry_snapshots(release)
            else:
                report["featured_links_skipped"] += 1
            return

        current_ids = [
            credit.artist_id
            for credit in release.artist_credits.all()
            if credit.role == "featured"
        ]
        target_ids = [artist.pk for artist in artists]
        target_text = format_artist_list([artist.display_name or artist.name for artist in artists])
        if current_ids == target_ids and release.featured_artists == target_text:
            report["featured_links_skipped"] += 1
            return
        if current_ids and not force:
            report["featured_links_skipped"] += 1
            return

        report["featured_links_updated"] += 1
        if not apply_changes:
            return

        release.artist_credits.filter(role="featured").delete()
        ReleaseArtistCredit.objects.bulk_create([
            ReleaseArtistCredit(
                release=release,
                artist=artist,
                role="featured",
                position=position,
            )
            for position, artist in enumerate(artists)
        ])
        release.featured_artists = target_text
        release.save(update_fields=["featured_artists", "updated_at"])
        release._prefetched_objects_cache = {}
        sync_release_chart_entry_snapshots(release)

    def _apply_cover_rows(self, rows, apply_changes, download_covers, report):
        release_index = self._release_index()
        for row in rows:
            release, miss = self._resolve_release(row, release_index)
            if miss:
                report["cover_misses"].append(miss)
                continue
            if release.cover_image:
                report["covers_skipped"] += 1
                continue
            artwork_url = self._best_artwork_url(row.get("artwork_url"))
            if not artwork_url:
                report["cover_misses"].append(f"{release.pk} {release.title}: missing artwork_url")
                continue

            if not apply_changes:
                report["covers_updated"] += 1
                continue
            if not download_covers:
                report["cover_misses"].append(
                    f"{release.pk} {release.title}: run again with --download-covers to fetch {_row_source(row)}"
                )
                continue

            try:
                content, ext = self._download(artwork_url)
            except Exception as exc:
                report["cover_misses"].append(f"{release.pk} {release.title}: cover download failed: {exc}")
                continue
            basename = slugify(f"{release.title}-{release.pk}") or f"cover-{release.pk}"
            release.cover_image.save(f"{basename}{ext}", ContentFile(content), save=False)
            release.save(update_fields=["cover_image", "updated_at"])
            report["covers_updated"] += 1

    def _best_artwork_url(self, url):
        url = str(url or "").strip()
        if not url:
            return ""
        return re.sub(r"/[0-9]+x[0-9]+bb\.(jpg|png|webp)$", r"/1200x1200bb.\1", url)

    def _download(self, url):
        request = Request(url, headers={"User-Agent": "NgomaChartsCMS/1.0"})
        with urlopen(request, timeout=30) as response:
            content = response.read()
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if not content:
            raise ValueError("empty response")
        ext = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }.get(content_type)
        if not ext:
            path_ext = PurePosixPath(urlparse(url).path).suffix.lower()
            ext = path_ext if path_ext in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"
        if ext == ".jpeg":
            ext = ".jpg"
        return content, ext

    def _backfill_upload_rows(self, rows, apply_changes, report):
        for row in rows:
            chart_type = row["chart_type"]
            year = int(row["year"])
            month = int(row["month"])
            existing = ChartUpload.objects.filter(
                chart_type=chart_type,
                year=year,
                month=month,
            ).exclude(status__in=["archived", "rolled_back"]).first()
            if existing:
                report["uploads_skipped"] += 1
                continue
            chart = MonthlyChart.objects.filter(
                chart_type=chart_type,
                year=year,
                month=month,
            ).first()
            if not chart:
                report["upload_misses"].append(f"{chart_type} {year}-{month:02d}: chart not found")
                continue
            row_count = chart.entries.filter(platform__isnull=True).count() or chart.entries.count()
            if row_count <= 0:
                report["upload_misses"].append(f"{chart_type} {year}-{month:02d}: chart has no entries")
                continue

            report["uploads_created"] += 1
            if not apply_changes:
                continue
            ChartUpload.objects.create(
                chart_type=chart_type,
                year=year,
                month=month,
                platform=None,
                status="published",
                row_count=row_count,
                original_filename=f"backfilled-{chart_type}-{year}-{month:02d}.json",
                rows_data=[],
                validation_summary={
                    "backfilled": True,
                    "source": "published MonthlyChart",
                    "row_count": row_count,
                    "warning_count": 0,
                    "error_count": 0,
                },
                uploaded_by=chart.published_by,
                approved_by=chart.published_by,
                published_by=chart.published_by,
                approved_at=chart.published_at or timezone.now(),
                published_at=chart.published_at or timezone.now(),
                notes=(
                    "Backfilled from an already published MonthlyChart to satisfy "
                    "CMS upload-history audit. No workbook file was attached."
                ),
            )

    def _write_audit_log(self, payload, report):
        try:
            AuditLog.objects.create(
                action="fix_cms_attention_alerts",
                module="dashboard",
                object_type="CMSAttentionRepair",
                object_id="20260731",
                object_repr="CMS attention alert repair 2026-07-31",
                old_value={},
                new_value={
                    "source": payload.get("source", ""),
                    "summary": report,
                    "timestamp": timezone.now().isoformat(),
                },
                reason="Source-backed CMS attention alert repair command",
                user=None,
                ip_address=None,
                user_agent="management-command",
            )
        except Exception:
            pass

    def _print_report(self, report, apply_changes):
        mode = "APPLIED" if apply_changes else "DRY RUN"
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{mode}: CMS attention alert repair summary"))
        for key in (
            "artists_updated",
            "artists_skipped",
            "release_rows_updated",
            "release_rows_skipped",
            "release_countries_propagated",
            "featured_links_updated",
            "featured_links_skipped",
            "covers_updated",
            "covers_skipped",
            "uploads_created",
            "uploads_skipped",
        ):
            self.stdout.write(f"  {key}: {report[key]}")

        for title, key in (
            ("Artist misses", "artist_misses"),
            ("Release misses", "release_misses"),
            ("Featured link misses", "featured_link_misses"),
            ("Cover misses", "cover_misses"),
            ("Upload misses", "upload_misses"),
        ):
            values = report[key]
            if not values:
                continue
            self.stdout.write(self.style.WARNING(f"\n{title}: {len(values)}"))
            for value in values[:30]:
                self.stdout.write(f"  - {_display(value)}")
            if len(values) > 30:
                self.stdout.write(f"  ...and {len(values) - 30} more")

        if report["duplicate_notes"]:
            self.stdout.write(self.style.WARNING("\nDuplicate review notes:"))
            for note in report["duplicate_notes"]:
                self.stdout.write(f"  - {_display(note)}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("\nNo data was written. Re-run with --apply to save changes."))
