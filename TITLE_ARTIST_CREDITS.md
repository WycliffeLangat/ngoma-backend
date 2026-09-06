# Artists credited in release titles

`charts/title_credits.py` registers a release-save hook in `ChartsConfig.ready()`.
Normal Django saves (including CMS editing and upload/import creation) add
explicit title feature credits to `ReleaseArtistCredit` and `featured_artists`.
The title is preserved. Existing credits are retained. Primary artists and
already-linked artists are not linked again as featured artists. Registered
group names and artist aliases are resolved before new artists are created.

Recognized forms include `(Featuring A & B)`, `[feat. A]`, `(ft. A)`,
`Song feat. A`, and `(with A)`. Ordinary title words and incomplete names
ending in an ellipsis are not treated as artist names.

## Historical records / production rollout

Railway runs the backfill automatically after migrations in its pre-deploy
command. If either step fails, the command exits unsuccessfully. The backfill
covers every stored date, including 2025 onward, and is safe to repeat on later
deployments. New imports and saves use the release-save hook.

For a manual preview or a deployment outside Railway, run:

```sh
python manage.py backfill_title_credits
python manage.py backfill_title_credits --apply
```

The first command previews and rolls back all changes. The second updates
every release with a recognizable title credit and fills monthly and regional
entry snapshots while retaining entry-specific credits. It also changes the
public data revision so connected clients refresh. Both commands are safe to
repeat. Back up the production database before the first applied run.

Future scripts using `bulk_create`, `bulk_update`, or queryset `update` bypass
Django save signals and must call `sync_title_credits(release)` afterward (or
run the backfill). Historical migration models also do not emit this signal.

No frontend deployment is necessary: public and CMS serializers already expose
the structured artist links and credit text.

## Regression checks

Run `python scripts/test_title_credits.py` from the backend environment. It uses
an isolated in-memory database and the current schema, skipping workbook seed
migrations. It checks title parsing, automatic saves/imports, historical
backfill, repeated execution, and the public API regression suite.
