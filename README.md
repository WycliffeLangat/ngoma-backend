# Ngoma Charts Backend

Kenya's official music charts API. Built with Django + Django REST Framework + PostgreSQL.

## Quick Local Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run migrations
python manage.py migrate

# 3. Seed the chart data
python manage.py seed_data --clear

# 4. Create admin user
python manage.py createsuperuser

# 5. Run the background chart worker in a second terminal
python manage.py process_chart_jobs

# 6. Run server
python manage.py runserver
```

Visit `http://localhost:8000/admin/` for the admin panel.
Visit `http://localhost:8000/api/v1/charts/latest/?chart_type=singles` to see the API.

## Deploy to Production

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for step-by-step Railway/Render deployment instructions.

## API Endpoints

All endpoints are under `/api/v1/`.

### Public app bootstrap

- `GET /app-data/` — the frontend's single source of truth for all published chart periods, singles, albums, platform charts, artists, releases, news, certifications and site settings
- `GET /app-data/revision/` — lightweight revision check used to detect CMS publications and edits

The `/app-data/` payload includes numeric `month_options`, `latest_published_month`,
and `latest_published_by_chart_type` metadata. The React frontend sorts periods by
`year` and `month` and never bundles or falls back to local chart records.

### Charts
- `GET /charts/?chart_type=singles` — list all monthly charts
- `GET /charts/latest/?chart_type=singles&platform=combined` — latest published chart
- `GET /charts/{id}/?platform=combined` — specific chart with entries
- `GET /charts/year_end/?year=2025&chart_type=singles` — year-end aggregated
- `GET /charts/analytics/?chart_type=singles&year=2025` — analytics for charts

Platform filter values: `combined` (default), or platform ID (1=Apple Music, 2=Audiomack, etc.)

### Artists
- `GET /artists/` — list (with `?chart_type=singles` filter)
- `GET /artists/{id}/` — artist detail
- `GET /artists/{id}/chart_history/?chart_type=singles` — chart appearances over time
- `GET /artists/{id}/stats/?chart_type=singles` — total points, peak, etc.

### Releases (songs/albums)
- `GET /releases/` — list (filterable by `chart_type`, `artist`)
- `GET /releases/{id}/journey/` — full cross-platform chart journey

### Other
- `GET /platforms/` — list of tracked platforms
- `GET /certifications/?level=diamond&chart_type=singles` — Diamond/Platinum/Gold awards
- `GET /news/` — published news articles
- `POST /ai/analyst/` — currently disabled by default and not used by the public app

The AI Analyst code is retained for possible future use, but the endpoint returns a disabled response unless `AI_ANALYST_ENABLED=True` is explicitly configured.

### Admin-only
- `POST /uploads/` — upload weekly xlsx file (auto-processes)
- `POST /uploads/rebuild_month/` — manually rebuild monthly aggregates
- `GET /cms/chart-jobs/` - inspect queued/running/succeeded/failed chart calculation jobs
- `POST /normalization-rules/` — manage artist/title spelling rules

## Models

| Model | Purpose |
|---|---|
| Platform | Apple Music, Audiomack, Boomplay, Spotify, YouTube, Shazam |
| Artist | Music artists, deduplicated by name |
| Release | A song (single) or album by an artist |
| MonthlyChart | The monthly chart for a year/month/chart_type |
| MonthlyChartEntry | A song/album's position on a monthly chart |
| WeeklyUpload | A raw uploaded xlsx file |
| PlatformChartEntry | Per-week, per-platform chart entry |
| NewsArticle | Editorial news content |
| Certification | Ngoma/Gold/Platinum/Diamond awards |
| NormalizationRule | Artist/title spelling fixes |

## Pipeline

`charts/pipeline.py` handles all data processing:
- `process_weekly_upload(upload)` — parse xlsx, normalize, dedupe, save entries
- `rebuild_monthly_chart(chart_type, year, month)` — recompute aggregates
- `award_certifications(chart_type)` — compatibility wrapper for canonical certification recalculation

The pipeline runs automatically when you upload a weekly file via the admin.

### Canonical scoring methodology

- Weekly source charts are fixed Top 100 charts for both singles and albums.
  Rank 1 earns 100 raw points and rank 100 earns 1 (`101 - rank`). Rows below
  rank 100 are never processed.
- Monthly platform rankings sum those weekly raw points. Combined rankings sum
  the monthly raw platform totals.
- `MonthlyChartEntry.raw_total_points` is the raw score used only for ranking.
  `MonthlyChartEntry.total_points` is the public Top 50 score (`51 - rank`);
  rank 51 or worse stores zero public points.
- Combined entries use platform coverage of 6 for singles and 2 for albums.
- Certifications, public analytics, history, and artist points use published
  Combined Top 50 public points only.
- The Combined Artist Chart uses Combined Singles Top 50 plus Combined Albums
  Top 50. Platform artist charts use only that platform's supported Top 50
  singles/albums rows. Every credited artist receives full points.

The formulas and supported-platform lists live in `charts/methodology.py`;
editable platform metadata cannot change scoring.
### Background calculation jobs

Weekly upload processing, final-chart publishing, month rebuilds, and chart
history harmonization are queued as `ChartCalculationJob` records so CMS
requests can return quickly. Run `python manage.py process_chart_jobs` beside
the web server to process queued work. Production startup already launches the
worker helper in the same service, and the `Procfile` also exposes a dedicated
`worker` process if you split web and worker services later.

Set `CHART_JOBS_ASYNC=false` for local debugging when you want the old
request-blocking behavior. Set `REDIS_URL` to use Redis as Django's shared
cache for public `/app-data/` payloads across gunicorn workers.


### Rebuild after a methodology deployment

Preview the complete historical repair:

```bash
python manage.py rebuild_chart_methodology --all --dry-run
```

Apply it after reviewing the summary:

```bash
python manage.py rebuild_chart_methodology --all
```

Periods with weekly source entries are recalculated exactly. Monthly-only
periods preserve their stored ordering score in `raw_total_points`, then
recalculate public points, coverage, history, artist credits, and
certifications. That is the safest available reconstruction when source
weekly workbooks are unavailable.

## Certification Thresholds

| Level | Points |
|---|---|
| Gold | 200+ |
| Platinum | 400+ |
| Diamond | 600+ |

## License & Contact

Built for Ngoma Charts Kenya.
