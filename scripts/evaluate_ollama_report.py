"""One fictional Arabic report excerpt, using ONLY an already installed Ollama model.

Standard library only. No pulls, installation, cloud calls, application API or DB writes.
Run from the repository root: python scripts/evaluate_ollama_report.py
"""
from __future__ import annotations

import hashlib
import html
import json
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:11434"
MODEL = "qwen2.5:1.5b"
OUT = ROOT / "storage/model-evaluation/results/qwen25-report-20261023"


def api(path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(BASE + path, data=data, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=180) as response:
        return json.load(response)


def write_json(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract-only", action="store_true", help="Use the model only for fields; assemble Q&A and notes in code")
    args = parser.parse_args()
    if args.extract_only:
        OUT = OUT / "extract-only"
    before = api("/api/tags")
    installed = {model["name"]: model for model in before["models"]}
    if MODEL not in installed:
        raise SystemExit(f"Required model is not installed: {MODEL}. No download attempted.")
    OUT.mkdir(parents=True, exist_ok=True)
    source_format = ROOT / "central/backend/app/assets/m53/source_format.json"
    source = {
        "test_data": "Fictional evaluation only; not an actual investigation or issued report.",
        "template_excerpt": "اسمي {statement_name}، مولود عام {birth_year} في {birth_place}، ومقيم حالياً في {residence}، رقم الهاتف {phone}.",
        "old_filled_example_STYLE_ONLY": {
            "identity": "اسمي فؤاد منصور، مولود عام 1978 في طرابلس، ومقيم حالياً في جونية، رقم الهاتف 03123456.",
            "question": "أين كنت مساء الأحد؟",
            "answer": "كنت في منزلي حتى الساعة الثامنة.",
        },
        "current_segments": [
            {"id": "S1", "speaker": "SPEAKER_00", "role": "investigator", "start": 0.0, "end": 2.0,
             "text": "عرّف عن حالك، ووين كنت مبارح؟"},
            {"id": "S2", "speaker": "SPEAKER_01", "role": "statement_giver", "start": 2.4, "end": 5.9,
             "text": "اسمي رامي ناصر، مولود سنة 1994 بصيدا."},
            {"id": "S3", "speaker": "SPEAKER_01", "role": "statement_giver", "start": 6.5, "end": 8.8,
             "text": "ساكن ببيروت. مبارح وصلت عالمكتب الساعة 9."},
            {"id": "S4", "speaker": "SPEAKER_01", "role": "statement_giver", "start": 9.2, "end": 12.5,
             "text": "بس ما شفت سامر، وما سلّمته أي مبلغ."},
        ],
        "investigator_notes": [
            {"id": "N1", "text": "وقت الوصول غير متحقق منه؛ طلبت مراجعة سجل الدخول."},
        ],
    }
    fields = ["statement_name", "birth_year", "birth_place", "residence", "phone"]
    field_schema = {"type": "object", "properties": {
        "value": {"type": ["string", "null"]},
        "source_ids": {"type": "array", "items": {"type": "string"}},
    }, "required": ["value", "source_ids"], "additionalProperties": False}
    text_schema = {"type": "object", "properties": {
        "text": {"type": "string"},
        "speaker": {"type": "string"},
        "source_ids": {"type": "array", "items": {"type": "string"}},
    }, "required": ["text", "speaker", "source_ids"], "additionalProperties": False}
    schema = {"type": "object", "properties": {
        "fields": {"type": "object", "properties": {name: field_schema for name in fields},
                   "required": fields, "additionalProperties": False},
        "question": text_schema, "answer": text_schema,
        "investigator_note": {"type": "object", "properties": {
            "text": {"type": "string"}, "source_ids": {"type": "array", "items": {"type": "string"}},
        }, "required": ["text", "source_ids"], "additionalProperties": False},
    }, "required": ["fields", "question", "answer", "investigator_note"], "additionalProperties": False}
    system = """أنت مساعد لملء جزء صغير من مسودة محضر بالعربية. أعد JSON فقط وفق البنية المطلوبة.
استخرج حقائق الحالة الحالية فقط من current_segments. المثال القديم يوضح الأسلوب فقط ولا يثبت أي حقيقة للحالة الجديدة.
كل حقل يحتوي value وsource_ids. إن لم يذكر الحقل، ضع value=null وsource_ids=[]. لا تخمن رقم هاتف أو هوية.
اكتب السؤال والجواب بالفصحى مع speaker وsource_ids الصحيحة. اجمع أجزاء جواب الشخص بترتيبها دون حذف أي حقيقة.
حافظ على جميع الأسماء والأرقام والنفي: عدم رؤية شخص وعدم تسليم مال ليسا إقراراً بالفعل.
لا تستنتج تاريخاً من كلمة أمس ولا تحدد صباحاً أو مساءً إن لم يذكر ذلك.
أعد ملاحظة المحقق كما هي في investigator_note، ولا تحولها إلى كلام صاحب الإفادة أو إلى إجراء تم التحقق منه.
اربط النص والحقل بالمقاطع المستخدمة. لا تضف معلومات من المثال القديم أو معرفة خارجية."""
    payload = {"model": MODEL, "stream": False, "format": schema, "keep_alive": "2m",
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": json.dumps(source, ensure_ascii=False)}],
               "options": {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 1600}}
    if args.extract_only:
        payload["format"] = {"type": "object", "properties": {"fields": schema["properties"]["fields"]},
                             "required": ["fields"], "additionalProperties": False}
        payload["messages"] = [
            {"role": "system", "content": """Extract five fields from the CURRENT Arabic statement below. Return only the requested JSON.
statement_name = full name; birth_year = year of birth as digits; birth_place = place of birth; residence = current city of residence; phone = telephone number.
Each field contains value (string or null) and source_ids (IDs of the lines proving it).
Copy names and places exactly in Arabic. If a value is not stated, return null and an empty source_ids array.
Use the statement giver's lines only. Do not guess or add facts."""},
            {"role": "user", "content": "\n".join(f"{s['id']} ({s['role']}): {s['text']}" for s in source["current_segments"])},
        ]
        payload["options"]["num_predict"] = 650
    write_json("input.json", source)
    write_json("request.json", payload)
    print(f"Testing installed {MODEL}; fictional 12.5-second excerpt; no downloads.", flush=True)
    started = time.perf_counter()
    response = api("/api/chat", payload)
    elapsed = time.perf_counter() - started
    write_json("response.json", response)
    result = json.loads(response["message"]["content"])
    write_json("model_result.json", result)
    if args.extract_only:
        # Fixed layout and exact source text are application responsibilities in this variant.
        question_segments = [s for s in source["current_segments"] if s["role"] == "investigator"]
        answer_segments = [s for s in source["current_segments"] if s["role"] == "statement_giver"]
        for key, parts in [("question", question_segments), ("answer", answer_segments)]:
            result[key] = {"text": " ".join(s["text"] for s in parts), "speaker": parts[0]["speaker"],
                           "source_ids": [s["id"] for s in parts]}
        result["investigator_note"] = {"text": source["investigator_notes"][0]["text"], "source_ids": ["N1"]}
    write_json("result.json", result)
    expected = {"statement_name": ("رامي ناصر", ["S2"]), "birth_year": ("1994", ["S2"]),
                "birth_place": ("صيدا", ["S2"]), "residence": ("بيروت", ["S3"]), "phone": (None, [])}
    value_checks = {key: result.get("fields", {}).get(key, {}).get("value") == value for key, (value, _) in expected.items()}
    source_checks = {key: result.get("fields", {}).get(key, {}).get("source_ids") == ids for key, (_, ids) in expected.items()}
    checks = {
        f"field_{key}": result.get("fields", {}).get(key) == {"value": value, "source_ids": ids}
        for key, (value, ids) in expected.items()
    }
    question, answer, note = (result.get(name, {}) for name in ("question", "answer", "investigator_note"))
    checks.update({
        "question_speaker_and_sources": question.get("speaker") == "SPEAKER_00" and question.get("source_ids") == ["S1"],
        "answer_speaker_and_ordered_sources": answer.get("speaker") == "SPEAKER_01" and answer.get("source_ids") == ["S2", "S3", "S4"],
        "note_preserved_separately": note == {"text": source["investigator_notes"][0]["text"], "source_ids": ["N1"]},
        "no_old_example_facts": not any(value in json.dumps(result, ensure_ascii=False) for value in ["فؤاد", "منصور", "1978", "طرابلس", "جونية", "03123456", "الأحد", "الثامنة"]),
        "generation_completed": response.get("done_reason") == "stop",
    })
    after = api("/api/tags")
    inventory = lambda data: sorted((m["name"], m["digest"], m["size"]) for m in data["models"])
    checks["installed_models_unchanged"] = inventory(before) == inventory(after)
    metrics = {key: response.get(key) for key in ["total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count", "eval_duration", "done_reason"]}
    metadata = {"model": installed[MODEL], "ollama_version": api("/api/version"),
                "created_at_utc": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": round(elapsed, 3),
                "source_template_sha256": hashlib.sha256(source_format.read_bytes()).hexdigest(),
                "template_scope": "Short identity excerpt adapted from M53; Q&A and note; not the full report",
                "mode": "extract-only" if args.extract_only else "full-example-and-rewording",
                "model_responsibility": "Five fields only; Q&A and note copied by code" if args.extract_only else "Fields, Q&A formalization, speaker references and note",
                "field_value_checks": value_checks, "field_source_checks": source_checks,
                "checks": checks, "passed": sum(checks.values()), "total": len(checks), "metrics": metrics,
                "manual_review_required": "Assess full meaning, omissions, negation and ungrounded additions in Arabic answer; structural checks do not prove semantic correctness."}
    write_json("evaluation.json", metadata)
    e = lambda value: html.escape(str(value if value is not None else "غير مذكور"))
    labels = {"statement_name": "الاسم", "birth_year": "سنة الولادة", "birth_place": "مكان الولادة", "residence": "الإقامة", "phone": "الهاتف"}
    rows = "".join(f"<tr><th>{labels[key]}</th><td>{e(result.get('fields', {}).get(key, {}).get('value'))}</td></tr>" for key in fields)
    source_rows = "".join(f"<li><b>{e(s['speaker'])} · {s['start']:.3f}–{s['end']:.3f} s · {s['id']}</b><p>{e(s['text'])}</p></li>" for s in source["current_segments"])
    document = f"""<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><title>تجربة محضر قصيرة — Qwen2.5</title>
<style>body{{font:18px/1.9 Tahoma,Arial,sans-serif;max-width:900px;margin:32px auto;padding:20px;background:#f4f6f9;color:#17273b}}article{{background:white;padding:28px;border:1px solid #d8e0eb;border-radius:12px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d8e0eb;padding:8px;text-align:right}}p{{white-space:pre-wrap}}small{{color:#52647a}}li{{margin-bottom:16px}}</style>
<article><h1>تجربة محضر قصيرة</h1><p><strong>بيانات خيالية للاختبار — ليست وثيقة صادرة</strong></p>
<p>النموذج: <b dir="ltr">{MODEL}</b> · الزمن: {elapsed:.1f} ثانية</p><h2>بيانات صاحب الإفادة</h2><table>{rows}</table>
<h2>السؤال والجواب المقترحان</h2><p><b>س:</b> {e(question.get('text'))}</p><p><b>ج:</b> {e(answer.get('text'))}</p>
<small>مصادر الجواب: {e(', '.join(answer.get('source_ids', [])))}</small>
<h2>ملاحظة المحقق</h2><p>{e(note.get('text'))}</p><h2>النص الأصلي للمقارنة</h2><ol>{source_rows}</ol>
<p>الفحوص الآلية: {sum(checks.values())}/{len(checks)}. يلزم تقييم المعنى والنفي والتفاصيل يدوياً؛ نجاح الفحوص لا يثبت دقة الاستخدام العام.</p></article></html>"""
    (OUT / "preview.html").write_text(document, encoding="utf-8")
    print(json.dumps({"elapsed_seconds": metadata["elapsed_seconds"], "passed": metadata["passed"],
                      "total": metadata["total"], "failed": [key for key, passed in checks.items() if not passed],
                      "output": str(OUT)}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
