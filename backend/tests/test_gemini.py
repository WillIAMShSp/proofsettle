"""GeminiProvider without the network: the request it sends, what it accepts back, and the
inspection flow through the API (photos -> Gemini findings -> engine's proposed adjustment)."""

import base64
import io
import json
import urllib.error

import pytest

from app import routes
from app.config import settings
from app.gemini import GeminiProvider, response_text
from app.inspection import InspectionFailed, InspectionRequest, MockProvider, Photo
from app.main import app
from app.routes import inspection_provider
from app.seed import PS_1042_TERMS
from tests.test_writes import BUYER, failed_inspection, inspected, ok, to_status

KEY = "test-gemini-key"


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def gemini_answer(report: dict, **candidate) -> dict:
    """A generateContent response whose text is `report` as JSON."""
    return {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": json.dumps(report)}]}, "finishReason": "STOP"} | candidate
        ]
    }


def fake_gemini(monkeypatch, answer):
    """Route urllib to a fake Gemini; `answer` is a payload, an exception, or request -> payload."""
    seen = []

    def urlopen(request, timeout):
        seen.append(request)
        result = answer(request) if callable(answer) else answer
        if isinstance(result, Exception):
            raise result
        return _Response(result)

    monkeypatch.setattr("app.gemini.urllib.request.urlopen", urlopen)
    return seen


def request_for(dispatch=(), receipt=()):
    photo = lambda id, kind: Photo(id, kind, "image/jpeg", "0" * 64, f"bytes of {id}".encode())
    return InspectionRequest(
        shipment_id="PS-1",
        terms=PS_1042_TERMS,
        dispatch=tuple(photo(i, "dispatch") for i in dispatch),
        receipt=tuple(photo(i, "receipt") for i in receipt),
    )


def http_error(code: int, message: str = "nope") -> urllib.error.HTTPError:
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    return urllib.error.HTTPError("https://gemini", code, "error", None, io.BytesIO(body))  # type: ignore[arg-type]


# --- The request ---------------------------------------------------------------------------


def test_the_request_carries_the_prompt_the_photos_and_the_schema(monkeypatch):
    seen = fake_gemini(monkeypatch, gemini_answer({"findings": []}))
    GeminiProvider(KEY, "gemini-3.8-flash").inspect(request_for(["ev_01"], ["ev_05", "ev_06"]))

    (req,) = seen
    assert req.full_url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
    assert KEY not in req.full_url  # in a header, never the URL
    assert req.get_header("X-goog-api-key") == KEY
    body = json.loads(req.data)
    parts = body["contents"][0]["parts"]
    prompt = parts[0]["text"]
    assert "100 × Machined metal component" in prompt
    assert "bend, crack, deep_scratch, discoloration" in prompt
    assert "price" in prompt  # told not to estimate money

    # Each photo is labelled with its evidence id right before its bytes, dispatch first.
    texts = [p.get("text") for p in parts[1:]]
    images = [p["inline_data"] for p in parts if "inline_data" in p]
    assert texts == [
        "DISPATCH photos (1):",
        "Evidence id: ev_01",
        None,
        "RECEIPT photos (2):",
        "Evidence id: ev_05",
        None,
        "Evidence id: ev_06",
        None,
    ]
    assert [base64.b64decode(i["data"]) for i in images] == [b"bytes of ev_01", b"bytes of ev_05", b"bytes of ev_06"]
    assert {i["mime_type"] for i in images} == {"image/jpeg"}

    config = body["generation_config"]
    assert config["response_mime_type"] == "application/json"
    assert config["temperature"] == 0
    finding = config["response_schema"]["properties"]["findings"]["items"]
    assert set(finding["required"]) == {
        "unitRef",
        "defectType",
        "confidence",
        "evidenceIds",
        "description",
        "presentInDispatch",
    }


def test_no_receipt_photos_means_no_call(monkeypatch):
    seen = fake_gemini(monkeypatch, gemini_answer({"findings": []}))
    with pytest.raises(InspectionFailed, match="No receipt photos"):
        GeminiProvider(KEY, "m").inspect(request_for(["ev_01"], []))
    assert seen == []


def test_photos_over_the_request_limit_are_refused_before_sending(monkeypatch):
    seen = fake_gemini(monkeypatch, gemini_answer({"findings": []}))
    monkeypatch.setattr("app.gemini.MAX_REQUEST_BYTES", 1000)
    with pytest.raises(InspectionFailed, match="too large"):
        GeminiProvider(KEY, "m").inspect(request_for([], ["ev_05"]))
    assert seen == []


# --- The response --------------------------------------------------------------------------


def test_the_answer_is_the_model_text_without_thoughts():
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "thinking…", "thought": True}, {"text": '{"findings": '}, {"text": "[]}"}]
                },
                "finishReason": "STOP",
            }
        ]
    }
    assert response_text(payload) == '{"findings": []}'


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"promptFeedback": {"blockReason": "SAFETY"}}, "declined"),
        ({"candidates": []}, "no result"),
        (gemini_answer({"findings": []}, finishReason="MAX_TOKENS"), "stopped"),
        ({"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]}, "empty"),
        ("not an object", "unreadable"),
    ],
)
def test_unusable_answers_fail_the_inspection(payload, match):
    with pytest.raises(InspectionFailed, match=match):
        response_text(payload)


@pytest.mark.parametrize(
    ("code", "match"),
    [(400, "refused"), (403, "API key"), (404, "model"), (429, "rate-limiting"), (503, "unavailable")],
)
def test_http_errors_become_readable_failures(monkeypatch, code, match):
    fake_gemini(monkeypatch, http_error(code))
    with pytest.raises(InspectionFailed, match=match) as raised:
        GeminiProvider(KEY, "m").inspect(request_for([], ["ev_05"]))
    assert KEY not in str(raised.value)


def test_an_unreachable_gemini_fails_cleanly(monkeypatch):
    fake_gemini(monkeypatch, urllib.error.URLError("no route"))
    with pytest.raises(InspectionFailed, match="reach Gemini"):
        GeminiProvider(KEY, "m").inspect(request_for([], ["ev_05"]))


# --- Which provider ------------------------------------------------------------------------


def test_the_provider_is_gemini_only_with_a_key(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    assert isinstance(routes.inspection_provider(), MockProvider)
    monkeypatch.setattr(settings, "gemini_api_key", KEY)
    monkeypatch.setattr(settings, "gemini_model", "gemini-3.5-flash-lite")
    provider = routes.inspection_provider()
    assert isinstance(provider, GeminiProvider)
    assert provider.name == "gemini:gemini-3.5-flash-lite"


# --- Through the API -----------------------------------------------------------------------


@pytest.fixture
def gemini(monkeypatch):
    """The app inspects with GeminiProvider; tests set what the fake Gemini answers."""
    provider = GeminiProvider(KEY, "gemini-3.8-flash")
    app.dependency_overrides[inspection_provider] = lambda: provider
    yield lambda answer: fake_gemini(monkeypatch, answer)
    app.dependency_overrides.pop(inspection_provider, None)


def receipt_ids(client, id):
    return [e["id"] for e in ok(client.get(f"/shipments/{id}", headers=BUYER))["evidence"] if e["kind"] == "receipt"]


def test_gemini_findings_become_the_engines_proposed_adjustment(client, gemini):
    id = to_status(client, "Inspection")
    r1, r2, *_ = receipt_ids(client, id)
    seen = gemini(
        lambda req: gemini_answer(
            {
                "findings": [
                    # Counted: covered type, new since dispatch, confident. Seen in two photos.
                    {
                        "unitRef": "Component #017",
                        "defectType": "bend",
                        "confidence": 0.95,
                        "evidenceIds": [r1, r2],
                        "description": "Bent flange",
                        "presentInDispatch": False,
                    },
                    # Needs review: below the 0.85 threshold.
                    {
                        "unitRef": "Component #042",
                        "defectType": "crack",
                        "confidence": 0.6,
                        "evidenceIds": [r2],
                        "description": "Possible hairline crack",
                        "presentInDispatch": False,
                    },
                    # Excluded: already there at dispatch.
                    {
                        "unitRef": "Component #050",
                        "defectType": "deep_scratch",
                        "confidence": 0.99,
                        "evidenceIds": [r1],
                        "description": "Scratch",
                        "presentInDispatch": True,
                    },
                ]
            }
        )
    )
    d = inspected(client, id)

    assert len(seen) == 1
    sent = [p["inline_data"] for p in json.loads(seen[0].data)["contents"][0]["parts"] if "inline_data" in p]
    assert len(sent) == 8  # 4 dispatch + 4 receipt photos, the real uploaded bytes

    assert d["status"] == "Proposed" and d["inspectionRun"] is None
    assert [f["unitRef"] for f in d["inspection"]["findings"]] == ["Component #017", "Component #042", "Component #050"]
    adj = d["adjustment"]
    # The engine, not Gemini, decides: 1 counted unit × $100 per unit (PS-1042's terms).
    assert adj["confirmedDefects"] == 1
    assert adj["credit"] == 100
    assert adj["settlementAmount"] == 9900
    assert [o["unitRef"] for o in adj["needsReview"]] == ["Component #042"]
    assert [o["reason"] for o in adj["excluded"]] == ["present_in_dispatch"]
    event = next(e for e in d["events"] if e["type"] == "inspection.completed")
    assert event["actor"] == "AI"
    assert ok(client.get(f"/shipments/{id}/audit", headers=BUYER))["verified"] is True


def test_gemini_citing_a_photo_it_was_not_given_stores_nothing(client, gemini):
    id = to_status(client, "Inspection")
    finding = {
        "unitRef": "Component #001",
        "defectType": "bend",
        "confidence": 0.9,
        "evidenceIds": ["ev_999"],
        "description": "Bent",
        "presentInDispatch": False,
    }
    gemini(gemini_answer({"findings": [finding]}))
    d = failed_inspection(client, id)
    assert "unknown evidence ev_999" in d["inspectionRun"]["error"]


def test_gemini_output_off_the_schema_stores_nothing(client, gemini):
    id = to_status(client, "Inspection")
    gemini(gemini_answer({"findings": [{"unitRef": "x", "amount": 500}]}))  # no amount field exists
    d = failed_inspection(client, id)
    assert "failed validation" in d["inspectionRun"]["error"]


def test_a_gemini_failure_can_be_retried(client, gemini):
    id = to_status(client, "Inspection")
    gemini(http_error(503))
    d = failed_inspection(client, id)
    assert "unavailable" in d["inspectionRun"]["error"]
    gemini(gemini_answer({"findings": []}))
    d = inspected(client, id)  # a failed run can simply be started again
    assert d["status"] == "Proposed" and d["adjustment"]["credit"] == 0 and d["inspectionRun"] is None


def test_a_slow_gemini_times_out_with_a_clear_message(monkeypatch):
    fake_gemini(monkeypatch, TimeoutError("timed out"))
    with pytest.raises(InspectionFailed, match="didn't finish within 300 s"):
        GeminiProvider(KEY, "m").inspect(request_for([], ["ev_05"]))


# --- The background job ------------------------------------------------------------------


def test_a_second_start_while_one_is_running_is_refused(client, db):
    from datetime import UTC, datetime

    from app.models import Shipment

    id = to_status(client, "Inspection")
    s = db.get(Shipment, id)
    s.inspection_state, s.inspection_started_at = "running", datetime.now(UTC)
    db.commit()
    res = client.post(f"/shipments/{id}/inspect", headers=BUYER)
    assert res.status_code == 409 and "already running" in res.json()["detail"]
    assert ok(client.get(f"/shipments/{id}", headers=BUYER))["inspectionRun"]["state"] == "running"


def test_a_run_that_died_can_be_started_again(client, db, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from app.models import Shipment

    id = to_status(client, "Inspection")
    s = db.get(Shipment, id)
    s.inspection_state = "running"
    s.inspection_started_at = datetime.now(UTC) - timedelta(seconds=settings.inspection_stale_s + 1)
    db.commit()
    run = ok(client.get(f"/shipments/{id}", headers=BUYER))["inspectionRun"]
    assert run["state"] == "failed" and "stopped without finishing" in run["error"]
    assert inspected(client, id)["status"] == "Proposed"  # the mock provider


def test_the_start_is_checked_before_anything_runs(client):
    assert client.post("/shipments/PS-1038/inspect", headers=BUYER).status_code == 409  # In Transit
    id = to_status(client, "Inspection")
    assert client.post(f"/shipments/{id}/inspect", headers={"X-Demo-Role": "Reviewer"}).status_code == 403
    assert ok(client.get(f"/shipments/{id}", headers=BUYER))["inspectionRun"] is None


def test_a_crashing_provider_is_recorded_not_raised(client):
    from app.main import app as fastapi_app

    class Crashes:
        name = "crashes"

        def inspect(self, request):
            raise RuntimeError("boom")

    id = to_status(client, "Inspection")
    fastapi_app.dependency_overrides[inspection_provider] = Crashes
    d = failed_inspection(client, id)
    assert "Inspection provider crashes failed" in d["inspectionRun"]["error"]
