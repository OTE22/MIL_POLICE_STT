#!/usr/bin/env python3
"""
Wipe EVERY row from the central database AND the local agent - full clean slate.
================================================================================

Unlike ``reset_demo_data.sh``, which preserves users, roles and permissions,
this script empties *every* application table, user accounts included. The only
thing kept is ``alembic_version``, so the schema stays migrated and no
``alembic upgrade`` is needed afterwards.

It clears three separate stores, which is the whole point: deleting the database
rows alone leaves the recorded audio sitting on disk in two places.

  1. central database   every table except alembic_version
  2. central storage    storage/recordings, storage/subject-documents
  3. local agent        desktop-agent/data/jobs (the recordings held on THIS
                        device) plus the jobs / job_tokens / nonces rows in
                        desktop-agent/data/agent.sqlite3

Deliberately kept:

  * ``alembic_version``               - schema stays migrated
  * ``central_public_key.pem``        - the agent cannot verify processing
                                        tokens without it
  * the agent's ``settings`` row      - holds agent_id, this device's identity.
                                        Pass --reset-agent-id to drop it and
                                        have the agent register as a new device.
  * ``desktop-agent/models``          - the model weights, mounted read-only

Everything is then restarted, which makes ``app.services.bootstrap.run_bootstrap``
re-seed roles, permissions and one administrator - username
CENTRAL_BOOTSTRAP_ADMIN_USERNAME, password CENTRAL_BOOTSTRAP_ADMIN_PASSWORD,
flagged must_change_password.

Usage (from anywhere):

    python scripts/wipe_all_data.py --yes

Safety: --yes alone is not enough. The script refuses unless CENTRAL_ENVIRONMENT
is development, demo or test, and - on a terminal - it also makes you type the
database name.

No third-party packages are required on the host: all SQL goes through
``docker compose exec postgres psql``, and the agent store is plain sqlite3.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT / "docker-compose.yml"

AGENT_DIR = ROOT / "desktop-agent"
AGENT_CONTAINER = "mstt-agent"          # container_name, fixed in the agent compose file

# Kept so the schema stays migrated; everything else in `public` is emptied.
PRESERVED_TABLES = {"alembic_version"}

# Subdirectories of storage/ whose *contents* are removed. The directories
# themselves stay: the backend expects them to exist.
STORAGE_SUBDIRS = ("recordings", "subject-documents")

# Agent sqlite tables holding operational data. `settings` is NOT here: it holds
# agent_id, which is device identity rather than data (see --reset-agent-id).
AGENT_TABLES = ("jobs", "job_tokens", "nonces")

# Files directly under the agent data dir that must survive the wipe.
AGENT_KEEP_FILES = {"central_public_key.pem", ".gitkeep"}

SAFE_ENVIRONMENTS = {"development", "demo", "test"}
BLOCKED_ENVIRONMENTS = {"production", "prod", "staging"}

RED, GRN, YEL, BLU, DIM, RST = (
    "\033[31m", "\033[32m", "\033[33m", "\033[34m", "\033[2m", "\033[0m",
)


def step(msg: str) -> None:
    print(f"\n{BLU}==> {msg}{RST}")


def ok(msg: str) -> None:
    print(f"  {GRN}[ ok ]{RST} {msg}")


def warn(msg: str) -> None:
    print(f"  {YEL}[warn]{RST} {msg}")


def note(msg: str) -> None:
    print(f"  {DIM}{msg}{RST}")


def die(msg: str) -> "NoReturn":  # type: ignore[valid-type]
    print(f"\n{RED}[REFUSED]{RST} {msg}\n", file=sys.stderr)
    raise SystemExit(1)


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def tree_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


# ---------------------------------------------------------------------------
# .env
# ---------------------------------------------------------------------------
def read_env(path: Path, *, required: bool = True) -> dict[str, str]:
    """Minimal KEY=VALUE reader. No interpolation, no `export`, quotes stripped."""
    if not path.is_file():
        if required:
            die(f"no .env at {path} - cannot determine the environment")
        return {}

    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


# ---------------------------------------------------------------------------
# docker helpers
# ---------------------------------------------------------------------------
def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        die(f"command failed: {' '.join(cmd)}\n{(result.stderr or result.stdout).strip()}")
    return result


def container_state(name: str) -> str | None:
    """'running', 'exited', ... or None when no such container exists."""
    result = run(
        ["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.State}}"],
        check=False,
    )
    state = result.stdout.strip()
    return state or None


def psql(sql: str, db_user: str, db_name: str, *, quiet: bool = True) -> str:
    """Run one statement in the postgres service and return trimmed stdout."""
    cmd = [
        "docker", "compose", "-f", str(COMPOSE_FILE), "exec", "-T", "postgres",
        "psql", "-v", "ON_ERROR_STOP=1", "-U", db_user, "-d", db_name,
        "-tAX", "-c", sql,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if quiet:
            die(f"psql failed:\n{detail}")
        raise RuntimeError(detail)
    return result.stdout.strip()


def table_counts(tables: list[str], db_user: str, db_name: str) -> dict[str, int]:
    """One round trip for all counts, rather than one per table."""
    if not tables:
        return {}
    union = " UNION ALL ".join(
        f"SELECT '{t}' AS t, count(*) AS n FROM {t}" for t in tables
    )
    counts: dict[str, int] = {}
    for line in psql(f"{union} ORDER BY t", db_user, db_name).splitlines():
        name, _, number = line.partition("|")
        if number:
            counts[name] = int(number)
    return counts


# ---------------------------------------------------------------------------
# safe deletion
# ---------------------------------------------------------------------------
def resolve_inside_project(path: Path, label: str) -> Path:
    """Canonicalise before deleting. Never remove a tree that has not been
    proven to sit where it is supposed to."""
    candidate = path.resolve()
    if not candidate.is_dir():
        die(f"{label} not found at {path}")
    root = ROOT.resolve()
    if root not in candidate.parents and candidate != root:
        die(f"{label} '{candidate}' resolves outside the project - refusing to delete")
    if candidate == Path(candidate.anchor):
        die(f"{label} resolved to the filesystem root")
    return candidate


def clear_contents(directory: Path) -> int:
    """Delete everything inside `directory`, keeping the directory itself."""
    removed = 0
    for entry in directory.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
        removed += 1
    return removed


# ---------------------------------------------------------------------------
# agent
# ---------------------------------------------------------------------------
def wipe_agent(agent_data: Path, *, reset_agent_id: bool) -> None:
    """Clear this device's local recordings and job store."""
    jobs_dir = agent_data / "jobs"
    if jobs_dir.is_dir():
        size = tree_size(jobs_dir)
        removed = clear_contents(jobs_dir)
        ok(f"{removed} local job folder(s) deleted ({human(size)} of recordings)")
    else:
        note("no jobs directory - no local recordings to clear")

    db_path = agent_data / "agent.sqlite3"
    if not db_path.is_file():
        note("no agent.sqlite3 - nothing to clear in the job store")
    else:
        conn = sqlite3.connect(str(db_path))
        try:
            present = {
                row[0] for row in
                conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            targets = list(AGENT_TABLES) + (["settings"] if reset_agent_id else [])
            cleared = []
            for table in targets:
                if table not in present:
                    continue
                before = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                conn.execute(f"DELETE FROM {table}")
                cleared.append(f"{table} ({before})")
            conn.commit()
            # Collapses the WAL and reclaims the pages the deletes freed.
            conn.execute("VACUUM")
        finally:
            conn.close()
        ok("job store cleared: " + (", ".join(cleared) if cleared else "already empty"))
        if reset_agent_id:
            note("agent_id dropped - the agent registers as a NEW device on next sync")
        else:
            note("agent_id kept - this device keeps its identity")

    # Anything else left directly under data/ that is not on the keep list is
    # stale state; surface it rather than deleting it silently.
    for entry in agent_data.iterdir():
        if entry.is_file() and entry.name not in AGENT_KEEP_FILES:
            if entry.name.startswith("agent.sqlite3"):
                continue
            warn(f"unexpected file left in agent data: {entry.name}")

    key = agent_data / "central_public_key.pem"
    if key.is_file():
        ok("central_public_key.pem preserved")
    else:
        warn("central_public_key.pem is missing - the agent cannot verify processing tokens")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete every row from the central database and every local "
                    "recording, then restart the app."
    )
    parser.add_argument("--yes", "-y", action="store_true",
                        help="required; without it the script refuses to run")
    parser.add_argument("--keep-files", action="store_true",
                        help="leave storage/ and the agent's recordings on disk")
    parser.add_argument("--skip-agent", action="store_true",
                        help="do not touch desktop-agent/data")
    parser.add_argument("--reset-agent-id", action="store_true",
                        help="also drop the agent's saved agent_id, so it registers as a new device")
    parser.add_argument("--no-restart", action="store_true",
                        help="skip the restart; nothing is re-seeded until you restart the backend yourself")
    args = parser.parse_args()

    # -- Safety ------------------------------------------------------------
    step("Safety checks")
    if not args.yes:
        die("refusing to run without --yes")

    env = read_env(ROOT / ".env")

    environment = env.get("CENTRAL_ENVIRONMENT", "").strip().lower()
    if not environment:
        die("CENTRAL_ENVIRONMENT is not set in .env. Refusing to guess.")
    if environment in BLOCKED_ENVIRONMENTS:
        die(f"CENTRAL_ENVIRONMENT is '{environment}'. This script never touches that.")
    if environment not in SAFE_ENVIRONMENTS:
        die(f"CENTRAL_ENVIRONMENT is '{environment}', which is not development, demo or test.")
    ok(f"environment is '{environment}'")

    db_name = env.get("POSTGRES_DB", "")
    db_user = env.get("POSTGRES_USER", "")
    if not db_name or not db_user:
        die("POSTGRES_DB / POSTGRES_USER are not set in .env")
    if "prod" in db_name.lower():
        die(f"database name '{db_name}' looks like production")
    ok(f"database '{db_name}'")

    if not COMPOSE_FILE.is_file():
        die(f"no docker-compose.yml at {COMPOSE_FILE}")

    storage_root: Path | None = None
    if not args.keep_files:
        storage_root = resolve_inside_project(ROOT / "storage", "storage root")
        ok(f"storage root {storage_root}")

    # The agent's data dir is a bind mount; honour an AGENT_DATA_PATH override
    # rather than assuming ./data.
    agent_data: Path | None = None
    if not args.skip_agent:
        agent_env = read_env(AGENT_DIR / ".env", required=False)
        configured = agent_env.get("AGENT_DATA_PATH", "./data")
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = AGENT_DIR / candidate
        agent_data = resolve_inside_project(candidate, "agent data dir")
        ok(f"agent data {agent_data}")

    # -- Inventory ---------------------------------------------------------
    step("Inspecting the database")
    tables = [
        t for t in psql(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename",
            db_user, db_name,
        ).splitlines() if t and t not in PRESERVED_TABLES
    ]
    if not tables:
        die("no application tables found - is this the right database?")

    before = table_counts(tables, db_user, db_name)
    total = sum(before.values())
    for name in sorted(before, key=lambda n: (-before[n], n)):
        if before[name]:
            print(f"    {before[name]:>8,}  {name}")
    note(f"{len(tables)} tables, {total:,} rows to delete")
    note(f"preserved: {', '.join(sorted(PRESERVED_TABLES))}")

    if agent_data is not None:
        jobs_dir = agent_data / "jobs"
        if jobs_dir.is_dir():
            folders = sum(1 for _ in jobs_dir.iterdir())
            note(f"local agent: {folders} job folder(s), {human(tree_size(jobs_dir))}")

    print(f"\n  {YEL}This deletes EVERY row, user accounts included.{RST}")
    print(f"  Environment: {environment}, database: {db_name}")
    if not args.keep_files:
        print(f"  Stored audio and documents under {storage_root} are deleted too.")
    if agent_data is not None and not args.keep_files:
        print(f"  Local recordings under {agent_data / 'jobs'} are deleted too.")
    if sys.stdin.isatty():
        # Git Bash and some CI shells report a tty while stdin is already at
        # EOF. That is the absence of a human, not a failed confirmation, so
        # fall back to --yes and the environment gate rather than aborting.
        try:
            typed = input("  Type the database name to confirm: ").strip()
        except EOFError:
            print()
            note("stdin is not readable - proceeding on --yes alone")
        else:
            if typed != db_name:
                die("confirmation did not match")

    # -- Agent, before the restart ----------------------------------------
    # The agent holds agent.sqlite3 open with WAL, so it has to stop before the
    # store is rewritten. It is started again in the restart step below.
    agent_was_present = False
    if agent_data is not None:
        step("Clearing local agent data")
        state = container_state(AGENT_CONTAINER)
        agent_was_present = state is not None
        if state == "running":
            run(["docker", "stop", AGENT_CONTAINER])
            ok(f"{AGENT_CONTAINER} stopped")
        elif state:
            note(f"{AGENT_CONTAINER} is {state} - no need to stop it")
        else:
            note(f"no {AGENT_CONTAINER} container; clearing the data directory anyway")

        if args.keep_files:
            note("--keep-files given: recordings kept, clearing the job store only")
            jobs_dir = agent_data / "jobs"
            if jobs_dir.is_dir():
                note(f"  {human(tree_size(jobs_dir))} of local audio left in place")
            wipe_agent_store_only(agent_data, reset_agent_id=args.reset_agent_id)
        else:
            wipe_agent(agent_data, reset_agent_id=args.reset_agent_id)

    # -- Truncate ----------------------------------------------------------
    step("Clearing the database")
    # One statement covering every table: CASCADE then resolves the FK order for
    # us, including the self-references on users and person_identities that no
    # hand-written delete order can satisfy. RESTART IDENTITY resets sequences so
    # the fresh data starts at id 1.
    psql(
        "TRUNCATE TABLE " + ", ".join(tables) + " RESTART IDENTITY CASCADE;",
        db_user, db_name,
    )
    ok(f"{len(tables)} tables truncated")

    after = table_counts(tables, db_user, db_name)
    remaining = {t: n for t, n in after.items() if n}
    if remaining:
        die(f"expected every table empty, found rows in: {remaining}")
    ok(f"verified empty ({total:,} rows deleted)")

    version = psql("SELECT version_num FROM alembic_version", db_user, db_name)
    ok(f"alembic_version preserved ({version or 'empty'})")

    # -- Central files -----------------------------------------------------
    step("Clearing stored files")
    if storage_root is not None:
        for sub in STORAGE_SUBDIRS:
            target = storage_root / sub
            if not target.is_dir():
                note(f"{sub} does not exist - nothing to clear")
                continue
            clear_contents(target)
            ok(f"{sub} cleared")

        leftover = [p for p in storage_root.rglob("*") if p.is_file()]
        if leftover:
            warn(f"{len(leftover)} file(s) remain under {storage_root}")
        else:
            ok("central storage is empty")
    else:
        note("--keep-files given: storage/ left untouched (rows are gone, files are now orphaned)")

    # -- Restart -----------------------------------------------------------
    step("Restarting the app")
    if args.no_restart:
        note("--no-restart given: restart the backend yourself to re-seed the admin")
        note("    docker compose restart")
        if agent_was_present:
            note(f"    docker start {AGENT_CONTAINER}")
        return 0

    run(["docker", "compose", "-f", str(COMPOSE_FILE), "restart"])
    ok("central stack restarted (postgres, backend, frontend, nginx)")

    if agent_was_present:
        run(["docker", "start", AGENT_CONTAINER])
        ok(f"{AGENT_CONTAINER} started")

    admin_user = env.get("CENTRAL_BOOTSTRAP_ADMIN_USERNAME", "admin")

    # run_bootstrap executes during startup; poll rather than guess how long it takes.
    for _ in range(90):
        try:
            found = psql(
                f"SELECT count(*) FROM users WHERE username = '{admin_user}'",
                db_user, db_name, quiet=False,
            )
        except RuntimeError:
            found = "0"          # postgres or backend still coming up
        if found == "1":
            break
        time.sleep(1)
    else:
        die(
            f"administrator '{admin_user}' was not re-created within 90s - "
            "check: docker compose logs backend"
        )

    roles = psql("SELECT count(*) FROM roles", db_user, db_name)
    perms = psql("SELECT count(*) FROM permissions", db_user, db_name)
    ok(f"administrator '{admin_user}' re-created ({roles} roles, {perms} permissions seeded)")

    print(f"""
{GRN}Everything wiped and restarted.{RST}

  Log in with:
      username  {admin_user}
      password  CENTRAL_BOOTSTRAP_ADMIN_PASSWORD from .env

  The account is flagged must_change_password, so the first login goes
  straight to the password-change screen.
""")
    return 0


def wipe_agent_store_only(agent_data: Path, *, reset_agent_id: bool) -> None:
    """--keep-files variant: clear the job store but leave the audio on disk."""
    db_path = agent_data / "agent.sqlite3"
    if not db_path.is_file():
        note("no agent.sqlite3 - nothing to clear in the job store")
        return
    conn = sqlite3.connect(str(db_path))
    try:
        present = {
            row[0] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        targets = list(AGENT_TABLES) + (["settings"] if reset_agent_id else [])
        cleared = []
        for table in targets:
            if table not in present:
                continue
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            conn.execute(f"DELETE FROM {table}")
            cleared.append(f"{table} ({count})")
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    ok("job store cleared: " + (", ".join(cleared) if cleared else "already empty"))


if __name__ == "__main__":
    raise SystemExit(main())
