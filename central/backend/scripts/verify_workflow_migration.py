"""Rehearse the forward migration on an explicitly isolated restored database."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.config import get_settings

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("database", nargs="?")
mode = parser.add_mutually_exclusive_group()
mode.add_argument("--capture", type=Path, help="Read-only evidence baseline; no migrations")
mode.add_argument("--verify", type=Path, help="Read-only comparison with a saved baseline")
args = parser.parse_args()
url = make_url(get_settings().database_url)
if not (args.capture or args.verify):
    assert args.database and args.database.startswith("workflow_rehearsal_") and args.database.endswith("_test"), "Isolated database required"
    url = url.set(database=args.database)
engine = create_engine(url)
tables = ("investigation_sessions", "session_investigators", "subjects", "subject_documents",
          "audio_recordings", "local_processing_jobs", "transcripts", "transcript_segments",
          "session_speakers", "person_identities", "person_identifiers", "voice_enrollments", "audit_logs")
columns = {table: [column["name"] for column in inspect(engine).get_columns(table)] for table in tables}
if args.verify:
    baseline = json.loads(args.verify.read_text(encoding="utf-8"))
    columns = baseline["columns"]

def snapshot():
    result = {}
    with engine.connect() as connection:
        for table, names in columns.items():
            selection = ",".join('"' + name + '"' for name in names)
            rows = connection.execute(text(f'SELECT {selection} FROM "{table}"')).mappings().all()
            serialized = sorted(json.dumps(dict(row), default=str, sort_keys=True) for row in rows)
            result[table] = {"rows": len(rows), "sha256": hashlib.sha256("\n".join(serialized).encode()).hexdigest()}
    return result

before = snapshot()
if args.capture:
    args.capture.write_text(json.dumps({"columns": columns, "preserved": before}, indent=2), encoding="utf-8")
    print("Captured investigation and evidence baseline; database unchanged")
    raise SystemExit(0)
if args.verify:
    assert before == baseline["preserved"], "Investigation or evidence baseline differs"
    print(json.dumps({"preserved": before, "unchanged": True}, indent=2))
    raise SystemExit(0)
os.environ["ALEMBIC_DATABASE_URL"] = url.render_as_string(hide_password=False)
command.upgrade(Config("alembic.ini"), "head")
after = snapshot()
assert before == after, "Evidence or investigation records changed during migration"
with engine.connect() as connection:
    assert connection.scalar(text("SELECT count(*) FROM generated_reports WHERE format_key != 'statement-html-1'")) == 0
    assert connection.scalar(text("SELECT to_regclass('report_template_versions')")) is None
    revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
print(json.dumps({"revision": revision, "preserved": after, "legacy_creation_data_removed": True}, indent=2))
