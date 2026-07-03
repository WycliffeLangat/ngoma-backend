from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from charts.models import (
    Artist,
    ArtistMergeLog,
    MonthlyChartEntry,
    Release,
    ReleaseArtistCredit,
)
from charts.cms_utils import harmonize_chart_history


class Command(BaseCommand):
    help = (
        "Repair releases that still show an archived artist's "
        "'<name> (merged <id>)' label after an artist merge. This happened "
        "because the merge endpoint moved releases the duplicate directly "
        "owned, but left ReleaseArtistCredit rows (primary/featured billing "
        "on OTHER releases) pointing at the archived duplicate. Re-points "
        "every such credit — and any stray Release.artist FK — onto the "
        "surviving artist. Run with --dry-run first (the default)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help="Actually write changes. Without this flag, only reports what would change.",
        )

    def _resolve_root(self, artist, keeper_by_dup_id, seen=None):
        """Follow merged_artist_id -> primary_artist chains to the final living artist."""
        seen = seen or set()
        if artist.id in seen:
            return artist  # merge-log cycle (shouldn't happen) — stop here
        seen.add(artist.id)
        keeper = keeper_by_dup_id.get(artist.id)
        if keeper is None or keeper.id == artist.id:
            return artist
        return self._resolve_root(keeper, keeper_by_dup_id, seen)

    def handle(self, *args, **options):
        apply_changes = options['apply']
        mode = "APPLYING" if apply_changes else "DRY RUN (pass --apply to write)"
        self.stdout.write(self.style.WARNING(f"Mode: {mode}"))

        # Latest merge log per duplicate id tells us who the duplicate was folded into.
        keeper_by_dup_id = {}
        for log in ArtistMergeLog.objects.filter(merged_artist_id__isnull=False).order_by('created_at'):
            keeper_by_dup_id[log.merged_artist_id] = log.primary_artist

        archived = Artist.objects.filter(name__regex=r'\(merged \d+\)$')
        self.stdout.write(f"Found {archived.count()} archived/merged artist row(s).")

        fixed_credits = 0
        deleted_dupe_credits = 0
        fixed_release_fks = 0
        unresolved = []
        touched_artist_ids = set()

        with transaction.atomic():
            for dup in archived:
                root = self._resolve_root(dup, keeper_by_dup_id)
                if root.id == dup.id:
                    unresolved.append(dup)
                    continue
                touched_artist_ids.add(root.id)

                # 1. ReleaseArtistCredit rows (primary or featured billing)
                #    still pointing at the archived duplicate.
                existing_root_credits = set(
                    ReleaseArtistCredit.objects.filter(artist=root)
                    .values_list('release_id', 'role')
                )
                for credit in list(ReleaseArtistCredit.objects.filter(artist=dup)):
                    key = (credit.release_id, credit.role)
                    if key in existing_root_credits:
                        self.stdout.write(
                            f"  [credit] release {credit.release_id} already credits "
                            f"{root.name} as {credit.role} — dropping duplicate row from {dup.name!r}"
                        )
                        if apply_changes:
                            credit.delete()
                        deleted_dupe_credits += 1
                    else:
                        self.stdout.write(
                            f"  [credit] release {credit.release_id}: {credit.role} "
                            f"{dup.name!r} -> {root.name!r}"
                        )
                        if apply_changes:
                            credit.artist = root
                            credit.save(update_fields=['artist'])
                        existing_root_credits.add(key)
                        fixed_credits += 1

                # 2. Any release still directly owned (Release.artist FK) by
                #    the archived duplicate — should not happen post-merge,
                #    but older/manual merges may have left this stale.
                for rel in list(Release.objects.filter(artist=dup)):
                    twin = Release.objects.filter(
                        canonical_title=rel.canonical_title,
                        artist=root,
                        chart_type=rel.chart_type,
                    ).exclude(pk=rel.pk).first()
                    if twin:
                        self.stdout.write(
                            f"  [release] {rel.id} ({rel.title!r}) duplicates release "
                            f"{twin.id} under {root.name!r} — needs a manual release merge, skipping"
                        )
                        unresolved.append(rel)
                        continue
                    self.stdout.write(
                        f"  [release] {rel.id} ({rel.title!r}): artist {dup.name!r} -> {root.name!r}"
                    )
                    if apply_changes:
                        rel.artist = root
                        rel.save(update_fields=['artist'])
                    fixed_release_fks += 1

            if not apply_changes:
                transaction.set_rollback(True)

        if apply_changes and touched_artist_ids:
            chart_ids = list(
                MonthlyChartEntry.objects.filter(
                    Q(release__artist__in=touched_artist_ids)
                    | Q(release__artist_credits__artist__in=touched_artist_ids)
                )
                .values_list('chart_id', flat=True).distinct()
            )
            if chart_ids:
                self.stdout.write(f"Re-harmonizing {len(chart_ids)} affected chart(s)...")
                harmonize_chart_history(chart_ids=chart_ids)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Credits re-pointed: {fixed_credits} | duplicate credit rows dropped: {deleted_dupe_credits} | "
            f"release FKs re-pointed: {fixed_release_fks}"
        ))
        if unresolved:
            self.stdout.write(self.style.WARNING(
                f"{len(unresolved)} item(s) need manual review (no merge-log keeper found, "
                "or a conflicting twin release exists):"
            ))
            for item in unresolved:
                label = getattr(item, 'name', None) or getattr(item, 'title', None)
                self.stdout.write(f"  - {type(item).__name__} {item.id}: {label!r}")

        if not apply_changes:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Dry run only — re-run with --apply to write these changes."))
