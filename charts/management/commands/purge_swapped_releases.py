"""Permanently remove releases created with artist/title fields reversed.

The command is intentionally conservative:

* An exact inverse companion is removable only when it has no chart,
  certification, or weekly-source support and the other orientation does.
* If neither orientation has support, the candidate is removable only when
  its credited artist owns exactly one release and the inverse artist owns
  at least two.
* A short, audited fingerprint list covers historical malformed rows that
  cannot be represented as an exact inverse pair.

Dry-run is the default. Use --apply for the destructive pass.
"""

from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from charts.cms_utils import bump_public_revision, harmonize_chart_history
from charts.models import (
    Artist,
    AuditLog,
    Certification,
    MonthlyChartEntry,
    PlatformChartEntry,
    RegionalChartEntry,
    Release,
)


def _norm(value):
    return " ".join(str(value or "").split()).casefold()


# Exact rows confirmed from the master workbook and external catalogue data.
# The value records the source provenance retained in the cleanup audit.
BAD_FINGERPRINTS = {
    ("matata", "matata", "singles"): (
        "YouTube; September-December 2025 and January 2026; malformed "
        "MPISHI by Matata ft. Bien credit"
    ),
    ("natamba", "natamba", "singles"): (
        "YouTube; September 2025 and March 2026; Natamba is by Aslay"
    ),
    ("zuchu", "zuchu", "singles"): (
        "YouTube; May 2026; malformed Hapo by G Nako & Zuchu credit"
    ),
    ("lava lava", "basi tu - lava lava", "singles"): (
        "YouTube; June 2026; malformed Basi Tu by Lava Lava ft. Mbosso credit"
    ),
    (
        "namlilia malebo",
        "haukusikia - albert muziki entertainment",
        "singles",
    ): (
        "Audiomack; June 2026; release title leaked into the artist credit"
    ),
    ("the art of loving", "the art of loving", "albums"): (
        "Apple Music; October 2025; duplicate malformed artist credit"
    ),
    (
        "2026 kenyan club bangers",
        "nonstop bangers non stop party mix - nonstop bangers mix - arbantone",
        "singles",
    ): (
        "Boomplay; June 2026; mix titles leaked into the artist credit"
    ),
}

# Some malformed credits became orphan Artist rows after an earlier release
# cleanup. They are safe to remove only when they still have no releases and
# no release-credit references.
KNOWN_ORPHAN_ARTIST_NAMES = {
    "BIEN - MPISHI",
    "BIEN - MPISHI #mpishiEP",
    "Nonstop Bangers Non stop Party Mix - Nonstop Bangers Mix - Arbantone",
    "ohangla club bangers mix - DJ WIZZY 254",
}


def _support_counts(release_ids):
    counts = Counter()
    for model in (
        MonthlyChartEntry,
        PlatformChartEntry,
        RegionalChartEntry,
        Certification,
    ):
        rows = (
            model.objects.filter(release_id__in=release_ids)
            .values("release_id")
            .annotate(total=Count("id"))
        )
        for row in rows:
            counts[row["release_id"]] += row["total"]
    return counts


def _release_key(release):
    return (
        _norm(release.title),
        _norm(release.artist.name),
        release.chart_type,
    )


class Command(BaseCommand):
    help = (
        "Hard-delete unsupported exact artist/title inversions and confirmed "
        "historical malformed releases. Defaults to a dry-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Permanently delete the detected releases and orphan artists.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print every detected release instead of the first 25.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        releases = list(Release.objects.select_related("artist").order_by("id"))
        release_ids = [release.id for release in releases]
        support = _support_counts(release_ids)
        artist_release_counts = Counter(release.artist_id for release in releases)
        by_key = {_release_key(release): release for release in releases}

        reasons = {}
        seen_pairs = set()
        for release in releases:
            key = _release_key(release)
            if key[0] == key[1]:
                continue
            inverse = (key[1], key[0], key[2])
            other = by_key.get(inverse)
            if other is None:
                continue
            pair = tuple(sorted((release.id, other.id)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            release_support = support[release.id]
            other_support = support[other.id]
            if (release_support == 0) != (other_support == 0):
                bad = release if release_support == 0 else other
                good = other if bad is release else release
                reasons[bad.id] = (
                    "Unsupported exact inverse companion of "
                    f"{good.title!r} by {good.artist.name!r}; traced to the "
                    "reversed July 2026 weekly upload."
                )
                continue

            if release_support == other_support == 0:
                release_artist_total = artist_release_counts[release.artist_id]
                other_artist_total = artist_release_counts[other.artist_id]
                if release_artist_total == 1 and other_artist_total >= 2:
                    reasons[release.id] = (
                        "Unsupported exact inverse companion; the inverse "
                        "artist has established release history."
                    )
                elif other_artist_total == 1 and release_artist_total >= 2:
                    reasons[other.id] = (
                        "Unsupported exact inverse companion; the inverse "
                        "artist has established release history."
                    )

        for release in releases:
            fingerprint = _release_key(release)
            provenance = BAD_FINGERPRINTS.get(fingerprint)
            if provenance:
                reasons.setdefault(
                    release.id,
                    f"Confirmed malformed source row: {provenance}.",
                )

        candidates = [
            release for release in releases if release.id in reasons
        ]
        reason_counts = Counter(
            "exact_inverse"
            if "exact inverse" in reasons[release.id].casefold()
            else "historical_fingerprint"
            for release in candidates
        )

        mode = "APPLY" if apply_changes else "DRY RUN"
        self.stdout.write(self.style.WARNING(
            f"[{mode}] Detected {len(candidates)} release(s): "
            f"{reason_counts['exact_inverse']} exact inverse companion(s), "
            f"{reason_counts['historical_fingerprint']} historical malformed "
            "row(s)."
        ))
        shown = candidates if options["verbose"] else candidates[:25]
        for release in shown:
            self.stdout.write(
                f"  [{release.id}] {release.title!r} / "
                f"{release.artist.name!r} ({release.chart_type}) - "
                f"{reasons[release.id]}"
            )
        if len(shown) < len(candidates):
            self.stdout.write(
                f"  ... {len(candidates) - len(shown)} more "
                "(use --verbose to print all)"
            )

        if not apply_changes:
            self.stdout.write(self.style.SUCCESS(
                "Dry-run complete; no database rows changed."
            ))
            return

        if not candidates:
            self.stdout.write(self.style.SUCCESS("Nothing to delete."))
            return

        bad_ids = [release.id for release in candidates]
        chart_ids = list(
            MonthlyChartEntry.objects.filter(release_id__in=bad_ids)
            .values_list("chart_id", flat=True)
            .distinct()
        )
        candidate_artist_ids = {release.artist_id for release in candidates}
        candidate_artist_ids.update(
            Artist.objects.filter(name__in=KNOWN_ORPHAN_ARTIST_NAMES)
            .values_list("id", flat=True)
        )

        audit_rows = [
            AuditLog(
                action="hard_deleted_swapped_release",
                module="releases",
                object_type="Release",
                object_id=str(release.id),
                object_repr=str(release)[:255],
                old_value={
                    "id": release.id,
                    "title": release.title,
                    "artist": release.artist.name,
                    "chart_type": release.chart_type,
                    "support_rows": support[release.id],
                },
                reason=reasons[release.id],
            )
            for release in candidates
        ]

        with transaction.atomic():
            AuditLog.objects.bulk_create(audit_rows, batch_size=100)
            Release.objects.filter(id__in=bad_ids).delete()

            orphan_qs = (
                Artist.objects.filter(id__in=candidate_artist_ids)
                .annotate(
                    release_count=Count("releases", distinct=True),
                    credit_count=Count("release_credits", distinct=True),
                )
                .filter(release_count=0, credit_count=0)
            )
            orphan_names = list(orphan_qs.values_list("name", flat=True))
            orphan_qs.delete()

            harmonization = (
                harmonize_chart_history(chart_ids=chart_ids)
                if chart_ids
                else {}
            )
            bump_public_revision()

        self.stdout.write(self.style.SUCCESS(
            f"Hard-deleted {len(candidates)} release(s) and "
            f"{len(orphan_names)} orphan artist(s)."
        ))
        if harmonization:
            self.stdout.write(
                "Rebuilt affected chart history: "
                f"{harmonization.get('charts', 0)} chart period(s), "
                f"{harmonization.get('rank_changes', 0)} rank change(s)."
            )
