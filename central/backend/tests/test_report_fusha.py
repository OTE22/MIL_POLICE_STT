"""Phase 11: الصياغة بالفصحى — suggestion, then a human decision. Never automatic.

The whole point of these tests is the ORDER: asking produces a suggestion that sits beside
the report text; only اعتماد / تعديل writes it into what will be printed; رفض leaves the
wording alone but keeps the offer on the record. No route exists from model output to
official text without a person.
"""

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db.session import SessionLocal
from app.models import FushaStatus, ReportQABlock, SessionSpeaker, SpeakerRole
from app.services.llm import source_hash
from app.services.llm.nvidia import NvidiaNimProvider

from conftest import ADMIN, auth, create_session, request_token, sample_result
from test_report_draft import _evidence_fingerprint


def _login(client):
    return client.post("/api/auth/login", json=ADMIN).json()["access_token"]


def _submit(client, token, session_id, turns):
    tok = request_token(client, token, session_id)
    body = sample_result()
    body["segments"] = [
        {
            "speaker_label": label,
            "start_seconds": 1.0 + 3 * i,
            "end_seconds": 2.0 + 3 * i,
            "text": text,
            "is_overlap": False,
        }
        for i, (label, text) in enumerate(turns)
    ]
    body["speaker_count"] = len({label for label, _ in turns})
    res = client.post(
        f"/api/local-processing/{tok['job_id']}/result",
        json=body,
        headers=auth(tok["processing_token"]),
    )
    assert res.status_code == 200, res.text


def _interview(client, token):
    s = create_session(client, token)
    _submit(
        client,
        token,
        s["id"],
        [("SPEAKER_00", "وين كنت مبارح؟"), ("SPEAKER_01", "ما بعرف مين أخد السيارة، بس شفت أحمد حدها")],
    )
    with SessionLocal() as db:
        sid = uuid.UUID(s["id"])
        row = db.scalar(
            select(SessionSpeaker).where(
                SessionSpeaker.session_id == sid, SessionSpeaker.speaker_label == "SPEAKER_00"
            )
        )
        row.speaker_role = SpeakerRole.INVESTIGATOR
        db.commit()
    return s


def _draft(client, token, session_id):
    res = client.post(f"/api/investigations/{session_id}/report", headers=auth(token))
    assert res.status_code in (200, 201), res.text
    return res.json()


@pytest.fixture
def fake_model(monkeypatch):
    """Wire the service to a stub model: every request answers with formal Arabic."""
    replies = {
        "وين كنت مبارح؟": "أين كنت مساء أمس؟",
        "ما بعرف مين أخد السيارة، بس شفت أحمد حدها": "لا أعرف من أخذ السيارة، لكنني شاهدت أحمد بالقرب منها.",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        sent = json.loads(request.content)["messages"][1]["content"]
        return httpx.Response(
            200, json={"choices": [{"message": {"content": replies.get(sent, "نص مصاغ")}}]}
        )

    def factory(*args, **kwargs):
        from app.services.llm.service import ArabicFormalizationService as Real

        provider = NvidiaNimProvider(
            api_key="nvapi-test", client=httpx.Client(transport=httpx.MockTransport(handler))
        )
        return Real(provider=provider)

    monkeypatch.setattr("app.api.reports.ArabicFormalizationService", factory)
    return replies


# --------------------------------------------------------------- availability


def test_the_composer_is_told_when_fusha_is_unavailable(client, investigator, monkeypatch, tmp_path):
    """No key on this machine: the draft still loads and says why AI is off."""
    monkeypatch.setattr(get_settings(), "nvidia_api_key_file", tmp_path / "absent")
    s = _interview(client, investigator["token"])
    body = _draft(client, investigator["token"], s["id"])
    assert body["llm"]["available"] is False
    assert body["llm"]["fallback_reason"]
    assert body["qa_blocks"], "the محضر workflow is fully usable without any model"


def test_requesting_a_suggestion_without_a_model_is_a_clean_503(client, investigator, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "nvidia_api_key_file", tmp_path / "absent")
    t = investigator["token"]
    s = _interview(client, t)
    draft = _draft(client, t, s["id"])
    res = client.post(
        f"/api/investigations/{s['id']}/report/blocks/{draft['qa_blocks'][0]['id']}/fusha",
        json={},
        headers=auth(t),
    )
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "fusha_unavailable"


def test_capabilities_endpoint_reports_the_runtime(client, investigator):
    res = client.get("/api/llm/capabilities", headers=auth(investigator["token"]))
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) >= {"available", "provider", "runtime", "execution", "model", "fallback_reason"}
    # Diagnostics only: a reason may NAME a missing key ("nvidia_api_key_missing") but no
    # key material, path or prompt may ever appear here.
    blob = str(body).lower()
    assert "nvapi" not in blob
    assert "/run/secrets" not in blob and "bearer" not in blob


# --------------------------------------------------------------- suggest


def test_a_suggestion_never_changes_the_printed_text(client, investigator, fake_model):
    t = investigator["token"]
    s = _interview(client, t)
    draft = _draft(client, t, s["id"])
    block = draft["qa_blocks"][0]
    printed_before = (block["report_question_text"], block["report_answer_text"])

    res = client.post(
        f"/api/investigations/{s['id']}/report/blocks/{block['id']}/fusha", json={}, headers=auth(t)
    )
    assert res.status_code == 200, res.text
    after = res.json()["qa_blocks"][0]

    assert after["fusha_status"] == "AI_SUGGESTED"
    assert after["llm_suggested_answer"] == fake_model["ما بعرف مين أخد السيارة، بس شفت أحمد حدها"]
    # The suggestion sits BESIDE the report text, which is untouched.
    assert (after["report_question_text"], after["report_answer_text"]) == printed_before


def test_a_suggestion_does_not_touch_the_evidence(client, investigator, fake_model):
    t = investigator["token"]
    s = _interview(client, t)
    draft = _draft(client, t, s["id"])
    before = _evidence_fingerprint(s["id"])
    client.post(
        f"/api/investigations/{s['id']}/report/blocks/{draft['qa_blocks'][0]['id']}/fusha",
        json={},
        headers=auth(t),
    )
    assert _evidence_fingerprint(s["id"]) == before


def test_provenance_is_stored_without_prompt_or_secrets(client, investigator, fake_model):
    t = investigator["token"]
    s = _interview(client, t)
    draft = _draft(client, t, s["id"])
    block_id = draft["qa_blocks"][0]["id"]
    client.post(
        f"/api/investigations/{s['id']}/report/blocks/{block_id}/fusha", json={}, headers=auth(t)
    )
    with SessionLocal() as db:
        prov = db.get(ReportQABlock, uuid.UUID(block_id)).llm_provenance
    assert prov["provider"] == "nvidia_nim"
    assert prov["model"] == get_settings().development_llm_model
    assert prov["temperature"] == 0.1
    assert prov["generated_at"]
    # The hash binds the offer to the text it was made for.
    assert "answer_source_hash" in prov and len(prov["answer_source_hash"]) == 64
    blob = str(prov).lower()
    assert "nvapi" not in blob and "prompt" not in blob and "think" not in blob


# --------------------------------------------------------------- decide


def test_approving_adopts_the_suggestion_verbatim(client, investigator, fake_model):
    t = investigator["token"]
    s = _interview(client, t)
    draft = _draft(client, t, s["id"])
    block_id = draft["qa_blocks"][0]["id"]
    suggested = client.post(
        f"/api/investigations/{s['id']}/report/blocks/{block_id}/fusha", json={}, headers=auth(t)
    ).json()["qa_blocks"][0]["llm_suggested_answer"]

    res = client.post(
        f"/api/investigations/{s['id']}/report/blocks/{block_id}/fusha/decision",
        json={"accept": True},
        headers=auth(t),
    )
    assert res.status_code == 200, res.text
    block = res.json()["qa_blocks"][0]
    assert block["report_answer_text"] == suggested
    assert block["fusha_status"] == "APPROVED"
    # The source copy of the transcript text is still the original colloquial line.
    assert block["answer_source_text"] == "ما بعرف مين أخد السيارة، بس شفت أحمد حدها"


def test_accepting_with_an_edit_records_it_as_the_humans_wording(client, investigator, fake_model):
    t = investigator["token"]
    s = _interview(client, t)
    draft = _draft(client, t, s["id"])
    block_id = draft["qa_blocks"][0]["id"]
    client.post(f"/api/investigations/{s['id']}/report/blocks/{block_id}/fusha", json={}, headers=auth(t))

    res = client.post(
        f"/api/investigations/{s['id']}/report/blocks/{block_id}/fusha/decision",
        json={"accept": True, "report_answer_text": "لا أعرف من أخذ السيارة، وقد شاهدت أحمد قربها."},
        headers=auth(t),
    )
    block = res.json()["qa_blocks"][0]
    assert block["report_answer_text"] == "لا أعرف من أخذ السيارة، وقد شاهدت أحمد قربها."
    assert block["fusha_status"] == "HUMAN_EDITED"
    with SessionLocal() as db:
        prov = db.get(ReportQABlock, uuid.UUID(block_id)).llm_provenance
    assert prov["approved_with_edit"] is True
    assert prov["approved_by"] and prov["approved_at"]


def test_rejecting_keeps_the_wording_and_the_record(client, investigator, fake_model):
    t = investigator["token"]
    s = _interview(client, t)
    draft = _draft(client, t, s["id"])
    block = draft["qa_blocks"][0]
    before = block["report_answer_text"]
    client.post(f"/api/investigations/{s['id']}/report/blocks/{block['id']}/fusha", json={}, headers=auth(t))

    res = client.post(
        f"/api/investigations/{s['id']}/report/blocks/{block['id']}/fusha/decision",
        json={"accept": False},
        headers=auth(t),
    )
    after = res.json()["qa_blocks"][0]
    assert after["report_answer_text"] == before, "rejection changes nothing that is printed"
    assert after["fusha_status"] == "REJECTED"
    assert after["llm_suggested_answer"], "what was offered stays on the record"


def test_a_decision_without_a_suggestion_is_refused(client, investigator):
    t = investigator["token"]
    s = _interview(client, t)
    draft = _draft(client, t, s["id"])
    res = client.post(
        f"/api/investigations/{s['id']}/report/blocks/{draft['qa_blocks'][0]['id']}/fusha/decision",
        json={"accept": True},
        headers=auth(t),
    )
    assert res.status_code == 409
    assert res.json()["detail"] == "fusha_no_suggestion"


def test_there_is_no_path_from_model_output_to_printed_text_without_a_decision(
    client, investigator, fake_model
):
    """The invariant, stated as a test: suggest twice, never decide, nothing is adopted."""
    t = investigator["token"]
    s = _interview(client, t)
    draft = _draft(client, t, s["id"])
    block = draft["qa_blocks"][0]
    original = block["report_answer_text"]

    for _ in range(2):
        body = client.post(
            f"/api/investigations/{s['id']}/report/blocks/{block['id']}/fusha", json={}, headers=auth(t)
        ).json()
    latest = body["qa_blocks"][0]
    assert latest["llm_suggested_answer"] != original
    assert latest["report_answer_text"] == original


# --------------------------------------------------------------- audit


def test_the_fusha_cycle_is_audited(client, investigator, fake_model):
    t = investigator["token"]
    s = _interview(client, t)
    draft = _draft(client, t, s["id"])
    block_id = draft["qa_blocks"][0]["id"]
    client.post(f"/api/investigations/{s['id']}/report/blocks/{block_id}/fusha", json={}, headers=auth(t))
    client.post(
        f"/api/investigations/{s['id']}/report/blocks/{block_id}/fusha/decision",
        json={"accept": True},
        headers=auth(t),
    )
    rows = client.get("/api/audit-logs?limit=100", headers=auth(_login(client))).json()["items"]
    actions = {r["action"] for r in rows}
    assert "REPORT_FUSHA_REQUESTED" in actions
    assert "REPORT_FUSHA_APPROVED" in actions
    # The audit entry names the model that produced the suggestion, never a key.
    requested = [r for r in rows if r["action"] == "REPORT_FUSHA_REQUESTED"][0]
    assert requested["safe_metadata"]["model"] == get_settings().development_llm_model
    assert "nvapi" not in str(requested).lower()
