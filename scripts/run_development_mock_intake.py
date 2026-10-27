"""Run the guarded development-only seed through the existing backend's authenticated API."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
command = ['docker', 'exec', '-i', 'mstt-backend', 'python', '-']
if '--apply' in sys.argv:
    command.append('--apply')
subprocess.run(command, input=(root / 'scripts/fill_development_session_intake.py').read_bytes(), cwd=root, check=True)
