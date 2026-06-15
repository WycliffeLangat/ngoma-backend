import json
import os
import secrets

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from openai import OpenAI

from .analyst_tools import ANALYST_TOOLS, TOOL_HANDLERS


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "analysis_summary": {
            "type": "string",
            "description": "A concise evidence summary, not hidden chain-of-thought.",
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "sources": {"type": "array", "items": {"type": "string"}},
        "follow_up_questions": {"type": "array", "items": {"type": "string"}},
        "chart": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["none", "line", "bar"]},
                "title": {"type": "string"},
                "subtitle": {"type": "string"},
                "x_label": {"type": "string"},
                "y_label": {"type": "string"},
                "is_prediction": {"type": "boolean"},
                "series": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "color": {"type": "string"},
                            "points": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string"},
                                        "value": {"type": "number"},
                                    },
                                    "required": ["label", "value"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["name", "color", "points"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["type", "title", "subtitle", "x_label", "y_label", "is_prediction", "series"],
            "additionalProperties": False,
        },
    },
    "required": ["answer", "analysis_summary", "confidence", "sources", "follow_up_questions", "chart"],
    "additionalProperties": False,
}


STYLE_HINTS = [
    "Write like a sharp music-chart analyst: direct, precise, and conversational.",
    "Lead with the conclusion, then explain the strongest evidence in natural prose.",
    "Use a polished editorial voice with compact paragraphs and concrete numbers.",
    "Be conversational and insightful. Vary sentence structure while keeping facts exact.",
    "Explain the chart story, not just the numbers. Keep the language clear and restrained.",
]


INSTRUCTIONS = """
You are Ngoma AI Analyst, a generative music-chart analyst embedded in the Ngoma Charts app.

PRODUCT CONTRACT
- Answer from Ngoma Charts application data only. Never browse the web and never use model memory as evidence.
- Before making a factual chart claim, call one or more provided tools. For broad questions, begin with get_app_overview and then call more specific tools when useful.
- Review enough of the available app data to answer the real intent, including relevant months, Combined charts, individual platforms, artist credits, certifications, country data, and news when applicable.
- Primary, featured, and joint artist credits count in artist analysis.
- Combined chart points are Display Points. Platform chart points use their original platform scale. Do not mix the scales.
- If the requested fact is not in the app data, say that clearly. Do not guess names, ranks, countries, dates, or points.
- You may analyze patterns and generate explanations. Predictions are allowed only after calling predict_next_month. Label every prediction as an estimate, explain the method briefly, and never present it as a future fact.
- Do not reveal hidden chain-of-thought. analysis_summary should give a short, user-facing summary of evidence and method.
- Use conversation history to resolve follow-ups such as "what about April?" or "compare that with Spotify".
- Avoid repeating the same stock phrasing. Keep facts stable while varying the presentation naturally.

GRAPH CONTRACT
- Include a chart when a time series, comparison, platform breakdown, rank journey, or prediction would materially help.
- Use line charts for time/rank journeys and bar charts for comparisons or platform totals.
- For rank charts, preserve actual rank values and state in the subtitle that lower is better.
- Set chart.type to "none" and series to [] when a graph would add no value.
- Never fabricate graph points. Every point must come from tool output.

ANSWER STYLE
- Lead with the useful answer.
- Cite exact chart names/months in the sources array.
- Offer 2 to 4 useful follow-up questions grounded in available data.
""".strip()


def _clean_messages(messages, question):
    cleaned = []
    for message in (messages or [])[-16:]:
        role = message.get("role")
        content = str(message.get("content") or message.get("text") or "").strip()
        if role in {"user", "assistant"} and content:
            cleaned.append({"role": role, "content": content[:8000]})
    if not cleaned or cleaned[-1]["role"] != "user" or cleaned[-1]["content"] != question:
        cleaned.append({"role": "user", "content": question})
    return cleaned


def _model_kwargs(model):
    kwargs = {}
    if model.startswith("gpt-5") or model.startswith("o"):
        kwargs["reasoning"] = {"effort": os.getenv("OPENAI_REASONING_EFFORT", "medium")}
    return kwargs


def _run_model(client, model, input_items, style_hint):
    current_input = list(input_items)
    for _ in range(6):
        response = client.responses.create(
            model=model,
            instructions=f"{INSTRUCTIONS}\n\nPRESENTATION HINT FOR THIS TURN: {style_hint}",
            input=current_input,
            tools=ANALYST_TOOLS,
            parallel_tool_calls=True,
            max_output_tokens=2400,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "ngoma_analyst_response",
                    "strict": True,
                    "schema": OUTPUT_SCHEMA,
                }
            },
            **_model_kwargs(model),
        )
        function_calls = [item for item in response.output if item.type == "function_call"]
        if not function_calls:
            payload = json.loads(response.output_text)
            payload["response_id"] = response.id
            payload["model"] = model
            payload["mode"] = "generative"
            return payload

        current_input.extend(response.output)
        for call in function_calls:
            handler = TOOL_HANDLERS.get(call.name)
            try:
                arguments = json.loads(call.arguments or "{}")
                result = handler(**arguments) if handler else {"error": f"Unknown tool: {call.name}"}
            except Exception as error:
                result = {"error": f"Tool {call.name} failed", "detail": str(error)}
            current_input.append({
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": json.dumps(result, ensure_ascii=False, default=str),
            })
    raise RuntimeError("The analyst exceeded the tool-call limit.")


@csrf_exempt
def ai_analyst(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST request required."}, status=405)

    try:
        body = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    question = str(body.get("question") or "").strip()
    if not question:
        return JsonResponse({"error": "Question is required."}, status=400)
    if len(question) > 4000:
        return JsonResponse({"error": "Question is too long."}, status=400)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return JsonResponse({
            "error": "Generative analyst is not configured.",
            "fallback": True,
        }, status=503)

    model = os.getenv("OPENAI_MODEL", "gpt-5.5")
    fallback_model = os.getenv("OPENAI_FALLBACK_MODEL", "gpt-4o-mini")
    style_hint = secrets.choice(STYLE_HINTS)
    if body.get("regenerate"):
        style_hint += " This is a regeneration: use a noticeably different structure and opening while preserving the evidence."

    input_items = _clean_messages(body.get("messages"), question)
    client = OpenAI(api_key=api_key, timeout=60.0, max_retries=1)

    try:
        payload = _run_model(client, model, input_items, style_hint)
        return JsonResponse(payload)
    except Exception as primary_error:
        if fallback_model and fallback_model != model:
            try:
                payload = _run_model(client, fallback_model, input_items, style_hint)
                payload["model_fallback_from"] = model
                return JsonResponse(payload)
            except Exception as fallback_error:
                print(f"[ai_analyst] primary={primary_error}; fallback={fallback_error}")
        else:
            print(f"[ai_analyst] error={primary_error}")
        return JsonResponse({
            "error": "The generative analyst is temporarily unavailable.",
            "fallback": True,
        }, status=502)
