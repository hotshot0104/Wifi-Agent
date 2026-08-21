#!/usr/bin/env python3
"""Install/update the private runtime and dispatch a management command."""

from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import sys
import venv


APP_NAME = "WiFiAgent"


def runtime_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME / "runtime"


def main() -> int:
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.", file=sys.stderr)
        return 2
    source = Path(__file__).resolve().parent
    runtime = runtime_dir()
    runtime.mkdir(parents=True, exist_ok=True)
    installed_script = runtime / "wifi_agent.py"
    installed_requirements = runtime / "requirements.txt"
    shutil.copy2(source / "wifi_agent.py", installed_script)
    shutil.copy2(source / "requirements.txt", installed_requirements)

    environment = runtime / ".venv"
    if not environment.exists():
        print("Creating the local Python environment…")
        venv.EnvBuilder(with_pip=True).create(environment)
    if os.name == "nt":
        python = environment / "Scripts" / "python.exe"
    else:
        python = environment / "bin" / "python"
    requirement_hash = hashlib.sha256(installed_requirements.read_bytes()).hexdigest()
    marker = runtime / ".requirements-installed"
    if not marker.exists() or marker.read_text(encoding="ascii", errors="ignore") != requirement_hash:
        print("Installing/updating required packages…")
        subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(installed_requirements)],
            check=True,
        )
        marker.write_text(requirement_hash, encoding="ascii")

    command = sys.argv[1:] or ["setup"]
    return subprocess.call([str(python), str(installed_script), *command])


if __name__ == "__main__":
    raise SystemExit(main())
