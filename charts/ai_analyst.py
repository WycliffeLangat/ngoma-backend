import json
import os

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from openai import OpenAI


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
        client = OpenAI(api_key=api_key)

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are the Ngoma Charts AI Analyst. "
                        "Answer clearly, briefly, and helpfully. "
                        "Focus on music chart analysis, artists, releases, "
                        "platform performance, trends, and insights."
                    ),
                },
                {
                    "role": "user",
                    "content": question,
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
