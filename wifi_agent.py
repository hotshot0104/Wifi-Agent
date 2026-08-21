#!/usr/bin/env python3
"""WiFi Agent: cross-platform Sophos/Cyberoam captive-portal automation."""

from __future__ import annotations

import argparse
from functools import lru_cache
import getpass
from html import escape as xml_escape
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import plistlib
import socket
import ssl
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

try:
    import keyring
    from keyring.errors import KeyringError, NoKeyringError
except ImportError:  # Helpful error before bootstrap has installed dependencies.
    keyring = None
    KeyringError = NoKeyringError = Exception

try:
    import psutil
except ImportError:
    psutil = None


APP_NAME = "WiFiAgent"
KEYRING_SERVICE = "WiFi Agent"
DEFAULT_CONFIG: dict[str, Any] = {
    "username": "",
    "portal_host": "192.168.1.2",
    "portal_port": 8090,
    "check_interval_seconds": 45,
    "network_interface": "auto",
    "allow_self_signed_portal": True,
}


def app_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / APP_NAME


CONFIG_PATH = app_dir() / "config.json"
LOG_PATH = app_dir() / "agent.log"


def ensure_dependencies() -> None:
    missing = []
    if keyring is None:
        missing.append("keyring")
    if psutil is None:
        missing.append("psutil")
    if missing:
        raise SystemExit(
            "Missing dependencies: " + ", ".join(missing)
            + ". Run install.py first, or: python -m pip install -r requirements.txt"
        )


def load_config() -> dict[str, Any]:
    config = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                config.update(saved)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot read {CONFIG_PATH}: {exc}") from exc
    return config


def save_config(config: dict[str, Any]) -> None:
    app_dir().mkdir(parents=True, exist_ok=True)
    public_config = {key: config[key] for key in DEFAULT_CONFIG if key in config}
    temporary = CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(public_config, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(0o600)
    temporary.replace(CONFIG_PATH)


def credential_backend_ready() -> tuple[bool, str]:
    ensure_dependencies()
    try:
        backend = keyring.get_keyring()
        priority = getattr(backend, "priority", 0)
        if priority <= 0:
            return False, "No usable operating-system credential vault was found."
        return True, backend.__class__.__name__
    except Exception as exc:
        return False, str(exc)


def store_credentials(username: str, password: str, old_username: str = "") -> None:
    ready, detail = credential_backend_ready()
    if not ready:
        raise RuntimeError(
            detail + " Install/unlock Windows Credential Manager, macOS Keychain, "
            "or a Linux Secret Service keyring and try again."
        )
    try:
        keyring.set_password(KEYRING_SERVICE, username, password)
        if old_username and old_username != username:
            try:
                keyring.delete_password(KEYRING_SERVICE, old_username)
            except KeyringError:
                pass
    except (KeyringError, NoKeyringError) as exc:
        raise RuntimeError(f"The password could not be saved in the OS credential vault: {exc}") from exc


def get_password(username: str) -> str:
    ensure_dependencies()
    try:
        password = keyring.get_password(KEYRING_SERVICE, username)
    except (KeyringError, NoKeyringError) as exc:
        raise RuntimeError(f"The OS credential vault is unavailable: {exc}") from exc
    if not password:
        raise RuntimeError("No saved password was found. Open setup and save the credentials again.")
    return password


def active_interfaces() -> list[str]:
    """Return active, non-loopback interfaces that currently own an IPv4 address."""
    ensure_dependencies()
    try:
        stats = psutil.net_if_stats()
        address_map = psutil.net_if_addrs()
    except (OSError, PermissionError):
        return _fallback_active_interfaces()
    result: list[str] = []
    for name, addresses in address_map.items():
        if not stats.get(name) or not stats[name].isup:
            continue
        if any(a.family == socket.AF_INET and not a.address.startswith("127.") for a in addresses):
            result.append(name)
    return sorted(result, key=str.casefold)


def _fallback_active_interfaces() -> list[str]:
    """Best-effort fallback for restricted machines where psutil/netlink is blocked."""
    if sys.platform.startswith("linux"):
        result = []
        for interface_path in Path("/sys/class/net").glob("*"):
            try:
                if interface_path.name == "lo":
                    continue
                state = (interface_path / "operstate").read_text(encoding="ascii").strip()
                carrier_path = interface_path / "carrier"
                carrier = carrier_path.read_text(encoding="ascii").strip() if carrier_path.exists() else "1"
                if state == "up" and carrier == "1":
                    result.append(interface_path.name)
            except OSError:
                continue
        return sorted(result, key=str.casefold)

    if sys.platform == "darwin":
        try:
            names = subprocess.run(
                ["ifconfig", "-l"], check=True, capture_output=True, text=True, timeout=5
            ).stdout.split()
            active = []
            for name in names:
                detail = subprocess.run(
                    ["ifconfig", name], check=True, capture_output=True, text=True, timeout=5
                ).stdout
                if "status: active" in detail and " inet " in detail:
                    active.append(name)
            return sorted(active, key=str.casefold)
        except (OSError, subprocess.SubprocessError):
            return []

    if sys.platform == "win32":
        command = (
            "Get-NetIPConfiguration | Where-Object { $_.IPv4Address -and "
            "$_.NetAdapter.Status -eq 'Up' } | Select-Object -ExpandProperty InterfaceAlias"
        )
        try:
            output = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                check=True, capture_output=True, text=True, timeout=8,
            ).stdout
            return sorted((line.strip() for line in output.splitlines() if line.strip()), key=str.casefold)
        except (OSError, subprocess.SubprocessError):
            return []
    return []


@lru_cache(maxsize=1)
def _mac_wireless_interfaces() -> frozenset[str]:
    if sys.platform != "darwin":
        return frozenset()
    try:
        output = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            check=True, capture_output=True, text=True, timeout=8,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    wireless: set[str] = set()
    hardware_port = ""
    for line in output.splitlines():
        if line.startswith("Hardware Port:"):
            hardware_port = line.partition(":")[2].strip().casefold()
        elif line.startswith("Device:") and any(word in hardware_port for word in ("wi-fi", "airport", "wireless")):
            wireless.add(line.partition(":")[2].strip())
    return frozenset(wireless)


def _looks_wired(name: str) -> bool:
    lower = name.casefold()
    excluded = (
        "wi-fi", "wifi", "wlan", "wireless", "airport", "loopback", "bluetooth",
        "docker", "veth", "virbr", "vmnet", "virtual", "tailscale", "utun", "tun", "tap",
    )
    if any(word in lower for word in excluded):
        return False
    if sys.platform == "darwin" and name in _mac_wireless_interfaces():
        return False
    if sys.platform.startswith("linux"):
        interface_path = Path("/sys/class/net") / name
        if (interface_path / "wireless").exists():
            return False
        # A physical/USB Ethernet interface has a device link. Some valid bonded
        # interfaces do not, so names commonly used for Ethernet remain accepted.
        if (interface_path / "device").exists():
            return True
        return lower.startswith(("eth", "en", "eno", "ens", "enp", "bond"))
    return True


def wired_interfaces(configured: str = "auto") -> list[str]:
    active = active_interfaces()
    if configured and configured != "auto":
        return [configured] if configured in active else []
    return [name for name in active if _looks_wired(name)]


def portal_port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


INTERNET_PROBES = (
    ("https://connectivitycheck.gstatic.com/generate_204", 204, None),
    ("http://www.msftconnecttest.com/connecttest.txt", 200, b"Microsoft Connect Test"),
    ("https://captive.apple.com/hotspot-detect.html", 200, b"Success"),
)


def internet_available(timeout: float = 5.0) -> bool:
    for url, expected_status, expected_body in INTERNET_PROBES:
        try:
            request = Request(url, headers={"User-Agent": f"{APP_NAME}/1.0"})
            with urlopen(request, timeout=timeout) as response:
                body = response.read(256)
                if response.status == expected_status and (
                    expected_body is None or expected_body in body
                ):
                    return True
        except (HTTPError, URLError, OSError, TimeoutError, ssl.SSLError):
            continue
    return False


class PortalClient:
    def __init__(self, config: dict[str, Any], password: str):
        self.username = str(config["username"])
        self.password = password
        self.host = str(config["portal_host"])
        self.port = int(config["portal_port"])
        self.base_url = f"https://{self.host}:{self.port}"
        self.ssl_context = ssl.create_default_context()
        if config.get("allow_self_signed_portal", True):
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

    def _request(self, request: Request, timeout: float = 10.0) -> str:
        with urlopen(request, timeout=timeout, context=self.ssl_context) as response:
            return response.read(64 * 1024).decode("utf-8", errors="replace")

    @staticmethod
    def _response_summary(text: str) -> tuple[bool, str]:
        import xml.etree.ElementTree as ET

        status = ""
        message = ""
        try:
            root = ET.fromstring(text)
            status = (root.findtext(".//status") or "").strip()
            message = (root.findtext(".//message") or "").strip()
        except ET.ParseError:
            pass
        combined = " ".join(part for part in (status, message) if part) or "HTTP response received"
        bad_words = ("fail", "invalid", "denied", "error", "could not", "maximum login")
        success = status.upper() in {"ACK", "LIVE", "OK", "SUCCESS"}
        if not status and message and not any(word in message.casefold() for word in bad_words):
            success = True
        return success, combined

    def login(self) -> tuple[bool, str]:
        form = urlencode({
            "mode": "191",
            "username": self.username,
            "password": self.password,
            "producttype": "0",
        }).encode("utf-8")
        request = Request(
            f"{self.base_url}/login.xml",
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": f"{APP_NAME}/1.0"},
            method="POST",
        )
        try:
            return self._response_summary(self._request(request))
        except (HTTPError, URLError, OSError, TimeoutError, ssl.SSLError) as exc:
            return False, str(exc)

    def keep_alive(self) -> tuple[bool, str]:
        url = f"{self.base_url}/live?mode=192&username={quote(self.username, safe='')}"
        try:
            return self._response_summary(self._request(Request(url, headers={"User-Agent": f"{APP_NAME}/1.0"}), 8))
        except (HTTPError, URLError, OSError, TimeoutError, ssl.SSLError) as exc:
            return False, str(exc)


def build_logger(console: bool = True) -> logging.Logger:
    app_dir().mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(APP_NAME)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        logger.addHandler(stream)
    return logger


def run_agent(once: bool = False) -> int:
    ensure_dependencies()
    config = load_config()
    username = str(config.get("username", "")).strip()
    if not username:
        print("No credentials configured. Run: python wifi_agent.py setup", file=sys.stderr)
        return 2
    try:
        password = get_password(username)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    logger = build_logger(console=sys.stderr is not None and sys.stderr.isatty())
    client = PortalClient(config, password)
    interval = max(15, int(config.get("check_interval_seconds", 45)))
    selected_interface = str(config.get("network_interface", "auto"))
    last_state: tuple[Any, ...] | None = None
    last_login_attempt = 0.0
    logger.info("Agent started; portal=%s:%s interface=%s", client.host, client.port, selected_interface)

    try:
        while True:
            wired = wired_interfaces(selected_interface)
            port_open = portal_port_open(client.host, client.port) if wired else False
            online = internet_available() if wired else False
            state = (tuple(wired), port_open, online)
            if state != last_state:
                logger.info(
                    "Status: ethernet=%s (%s), portal-port=%s, internet=%s",
                    "connected" if wired else "disconnected",
                    ", ".join(wired) if wired else "none",
                    "open" if port_open else "closed/unreachable",
                    "available" if online else "unavailable",
                )
                last_state = state

            if wired and port_open:
                if online:
                    ok, message = client.keep_alive()
                    if not ok:
                        logger.warning("Portal keep-alive was not acknowledged: %s", message)
                elif time.monotonic() - last_login_attempt >= max(30, interval):
                    last_login_attempt = time.monotonic()
                    logger.info("Ethernet is connected but internet is unavailable; attempting portal login")
                    ok, message = client.login()
                    if ok:
                        logger.info("Portal login accepted: %s", message)
                        time.sleep(3)
                        if internet_available():
                            online = True
                            logger.info("Internet became available after portal login")
                            last_state = None
                        else:
                            logger.warning("Login was accepted, but internet is still unavailable")
                    else:
                        logger.warning("Portal login rejected/failed: %s", message)

            if once:
                return 0 if online else 1
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Agent stopped")
        return 0


def _service_command() -> list[str]:
    executable = Path(sys.executable)
    if sys.platform == "win32":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            executable = pythonw
    return [str(executable), str(Path(__file__).resolve()), "run"]


def install_startup() -> str:
    username = str(load_config().get("username", "")).strip()
    if not username:
        raise RuntimeError("Save credentials before installing the startup service.")
    # Refuse to install a service that is guaranteed to fail immediately.
    get_password(username)
    command = _service_command()
    app_dir().mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        account = getpass.getuser()
        domain = os.environ.get("USERDOMAIN", "").strip()
        if domain and "\\" not in account:
            account = f"{domain}\\{account}"
        task_xml = app_dir() / "startup-task.xml"
        arguments = subprocess.list2cmdline(command[1:])
        xml = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Sophos/Cyberoam Ethernet auto-login</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{xml_escape(account)}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{xml_escape(account)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec>
    <Command>{xml_escape(command[0])}</Command>
    <Arguments>{xml_escape(arguments)}</Arguments>
    <WorkingDirectory>{xml_escape(str(Path(__file__).resolve().parent))}</WorkingDirectory>
  </Exec></Actions>
</Task>
'''
        task_xml.write_text(xml, encoding="utf-16")
        try:
            subprocess.run(
                ["schtasks", "/Create", "/TN", APP_NAME, "/XML", str(task_xml), "/F"],
                check=True, capture_output=True, text=True,
            )
        finally:
            task_xml.unlink(missing_ok=True)
        subprocess.run(["schtasks", "/Run", "/TN", APP_NAME], check=True, capture_output=True, text=True)
        return f"Windows startup task '{APP_NAME}' installed and started."

    if sys.platform == "darwin":
        target = Path.home() / "Library" / "LaunchAgents" / "com.local.wifi-agent.plist"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "Label": "com.local.wifi-agent",
            "ProgramArguments": command,
            "RunAtLoad": True,
            "KeepAlive": True,
            "StandardOutPath": str(LOG_PATH),
            "StandardErrorPath": str(LOG_PATH),
        }
        with target.open("wb") as handle:
            plistlib.dump(payload, handle)
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", domain, str(target)], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", domain, str(target)], check=True, capture_output=True, text=True)
        return f"macOS LaunchAgent installed at {target} and started."

    target = Path.home() / ".config" / "systemd" / "user" / "wifi-agent.service"
    target.parent.mkdir(parents=True, exist_ok=True)
    quoted_command = " ".join(_systemd_quote(part) for part in command)
    target.write_text(
        "[Unit]\n"
        "Description=WiFi Agent captive-portal automation\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        f"ExecStart={quoted_command}\n"
        "Restart=on-failure\n"
        "RestartSec=10\n\n"
        "[Install]\n"
        "WantedBy=default.target\n",
        encoding="utf-8",
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True, text=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", target.name], check=True, capture_output=True, text=True)
    return f"Linux systemd user service installed at {target} and started."


def _systemd_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def uninstall_startup() -> str:
    if sys.platform == "win32":
        subprocess.run(["schtasks", "/Delete", "/TN", APP_NAME, "/F"], check=True, capture_output=True, text=True)
        return f"Windows startup task '{APP_NAME}' removed. Saved settings were kept."
    if sys.platform == "darwin":
        target = Path.home() / "Library" / "LaunchAgents" / "com.local.wifi-agent.plist"
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(target)], capture_output=True)
        if target.exists():
            target.unlink()
        return "macOS LaunchAgent removed. Saved settings were kept."
    target = Path.home() / ".config" / "systemd" / "user" / "wifi-agent.service"
    subprocess.run(["systemctl", "--user", "disable", "--now", target.name], capture_output=True)
    if target.exists():
        target.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    return "Linux systemd user service removed. Saved settings were kept."


def show_setup_ui() -> int:
    ensure_dependencies()
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        print("Tkinter is not installed. On Debian/Ubuntu, install python3-tk, then retry.", file=sys.stderr)
        return 2

    config = load_config()
    root = tk.Tk()
    root.title("Cyberoam Auto Login")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=18)
    frame.grid()

    username = tk.StringVar(value=str(config["username"]))
    password = tk.StringVar()
    host = tk.StringVar(value=str(config["portal_host"]))
    port = tk.StringVar(value=str(config["portal_port"]))
    interval = tk.StringVar(value=str(config["check_interval_seconds"]))
    interface = tk.StringVar(value=str(config.get("network_interface", "auto")))
    insecure = tk.BooleanVar(value=bool(config.get("allow_self_signed_portal", True)))
    status = tk.StringVar(value="Password is stored only in your operating system's credential vault.")

    fields = (
        ("Username / roll number", username, False),
        ("Password", password, True),
        ("Portal host", host, False),
        ("Portal port", port, False),
        ("Check every (seconds)", interval, False),
    )
    for row, (label, variable, secret) in enumerate(fields):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
        ttk.Entry(frame, textvariable=variable, show="*" if secret else "", width=34).grid(row=row, column=1, sticky="ew", pady=4)

    ttk.Label(frame, text="Wired interface").grid(row=5, column=0, sticky="w", pady=4, padx=(0, 12))
    choices = ["auto"] + active_interfaces()
    if interface.get() not in choices:
        choices.append(interface.get())
    ttk.Combobox(frame, textvariable=interface, values=choices, state="readonly", width=31).grid(row=5, column=1, sticky="ew", pady=4)
    ttk.Checkbutton(frame, text="Allow the portal's self-signed HTTPS certificate", variable=insecure).grid(
        row=6, column=0, columnspan=2, sticky="w", pady=(8, 4)
    )
    ttk.Label(frame, textvariable=status, wraplength=430).grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 8))

    def save() -> bool:
        new_username = username.get().strip()
        new_password = password.get()
        if not new_username:
            messagebox.showerror("Missing username", "Enter your portal username or roll number.")
            return False
        if not new_password and new_username != config.get("username"):
            messagebox.showerror("Missing password", "Enter the password for this username.")
            return False
        try:
            new_port = int(port.get())
            new_interval = max(15, int(interval.get()))
            if not 1 <= new_port <= 65535:
                raise ValueError("Portal port must be between 1 and 65535.")
            if new_password:
                store_credentials(new_username, new_password, str(config.get("username", "")))
            elif not keyring.get_password(KEYRING_SERVICE, new_username):
                raise ValueError("Enter a password; none is currently saved for this username.")
            config.update({
                "username": new_username,
                "portal_host": host.get().strip(),
                "portal_port": new_port,
                "check_interval_seconds": new_interval,
                "network_interface": interface.get(),
                "allow_self_signed_portal": insecure.get(),
            })
            if not config["portal_host"]:
                raise ValueError("Portal host cannot be empty.")
            save_config(config)
            password.set("")
            status.set(f"Settings saved to {CONFIG_PATH}. The password is in the OS vault.")
            return True
        except (ValueError, RuntimeError, KeyringError) as exc:
            messagebox.showerror("Could not save", str(exc))
            return False

    def install() -> None:
        if not save():
            return
        try:
            message = install_startup()
            status.set(message)
            messagebox.showinfo("Service installed", message)
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
            messagebox.showerror("Installation failed", detail)

    def test_now() -> None:
        if not save():
            return
        status.set("Checking Ethernet, portal port, and internet…")

        def worker() -> None:
            try:
                wired = wired_interfaces(str(config["network_interface"]))
                open_ = portal_port_open(str(config["portal_host"]), int(config["portal_port"])) if wired else False
                online = internet_available() if wired else False
                summary = (
                    f"Ethernet: {'connected (' + ', '.join(wired) + ')' if wired else 'not connected'} | "
                    f"Portal port: {'open' if open_ else 'closed/unreachable'} | "
                    f"Internet: {'available' if online else 'unavailable'}"
                )
                root.after(0, lambda: status.set(summary))
            except Exception as exc:
                root.after(0, lambda error=str(exc): messagebox.showerror("Check failed", error))

        threading.Thread(target=worker, daemon=True).start()

    buttons = ttk.Frame(frame)
    buttons.grid(row=8, column=0, columnspan=2, sticky="e", pady=(8, 0))
    ttk.Button(buttons, text="Test now", command=test_now).pack(side="left", padx=4)
    ttk.Button(buttons, text="Save", command=save).pack(side="left", padx=4)
    ttk.Button(buttons, text="Save & install service", command=install).pack(side="left", padx=4)

    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("setup", help="open the credential/settings window")
    run_parser = subparsers.add_parser("run", help="run the background monitor")
    run_parser.add_argument("--once", action="store_true", help="perform one status/login cycle")
    subparsers.add_parser("install", help="install and start the per-user startup service")
    subparsers.add_parser("uninstall", help="remove the startup service (keep settings)")
    subparsers.add_parser("status", help="print the most recent service log")
    args = parser.parse_args()

    try:
        if args.command in (None, "setup"):
            return show_setup_ui()
        if args.command == "run":
            return run_agent(args.once)
        if args.command == "install":
            print(install_startup())
            return 0
        if args.command == "uninstall":
            print(uninstall_startup())
            return 0
        if args.command == "status":
            if LOG_PATH.exists():
                print("".join(LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines(True)[-30:]), end="")
                return 0
            print(f"No log exists yet at {LOG_PATH}")
            return 1
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
        print(f"Error: {detail}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
