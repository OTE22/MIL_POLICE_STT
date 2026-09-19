"""Open (or close) a local pgAdmin/psql tunnel to the mstt-postgres container.

The database publishes no port on purpose - it lives on the internal compose network
only. For debugging, this script runs a tiny socat sidecar that joins that network and
forwards 127.0.0.1:5432 on this machine to postgres:5432 inside. Nothing in the stack
is touched, recreated or restarted, and removing the sidecar closes the door again.

    python scripts/pg_debug_tunnel.py            # open the tunnel
    python scripts/pg_debug_tunnel.py --status   # is it open?
    python scripts/pg_debug_tunnel.py --stop     # close it

Then in pgAdmin 4: host 127.0.0.1, port 5432, database military_stt, user stt,
password = POSTGRES_PASSWORD from the project .env.

Deliberately bound to 127.0.0.1 only: voice_enrollments holds biometric embeddings,
and this must never offer them to the LAN. Treat the connection as read-only - edits
that bypass the API (person_name/person_reference, hand-deleted registry rows) corrupt
identity bookkeeping while looking like they worked.
"""

import argparse
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

CONTAINER = "pg-debug-tunnel"
DB_CONTAINER = "mstt-postgres"
DB_SERVICE_HOST = "postgres"  # the service name on the compose network
LOCAL_BIND = "127.0.0.1"
LOCAL_PORT = 5432
IMAGE = "alpine/socat"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True)


def die(msg: str) -> NoReturn:
    print(f"ERROR: {msg}")
    sys.exit(1)


def tunnel_running() -> bool:
    res = run("ps", "--filter", f"name=^{CONTAINER}$", "--format", "{{.Names}}")
    return CONTAINER in res.stdout.split()


def find_db_network() -> str:
    """Ask the running postgres container which network it is on - never guess the
    compose project prefix, it changes with the folder name."""
    res = run(
        "inspect", DB_CONTAINER,
        "--format", "{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}",
    )
    if res.returncode != 0:
        die(f"container {DB_CONTAINER} not found - is the stack up? (docker compose up -d)")
    networks = res.stdout.split()
    if not networks:
        die(f"{DB_CONTAINER} is on no network?")
    if len(networks) > 1:
        print(f"note: {DB_CONTAINER} is on several networks, using {networks[0]}")
    return networks[0]


def port_answers() -> bool:
    try:
        with socket.create_connection((LOCAL_BIND, LOCAL_PORT), timeout=2):
            return True
    except OSError:
        return False


def env_credentials() -> dict:
    """Read the connection facts (not the password value) from the project .env."""
    creds = {"POSTGRES_DB": "military_stt", "POSTGRES_USER": "stt"}
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^(POSTGRES_DB|POSTGRES_USER)=(.*)$", line.strip())
            if m:
                creds[m.group(1)] = m.group(2)
    return creds


def print_connection_help() -> None:
    creds = env_credentials()
    print("\npgAdmin 4 -> Register Server -> Connection:")
    print(f"  Host name/address    : {LOCAL_BIND}")
    print(f"  Port                 : {LOCAL_PORT}")
    print(f"  Maintenance database : {creds['POSTGRES_DB']}")
    print(f"  Username             : {creds['POSTGRES_USER']}")
    print(f"  Password             : POSTGRES_PASSWORD in {PROJECT_ROOT / '.env'}")
    print(f"\nclose the tunnel when done:  python {Path(__file__).relative_to(PROJECT_ROOT)} --stop")


def start() -> None:
    if tunnel_running():
        print(f"{CONTAINER} is already running.")
        print_connection_help()
        return
    # A stopped leftover with the same name would block docker run.
    run("rm", "-f", CONTAINER)

    if port_answers():
        die(f"something else already listens on {LOCAL_BIND}:{LOCAL_PORT} - "
            "stop it or it is a previous tunnel under another name")

    network = find_db_network()
    print(f"starting {CONTAINER} on network {network} "
          f"({LOCAL_BIND}:{LOCAL_PORT} -> {DB_SERVICE_HOST}:5432) ...")
    res = run(
        "run", "-d", "--name", CONTAINER,
        "--network", network,
        "-p", f"{LOCAL_BIND}:{LOCAL_PORT}:5432",
        "--restart", "no",  # a debug door must not reopen itself on reboot
        IMAGE,
        "tcp-listen:5432,fork,reuseaddr", f"tcp-connect:{DB_SERVICE_HOST}:5432",
    )
    if res.returncode != 0:
        die(res.stderr.strip())

    # Prove the path works end to end before claiming success.
    for _ in range(10):
        if port_answers():
            print("tunnel is up and answering.")
            print_connection_help()
            return
        time.sleep(0.5)
    run("rm", "-f", CONTAINER)
    die("the sidecar started but the port never answered - removed it again")


def stop() -> None:
    if not tunnel_running():
        run("rm", "-f", CONTAINER)  # clear a stopped leftover, if any
        print("no tunnel is running.")
        return
    res = run("rm", "-f", CONTAINER)
    if res.returncode != 0:
        die(res.stderr.strip())
    print("tunnel closed - the database is internal-only again.")


def status() -> None:
    if tunnel_running():
        answering = "and answering" if port_answers() else "but NOT answering"
        print(f"tunnel is running {answering} on {LOCAL_BIND}:{LOCAL_PORT}.")
    else:
        print("no tunnel is running (database reachable only inside the compose network).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--stop", action="store_true", help="close the tunnel")
    action.add_argument("--status", action="store_true", help="report whether it is open")
    args = parser.parse_args()

    if run("version", "--format", "{{.Server.Version}}").returncode != 0:
        die("docker is not reachable - is Docker Desktop running?")

    if args.stop:
        stop()
    elif args.status:
        status()
    else:
        start()


if __name__ == "__main__":
    main()
