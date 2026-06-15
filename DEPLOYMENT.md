# Ngoma Charts Backend — Deployment Guide

Step-by-step guide to deploy the backend to a live URL. Recommended platform: **Railway** (simplest, ~$5/month, includes PostgreSQL).

---

## Option A: Railway (Recommended)

### 1. Prepare your code

You already have everything. The key files are:
- `Procfile` — tells Railway how to run the app
- `requirements.txt` — Python dependencies
- `runtime.txt` — Python version
- `.env.example` — shows required env vars
- `.gitignore` — keeps secrets out of git

### 2. Push to GitHub

```bash
cd ngoma_backend
git init
git add .
git commit -m "Initial Ngoma Charts backend"
git branch -M main
# Create a new repo at github.com (e.g. github.com/yourname/ngoma-backend)
git remote add origin https://github.com/yourname/ngoma-backend.git
git push -u origin main
```

### 3. Deploy on Railway

1. Sign up at [railway.app](https://railway.app) (free; uses GitHub login)
2. Click **New Project** → **Deploy from GitHub repo** → select `ngoma-backend`
3. Railway auto-detects Django and starts deploying
4. Click **+ New** → **Database** → **PostgreSQL**. Railway automatically wires `DATABASE_URL` to your app.
5. Click your app service → **Variables** tab → add these:

   | Variable | Value |
   |---|---|
   | `SECRET_KEY` | Generate one at [djecrety.ir](https://djecrety.ir) |
   | `DEBUG` | `False` |
   | `ALLOWED_HOSTS` | `your-app-name.up.railway.app` (Railway shows you this) |
   | `CORS_ALLOWED_ORIGINS` | `https://ngomacharts.co.ke` (your frontend URL) |
   | `CSRF_TRUSTED_ORIGINS` | `https://your-app-name.up.railway.app` |
   | `OPENAI_API_KEY` | Your server-side OpenAI project key |
   | `OPENAI_MODEL` | `gpt-5.5` |
   | `OPENAI_FALLBACK_MODEL` | `gpt-4o-mini` |
   | `OPENAI_REASONING_EFFORT` | `medium` |

6. Wait ~2 minutes for first deploy. The `release` command in Procfile auto-runs migrations.

### 4. Seed the data and create admin user

In Railway, click your app → three-dot menu → **Open Shell**:

```bash
python manage.py seed_data --clear
python manage.py createsuperuser
```

### 5. Test

Visit `https://your-app-name.up.railway.app/admin/` and log in.
Visit `https://your-app-name.up.railway.app/api/v1/charts/latest/?chart_type=singles` to see real chart data via API.

### 6. Custom domain (optional)

In Railway → Settings → Networking → **Custom Domain** → enter `api.ngomacharts.co.ke`. Railway gives you a CNAME to add at your domain registrar.

---

## Option B: Render

Almost identical workflow. Render has a free tier but spins down after 15 min of inactivity (slow first request). $7/month gets always-on. Use the same `Procfile` and env vars.

1. Sign up at [render.com](https://render.com)
2. **New** → **Web Service** → connect GitHub
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn ngoma_backend.wsgi`
5. Add a **PostgreSQL** database from the dashboard, copy its connection string into `DATABASE_URL`
6. Add the same env vars as Railway above
7. After deploy, use the **Shell** tab to run `python manage.py seed_data --clear` and `createsuperuser`

---

## Option C: DigitalOcean (full control, ~$6/month)

For when you want more control. You'll provision a droplet, install nginx, gunicorn, postgresql yourself. Recommended only if you're comfortable with Linux server admin.

---

## Environment variables reference

| Variable | Required? | Example |
|---|---|---|
| `SECRET_KEY` | Yes | A 50+ character random string |
| `DEBUG` | Yes | `False` in production |
| `ALLOWED_HOSTS` | Yes | `api.ngomacharts.co.ke,your-app.up.railway.app` |
| `DATABASE_URL` | Yes | Auto-set by Railway/Render |
| `CORS_ALLOWED_ORIGINS` | Yes | `https://ngomacharts.co.ke` |
| `CSRF_TRUSTED_ORIGINS` | Yes | `https://api.ngomacharts.co.ke` |
| `OPENAI_API_KEY` | For generative analyst | Server-side OpenAI project key |
| `OPENAI_MODEL` | No | `gpt-5.5` |
| `OPENAI_FALLBACK_MODEL` | No | `gpt-4o-mini` |
| `OPENAI_REASONING_EFFORT` | No | `medium` |

---

## Adding new monthly data after deploy

Once live, this is your weekly workflow:

1. Log into `/admin/`
2. Go to **Weekly uploads** → **Add weekly upload**
3. Pick chart type (singles/albums), year, month, week
4. Upload the xlsx file
5. Click save — pipeline auto-processes the file
6. Click **Monthly charts** → find the relevant month → click **Rebuild** to refresh aggregates

That's it. No code changes needed for ongoing operations.

---

## Troubleshooting

**"DisallowedHost" error** → add your domain to `ALLOWED_HOSTS` env var.

**Static files not loading on admin** → run `python manage.py collectstatic --noinput` (Procfile does this on deploy automatically).

**CORS errors from frontend** → add the frontend URL to `CORS_ALLOWED_ORIGINS`.

**Database connection refused** → confirm `DATABASE_URL` is set. On Railway it's automatic when you add the PostgreSQL plugin.
