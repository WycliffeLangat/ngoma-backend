import json
import os

from django.apps import apps
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from openai import OpenAI


def build_database_context():
    """
    Pulls current data from the Django database and prepares it for the AI.
    It reads all models inside the charts app, including artists, releases,
    charts, platforms, uploads, news, certifications, and related data.
    """

    context = {}

    charts_app = apps.get_app_config("charts")

    for model in charts_app.get_models():
        model_name = model.__name__

        try:
            queryset = model.objects.all().order_by("-id")[:100]
        except Exception:
            queryset = model.objects.all()[:100]

        rows = []

        for obj in queryset:
            item = {}

            for field in obj._meta.fields:
                field_name = field.name

                try:
                    value = getattr(obj, field_name)
                    item[field_name] = str(value)
                except Exception:
                    item[field_name] = None

            rows.append(item)

        context[model_name] = rows

    return context


@csrf_exempt
def ai_analyst(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST request required."}, status=405)

    try:
        body = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    question = body.get("question", "").strip()

    if not question:
        return JsonResponse({"error": "Question is required."}, status=400)

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return JsonResponse(
            {"error": "OPENAI_API_KEY not configured."},
            status=500,
        )

    try:
        database_context = build_database_context()

        database_context_text = json.dumps(
            database_context,
            indent=2,
            ensure_ascii=False,
            default=str,
        )

        client = OpenAI(api_key=api_key)

        response = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are the Ngoma Charts AI Analyst. "
                        "You must answer using the database context provided. "
                        "If the answer is not available in the database context, say so clearly. "
                        "Do not invent chart positions, artist names, rankings, months, or platform data. "
                        "Be clear, brief, analytical, and useful."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Here is the current Ngoma Charts database context:\n\n"
                        f"{database_context_text}\n\n"
                        "Now answer this question based only on the database context:\n\n"
                        f"{question}"
                    ),
                },
            ],
        )

        return JsonResponse({"answer": response.output_text})

    except Exception as e:
        print(f"[ai_analyst] OpenAI error: {e}")
        return JsonResponse(
            {"error": "The analyst is temporarily unavailable."},
            status=502,
        )
