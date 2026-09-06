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

Deploy the backend changes, then run:

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
