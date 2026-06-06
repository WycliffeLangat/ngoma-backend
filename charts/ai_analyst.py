"""
ai_analyst.py — Ngoma Charts AI Analyst endpoint

Drop this into your Django `charts/` app and wire the URL (see bottom).
It keeps your Anthropic API key SECRET on the server. The browser never sees it.

SETUP
-----
1. Install the SDK:
       pip install anthropic

2. Set your API key as an environment variable (NEVER hardcode it):
       export ANTHROPIC_API_KEY="sk-ant-..."
   On your host (Railway / Render / Fly / a VPS) add it as a secret env var.

3. Add the URL route in charts/urls.py:
       from .ai_analyst import ai_analyst
       urlpatterns += [ path('ai/analyst/', ai_analyst) ]

4. In the frontend (ngoma_charts.jsx), set:
       const API_BASE = "https://your-backend.com/api/v1";
   The AI Analyst will then automatically route through this endpoint.

OPTIONAL — build the data context server-side
----------------------------------------------
Right now the frontend sends the chart context in the `system` field. Once your
charts live in the database, you can ignore the client-sent context and build it
from real data instead (see build_context() stub below) so the AI always has the
latest months without the frontend needing to know them.
"""
import os
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

try:
    import anthropic
except ImportError:
    anthropic = None


# --- Optional: build context from your DB instead of trusting the client ---
def build_context():
    """
    Build the chart-data context from the database so the AI always has the
    latest data. Returns a string. Wire this in once your charts are populated.
    """
    from .models import MonthlyChart, MonthlyChartEntry
    lines = []
    for chart in MonthlyChart.objects.filter(is_published=True).order_by('-year', '-month')[:6]:
        top = (MonthlyChartEntry.objects
               .filter(chart=chart, platform__isnull=True)
               .select_related('release', 'release__artist')
               .order_by('rank')[:10])
        items = ", ".join(
            f"#{e.rank} {e.release.title} ({e.release.artist.name}, {e.total_points}pts)"
            for e in top
        )
        lines.append(f"{chart.label} {chart.chart_type} Top 10: {items}")
    return " | ".join(lines)


@csrf_exempt
@require_POST
def ai_analyst(request):
    """
    POST { "question": "...", "system": "..." }  ->  { "answer": "..." }

    The API key lives only here, server-side, read from the environment.
    """
    if anthropic is None:
        return JsonResponse({"error": "anthropic SDK not installed. Run: pip install anthropic"}, status=500)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return JsonResponse({"error": "ANTHROPIC_API_KEY not configured on the server."}, status=500)

    try:
        body = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    question = (body.get("question") or "").strip()
    if not question:
        return JsonResponse({"error": "Missing 'question'."}, status=400)

    # Use the client-supplied system context, OR build it from the DB.
    # To always use fresh DB data, replace the next line with: system = "...intro... " + build_context()
    system = body.get("system") or "You are the Ngoma Charts AI analyst for Kenya's official music charts. Be concise and data-driven."

    # Basic safety: cap question length
    question = question[:2000]

    client = anthropic.Anthropic(api_key=api_key)
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1200,
            system=system,
            messages=[{"role": "user", "content": question}],
        )
        answer = "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")
        return JsonResponse({"answer": answer or "No response."})
    except Exception as e:
        # Don't leak internal details to the client
        print(f"[ai_analyst] error: {e}")
        return JsonResponse({"error": "The analyst is temporarily unavailable."}, status=502)
