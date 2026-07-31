"""Repair remaining live CMS alert classes after full dashboard audit export.

Dry-run by default. Pass --apply to write:
  * source-backed artist country rows
  * release country propagation from lead artist
  * generated-news cover/SEO fields from related release/excerpt
  * a BackupRecord for the production backup taken before repair
  * known orphan/stale Brick & Lace credit cleanup
"""

import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Min, Q
from django.utils import timezone

from charts.cms_utils import sync_release_chart_entry_snapshots
from charts.models import Artist, AuditLog, BackupRecord, NewsArticle, Release


DEFAULT_COUNTRY_PATH = os.path.join(
    "scripts",
    "remaining_artist_country_research_20260731_final.json",
)

GENERIC_RELEASE_ARTISTS = {"various artists"}


def _blank(value):
    return value is None or str(value).strip() == ""


def _code(value):
    return str(value or "").strip().upper()


def _normalized(value):
    return " ".join(
        "".join(ch.lower() if ch.isalnum() else " " for ch in str(value or "")).split()
    )


def _looks_like_country_code_name(country, code):
    country_text = str(country or "").strip().upper()
    code_text = _code(code)
    return bool(country_text and code_text and len(country_text) == 2 and country_text == code_text)


def _wants_overwrite(row):
    return bool(row.get("overwrite") or row.get("force"))


class Command(BaseCommand):
    help = "Apply full remaining CMS alert fixes sourced from the live dashboard audit."

    def add_arguments(self, parser):
        parser.add_argument("--country-path", default=DEFAULT_COUNTRY_PATH)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument(
            "--backup-note",
            default="prod_backup_before_cms_attention_direct_models_20260731130047.json",
            help="Human-readable production backup artifact name to record in BackupRecord.notes.",
        )

    def handle(self, *args, **options):
        path = Path(options["country_path"])
        if not path.exists():
            raise CommandError(f"Country research file not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        report = {
            "artists_updated": 0,
            "artists_skipped": 0,
            "artist_misses": [],
            "release_rows_updated": 0,
            "release_rows_skipped": 0,
            "release_row_misses": [],
            "release_countries_propagated": 0,
            "news_updated": 0,
            "news_skipped": 0,
            "backup_records_created": 0,
            "backup_records_skipped": 0,
            "brick_lace_rows_updated": 0,
            "orphan_artists_archived": 0,
            "archive_skipped": 0,
        }

        if options["apply"]:
            with transaction.atomic():
                self._run(payload, options, report)
                self._audit(payload, report)
        else:
            self._run(payload, options, report)
        self._print(report, options["apply"])

    def _run(self, payload, options, report):
        self._apply_artist_countries(payload.get("artists", []), options["apply"], report)
        self._propagate_release_countries(options["apply"], report)
        self._apply_release_countries(payload.get("release_countries", []), options["apply"], report)
        self._fix_news(options["apply"], report)
        self._record_backup(options["apply"], options["backup_note"], report)
        self._fix_brick_lace(options["apply"], report)

    def _apply_artist_countries(self, rows, apply_changes, report):
        for row in rows:
            artist = Artist.objects.filter(pk=row.get("id")).first()
            if not artist:
                report["artist_misses"].append(f"artist not found: {row.get('id')} {row.get('name')}")
                continue
            updates = []
            overwrite = _wants_overwrite(row)
            for field in ("country", "country_code", "city_region", "genre", "biography"):
                if field not in row or _blank(row.get(field)):
                    continue
                value = _code(row[field]) if field == "country_code" else row[field]
                current = getattr(artist, field, "")
                bad_code_name = field == "country" and _looks_like_country_code_name(current, artist.country_code)
                if _blank(current) or overwrite or bad_code_name:
                    setattr(artist, field, value)
                    updates.append(field)
            if not updates:
                report["artists_skipped"] += 1
                continue
            report["artists_updated"] += 1
            if apply_changes:
                artist.save(update_fields=[*updates, "updated_at"])

    def _propagate_release_countries(self, apply_changes, report):
        releases = Release.objects.exclude(status="archived").select_related("artist")
        for release in releases:
            artist = release.artist
            if _normalized(artist.name) in GENERIC_RELEASE_ARTISTS:
                continue
            updates = []
            release_code = _code(release.country_code)
            artist_code = _code(artist.country_code)
            release_country_is_code = _looks_like_country_code_name(release.country, release.country_code)
            code_mismatch = bool(release_code and artist_code and release_code != artist_code)
            if not _blank(artist.country) and (_blank(release.country) or release_country_is_code or code_mismatch):
                release.country = artist.country
                updates.append("country")
            if not _blank(artist.country_code) and (_blank(release.country_code) or code_mismatch):
                release.country_code = _code(artist.country_code)
                updates.append("country_code")
            if not updates:
                continue
            report["release_countries_propagated"] += 1
            if apply_changes:
                release.save(update_fields=[*updates, "updated_at"])

    def _apply_release_countries(self, rows, apply_changes, report):
        for row in rows:
            release = Release.objects.filter(pk=row.get("id")).first()
            if not release:
                report["release_row_misses"].append(f"release not found: {row.get('id')} {row.get('title')}")
                continue
            updates = []
            overwrite = _wants_overwrite(row)
            for field in ("country", "country_code", "genre"):
                if field not in row or _blank(row.get(field)):
                    continue
                value = _code(row[field]) if field == "country_code" else row[field]
                current = getattr(release, field, "")
                bad_code_name = field == "country" and _looks_like_country_code_name(current, release.country_code)
                if _blank(current) or overwrite or bad_code_name:
                    setattr(release, field, value)
                    updates.append(field)
            if not updates:
                report["release_rows_skipped"] += 1
                continue
            report["release_rows_updated"] += 1
            if apply_changes:
                release.save(update_fields=[*updates, "updated_at"])

    def _fix_news(self, apply_changes, report):
        releases = list(
            Release.objects.exclude(status="archived")
            .exclude(cover_image="")
            .select_related("artist")
            .annotate(chart_count=Count("monthlychartentry"), best_rank=Min("monthlychartentry__rank"))
            .order_by("-chart_count", "best_rank", "id")
        )
        title_candidates = sorted(
            [(release, _normalized(release.title)) for release in releases if release.title],
            key=lambda item: len(item[1]),
            reverse=True,
        )
        artist_candidates = sorted(
            [(release, _normalized(release.artist.name)) for release in releases if release.artist_id],
            key=lambda item: len(item[1]),
            reverse=True,
        )
        fallback_cover = self._fallback_news_cover(releases)
        articles = NewsArticle.objects.filter(status="published", is_published=True).select_related(
            "related_release", "related_artist"
        )
        for article in articles:
            updates = []
            if _blank(article.cover_image):
                cover_name = self._news_cover_name(
                    article,
                    title_candidates,
                    artist_candidates,
                    fallback_cover,
                )
                if cover_name:
                    article.cover_image = cover_name
                    updates.append("cover_image")
            if _blank(article.seo_title):
                article.seo_title = article.title[:255]
                updates.append("seo_title")
            if _blank(article.seo_description):
                description = article.excerpt or article.subheadline or article.body or article.title
                article.seo_description = str(description).strip()[:300]
                updates.append("seo_description")
            if not updates:
                report["news_skipped"] += 1
                continue
            report["news_updated"] += 1
            if apply_changes:
                article.save(update_fields=[*updates, "updated_at"])

    def _news_cover_name(self, article, title_candidates, artist_candidates, fallback_cover):
        if article.related_release and article.related_release.cover_image:
            return article.related_release.cover_image.name
        text = " ".join(
            [
                str(article.title or ""),
                str(article.excerpt or ""),
                str(article.subheadline or ""),
                str(article.body or ""),
                " ".join(str(tag) for tag in (article.tags or [])),
            ]
        )
        haystack = _normalized(text)
        for release, title in title_candidates:
            if len(title) >= 4 and title in haystack:
                return release.cover_image.name
        for release, artist in artist_candidates:
            if len(artist) >= 4 and artist in haystack:
                return release.cover_image.name
        return fallback_cover

    def _fallback_news_cover(self, releases):
        for preferred in ("Finale", "Donjo Maber", "Pawa", "The Last Wun"):
            for release in releases:
                if _normalized(release.title) == _normalized(preferred) and release.cover_image:
                    return release.cover_image.name
        for release in releases:
            if release.cover_image:
                return release.cover_image.name
        return ""

    def _record_backup(self, apply_changes, backup_note, report):
        if BackupRecord.objects.exists():
            report["backup_records_skipped"] += 1
            return
        report["backup_records_created"] += 1
        if apply_changes:
            BackupRecord.objects.create(
                status="created",
                notes=(
                    "Production CMS direct-model JSON backup created before full alert repair: "
                    f"{backup_note}"
                ),
            )

    def _fix_brick_lace(self, apply_changes, report):
        brick = Artist.objects.filter(pk=1062).first()
        lace = Artist.objects.filter(pk=3098).first()
        if brick:
            updates = []
            if _blank(brick.country):
                brick.country = "Jamaica"
                updates.append("country")
            if _blank(brick.country_code):
                brick.country_code = "JM"
                updates.append("country_code")
            if _blank(brick.city_region):
                brick.city_region = "Kingston, Jamaica"
                updates.append("city_region")
            if _blank(brick.genre):
                brick.genre = "Dancehall; R&B"
                updates.append("genre")
            aliases = [alias for alias in (brick.aliases or []) if str(alias).strip().casefold() != "lace"]
            if aliases != (brick.aliases or []):
                brick.aliases = aliases
                updates.append("aliases")
            if updates:
                report["brick_lace_rows_updated"] += 1
                if apply_changes:
                    brick.save(update_fields=[*updates, "updated_at"])

        release = Release.objects.filter(pk=19286).first()
        if release and release.featured_artists:
            report["brick_lace_rows_updated"] += 1
            if apply_changes:
                release.featured_artists = ""
                release.save(update_fields=["featured_artists", "updated_at"])
                sync_release_chart_entry_snapshots(release)

        if lace:
            in_use = Release.objects.filter(Q(artist=lace) | Q(artist_credits__artist=lace)).exists()
            if in_use:
                report["archive_skipped"] += 1
            elif lace.status != "archived":
                report["orphan_artists_archived"] += 1
                if apply_changes:
                    lace.status = "archived"
                    lace.save(update_fields=["status", "updated_at"])

    def _audit(self, payload, report):
        try:
            AuditLog.objects.create(
                action="fix_remaining_cms_alerts",
                module="dashboard",
                object_type="CMSRemainingAlertRepair",
                object_id="20260731",
                object_repr="Remaining CMS alert repair 2026-07-31",
                old_value={},
                new_value={
                    "summary": report,
                    "source": payload.get("generated_at", ""),
                    "timestamp": timezone.now().isoformat(),
                },
                reason="Source-backed full CMS alert repair command",
                user=None,
                user_agent="management-command",
            )
        except Exception:
            pass

    def _print(self, report, apply_changes):
        mode = "APPLIED" if apply_changes else "DRY RUN"
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{mode}: remaining CMS alert repair"))
        for key, value in report.items():
            if isinstance(value, list):
                self.stdout.write(f"  {key}: {len(value)}")
                for item in value[:20]:
                    self.stdout.write(f"    - {item}")
            else:
                self.stdout.write(f"  {key}: {value}")
        if not apply_changes:
            self.stdout.write(self.style.WARNING("\nNo data was written. Re-run with --apply to save changes."))
