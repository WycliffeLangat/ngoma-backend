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

# 5. Run server
python manage.py runserver
```

Visit `http://localhost:8000/admin/` for the admin panel.
Visit `http://localhost:8000/api/v1/charts/latest/?chart_type=singles` to see the API.

## Deploy to Production

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for step-by-step Railway/Render deployment instructions.

## API Endpoints

All endpoints are under `/api/v1/`.

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
- `award_certifications(chart_type)` — auto-award based on cumulative points

The pipeline runs automatically when you upload a weekly file via the admin.

## Certification Thresholds

| Level | Points |
|---|---|
| Gold | 200+ |
| Platinum | 400+ |
| Diamond | 600+ |

## License & Contact

Built for Ngoma Charts Kenya.
