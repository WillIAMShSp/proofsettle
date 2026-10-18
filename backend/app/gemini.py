"""GeminiProvider: AI inspection of the evidence photos with Google's Gemini API.

Gemini looks at the dispatch photos (the goods as shipped) and the receipt photos (as
delivered) and reports damage as findings, in InspectionReport's JSON shape. That is all it
does. Its output goes through inspection.parse_report like any provider's, and the proposed
adjustment is computed by app.settlement from the agreed terms: Gemini never sees or sets
an amount, a status or a decision.

Called over REST (generateContent, v1beta) with urllib, like app.auth calls Supabase, so
there is no SDK dependency. Turned on by PROOFSETTLE_GEMINI_API_KEY (or GEMINI_API_KEY) in
backend/.env; without a key the backend keeps using MockProvider.
"""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.inspection import InspectionFailed, InspectionRequest, Photo

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
# Gemini limits a whole request (prompt plus inline image bytes) to 20 MB. Stay under it
# with room for the prompt; base64 makes the bytes a third bigger on the wire.
MAX_REQUEST_BYTES = 19 * 1024 * 1024

# The report shape (inspection.ProviderFinding, minus nothing). Ranges and the allowed
# defect types are in the prompt and checked again by parse_report and the settlement
# engine, so the schema stays to types and required fields.
_FINDING_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "unitRef": {"type": "STRING"},
        "defectType": {"type": "STRING"},
        "confidence": {"type": "NUMBER"},
        "evidenceIds": {"type": "ARRAY", "items": {"type": "STRING"}},
        "description": {"type": "STRING"},
        "presentInDispatch": {"type": "BOOLEAN"},
    },
    "required": ["unitRef", "defectType", "confidence", "evidenceIds", "description", "presentInDispatch"],
    "propertyOrdering": ["unitRef", "defectType", "confidence", "evidenceIds", "description", "presentInDispatch"],
}
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"findings": {"type": "ARRAY", "items": _FINDING_SCHEMA}},
    "required": ["findings"],
}


def build_prompt(request: InspectionRequest) -> str:
    terms = request.terms
    acceptance = terms.acceptance
    types = ", ".join(acceptance.defect_types)
    return f"""You are a quality inspector comparing photos of one shipment before and after delivery.

Shipment: {terms.quantity} × {terms.item_description}.
The agreement covers only these defect types: {types}.

You get two sets of photos, each image preceded by its evidence id:
- DISPATCH photos: the goods as the supplier shipped them (the baseline).
- RECEIPT photos: the same goods as the buyer received them.

Report each unit that shows damage in the RECEIPT photos as one finding:
- unitRef: which unit it is, at most 100 characters. Use a label or number visible on the
  unit if there is one (for example "Component #017"); otherwise describe its position
  (for example "Bracket, top-left of ev_05"). One physical unit must have exactly one
  finding and the same unitRef, even when several photos show it.
- defectType: exactly one of: {types}. If the damage fits none of them, use the closest
  lowercase snake_case word (for example "dent"); it will not be counted.
- confidence: 0 to 1, how sure you are that this damage is real and not glare, a shadow,
  dirt, a reflection or a photo artifact.
- evidenceIds: the ids of the photos that show it, copied exactly from the labels below.
  Include at least one RECEIPT photo id.
- description: one short sentence about what you see, at most 500 characters.
- presentInDispatch: true if the same damage is already visible in a DISPATCH photo
  (so it happened before shipping), otherwise false.

Rules:
- Report only physical damage you can see. Do not guess about parts that aren't visible.
- If there is no damage, return {{"findings": []}}.
- Do not estimate prices, credits, refunds or who is at fault; that is decided elsewhere
  from the agreement.
- Use only evidence ids from the labels below.
"""


def _image_parts(label: str, photos: tuple[Photo, ...]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [{"text": f"{label} photos ({len(photos)}):"}]
    for p in photos:
        parts.append({"text": f"Evidence id: {p.id}"})
        parts.append({"inline_data": {"mime_type": p.content_type, "data": base64.b64encode(p.data).decode()}})
    return parts


def build_request_body(request: InspectionRequest) -> dict[str, Any]:
    parts = [{"text": build_prompt(request)}]
    parts += _image_parts("DISPATCH", request.dispatch)
    parts += _image_parts("RECEIPT", request.receipt)
    return {
        "contents": [{"role": "user", "parts": parts}],
        "generation_config": {
            "response_mime_type": "application/json",
            "response_schema": RESPONSE_SCHEMA,
            "temperature": 0,
        },
    }


def response_text(payload: object) -> str:
    """The model's JSON text from a generateContent response, or InspectionFailed."""
    if not isinstance(payload, dict):
        raise InspectionFailed("Gemini returned an unreadable response")
    blocked = (payload.get("promptFeedback") or {}).get("blockReason")
    if blocked:
        raise InspectionFailed(f"Gemini declined to inspect these photos ({blocked})")
    candidates = payload.get("candidates") or []
    if not candidates or not isinstance(candidates[0], dict):
        raise InspectionFailed("Gemini returned no result")
    candidate = candidates[0]
    reason = candidate.get("finishReason")
    if reason not in (None, "STOP"):
        raise InspectionFailed(f"Gemini stopped before finishing the inspection ({reason})")
    parts = (candidate.get("content") or {}).get("parts") or []
    # Thought summaries, if a model sends them, are marked `thought` and are not the answer.
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought"))
    if not text.strip():
        raise InspectionFailed("Gemini returned an empty inspection")
    return text


class GeminiProvider:
    """InspectionProvider backed by Gemini. See the module docstring."""

    def __init__(self, api_key: str, model: str, *, timeout: float = 300.0) -> None:
        if not api_key:
            raise ValueError("GeminiProvider needs an API key")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.name = f"gemini:{model}"  # recorded on the inspection's audit event

    def inspect(self, request: InspectionRequest) -> str:
        if not request.receipt:
            raise InspectionFailed("No receipt photos to inspect")
        body = json.dumps(build_request_body(request)).encode()
        if len(body) > MAX_REQUEST_BYTES:
            mb = len(body) / 1024 / 1024
            raise InspectionFailed(
                f"The photos are too large to inspect together ({mb:.0f} MB; Gemini takes under 20 MB). "
                "Upload smaller or fewer photos."
            )
        url = f"{API_ROOT}/models/{urllib.parse.quote(self.model, safe='-._')}:generateContent"
        # The key goes in a header, not the URL, so it never lands in a log line.
        http = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(http, timeout=self.timeout) as res:
                payload = json.loads(res.read().decode())
        except urllib.error.HTTPError as e:
            raise InspectionFailed(_http_error(e)) from e
        except TimeoutError as e:
            raise InspectionFailed(
                f"Gemini didn't finish within {self.timeout:.0f} s; try again, or with fewer photos"
            ) from e
        except (urllib.error.URLError, OSError) as e:
            raise InspectionFailed("Could not reach Gemini; try the inspection again") from e
        except json.JSONDecodeError as e:
            raise InspectionFailed("Gemini returned an unreadable response") from e
        return response_text(payload)


def _http_error(e: urllib.error.HTTPError) -> str:
    try:
        message = str(json.loads(e.read().decode(errors="replace"))["error"]["message"])
    except (OSError, ValueError, KeyError, TypeError):  # no body, not JSON, or another shape
        message = str(e.reason)
    if e.code in (401, 403):
        return f"Gemini rejected the API key (check PROOFSETTLE_GEMINI_API_KEY): {message}"
    if e.code == 404:
        return f"Gemini has no model by that name (check PROOFSETTLE_GEMINI_MODEL): {message}"
    if e.code == 429:
        return "Gemini is rate-limiting this key; wait a minute and run the inspection again"
    if e.code >= 500:
        return "Gemini is unavailable right now; run the inspection again"
    return f"Gemini refused the inspection request ({e.code}): {message}"
