#!/usr/bin/env python3
"""One-command laptop demo: the whole Allied Awaaz system on one laptop, no hardware.

Starts, on this machine:
  * a throwaway Mosquitto broker with the repo ACL and fresh passwords (if mosquitto is installed;
    otherwise the terminal uses its signed HTTPS polling fallback)
  * the backend on :8000, or the next free port (SQLite, demo data seeded, simulated gateway)
  * the laptop terminal on http://127.0.0.1:8090 (screen, keypad, mic, speakers)
  * optionally the bank console on :3000 (--console)
and opens the terminal in the browser. Ctrl+C stops everything.

    python scripts/laptop_demo.py
    python scripts/laptop_demo.py --console          # also the staff console (demo step 6)
    python scripts/laptop_demo.py --api http://localhost:8000 --no-backend   # use a running stack

The payer page link in each QR uses this laptop's LAN IP, so a phone on the same Wi-Fi can scan
and pay. Allow Python through the Windows firewall if asked.
"""
from __future__ import annotations

import argparse
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
WIN = os.name == "nt"


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent; picks the outbound interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def find_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if WIN:
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
            candidate = Path(base) / "mosquitto" / f"{name}.exe"
            if base and candidate.is_file():
                return str(candidate)
    return None


def wait_http(url: str, seconds: int) -> bool:
    for _ in range(seconds * 2):
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


class Stack:
    def __init__(self) -> None:
        self.procs: list[tuple[str, subprocess.Popen]] = []
        self.work = Path(tempfile.mkdtemp(prefix="awaaz-laptop-"))

    def start(self, name: str, cmd: list[str], env: dict | None = None, cwd: Path | None = None) -> subprocess.Popen:
        log = open(self.work / f"{name}.log", "w")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if WIN else 0
        p = subprocess.Popen(cmd, cwd=cwd, env={**os.environ, **(env or {})}, stdout=log, stderr=subprocess.STDOUT,
                             creationflags=flags)
        self.procs.append((name, p))
        return p

    def stop(self) -> None:
        for name, p in reversed(self.procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()

    def tail(self, name: str, lines: int = 25) -> str:
        path = self.work / f"{name}.log"
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:]) if path.exists() else ""


def start_broker(stack: Stack, port: int, backend_pw: str, device_pw: str) -> bool:
    mosq, mpasswd = find_tool("mosquitto"), find_tool("mosquitto_passwd")
    if not (mosq and mpasswd):
        return False
    d = stack.work / "mq"
    d.mkdir()
    shutil.copy(ROOT / "infra" / "mosquitto" / "acl", d / "acl")
    pw = d / "passwd"
    subprocess.run([mpasswd, "-b", "-c", str(pw), "awaaz-backend", backend_pw], check=True, capture_output=True)
    subprocess.run([mpasswd, "-b", str(pw), "awz-demo-001", device_pw], check=True, capture_output=True)
    conf = d / "mosquitto.conf"
    conf.write_text(f"listener {port} 127.0.0.1\nallow_anonymous false\npassword_file {pw.as_posix()}\n"
                    f"acl_file {(d / 'acl').as_posix()}\npersistence false\n")
    stack.start("broker", [mosq, "-c", str(conf)])
    time.sleep(1)
    return not port_free(port)


def ensure_console_build(api: str) -> None:
    console = ROOT / "console"
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("--console needs Node.js 20+ (npm not found)")
    marker = console / ".next" / "awaaz-api-base"
    if marker.exists() and marker.read_text().strip() == api:
        return
    print("  building console for", api, "(about a minute)...")
    if not (console / "node_modules").is_dir():
        subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=console, check=True, shell=WIN)
    env = {**os.environ, "NEXT_PUBLIC_API_BASE": api, "NEXT_TELEMETRY_DISABLED": "1"}
    subprocess.run([npm, "run", "-s", "build"], cwd=console, env=env, check=True, shell=WIN)
    marker.write_text(api)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", help="backend URL (default http://localhost:<port>)")
    ap.add_argument("--port", type=int, default=8000, help="backend port; the next free one is used if busy")
    ap.add_argument("--no-backend", action="store_true", help="use an already running backend (e.g. docker compose)")
    ap.add_argument("--console", action="store_true", help="also start the bank console on :3000")
    ap.add_argument("--terminal-port", type=int, default=8090)
    ap.add_argument("--mqtt-port", type=int, default=1884, help="port for the throwaway broker")
    ap.add_argument("--no-mqtt", action="store_true", help="skip MQTT; terminal uses signed HTTPS polling")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    stack = Stack()
    ip = lan_ip()
    device_secret = os.getenv("AWAAZ_DEMO_DEVICE_SECRET", "dev-device-secret-001")
    backend_pw, device_pw = secrets.token_urlsafe(12), secrets.token_urlsafe(12)
    mqtt = False

    def shutdown(*_):
        print("\nStopping...")
        stack.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    print("Allied Awaaz laptop demo")
    try:
        if not a.no_backend:
            if not port_free(a.port):
                busy = a.port
                a.port = next(p for p in range(a.port + 1, a.port + 50) if port_free(p))
                print(f"  note      port {busy} is in use by another program; using {a.port}")
            a.api = a.api or f"http://localhost:{a.port}"
            if not port_free(a.terminal_port):
                raise SystemExit(f"port {a.terminal_port} is busy; pass --terminal-port")
            if not a.no_mqtt:
                mqtt = start_broker(stack, a.mqtt_port, backend_pw, device_pw)
                print(f"  broker    {'127.0.0.1:%d (verified MQTT)' % a.mqtt_port if mqtt else 'not found, using signed HTTPS polling'}")
            env = {
                "AWAAZ_DATABASE_URL": f"sqlite:///{(stack.work / 'awaaz.db').as_posix()}",
                "AWAAZ_PUBLIC_BASE_URL": f"http://{ip}:{a.port}",
                "AWAAZ_CORS_ORIGINS": "http://localhost:3000,http://127.0.0.1:3000",
                "AWAAZ_MQTT_ENABLED": "true" if mqtt else "false",
                "AWAAZ_MQTT_HOST": "127.0.0.1", "AWAAZ_MQTT_PORT": str(a.mqtt_port),
                "AWAAZ_MQTT_PASSWORD": backend_pw,
                "AWAAZ_DEMO_DEVICE_SECRET": device_secret,
            }
            stack.start("backend", [PY, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(a.port)],
                        env, cwd=ROOT / "backend")
            if not wait_http(a.api + "/healthz", 90):
                print(stack.tail("backend"))
                raise SystemExit("backend did not start")
            print(f"  backend   {a.api}  (payer links use http://{ip}:{a.port})")
        else:
            a.api = a.api or f"http://localhost:{a.port}"
            if not wait_http(a.api + "/healthz", 10):
                raise SystemExit(f"no backend at {a.api}")

        term_env = {"AWAAZ_API": a.api, "AWAAZ_TERMINAL_PORT": str(a.terminal_port),
                    "AWAAZ_DEMO_DEVICE_SECRET": device_secret}
        if mqtt:
            term_env |= {"AWAAZ_MQTT_HOST": "127.0.0.1", "AWAAZ_MQTT_PORT": str(a.mqtt_port),
                         "AWAAZ_DEVICE_MQTT_PASSWORD": device_pw}
        stack.start("terminal", [PY, str(ROOT / "tools" / "laptop_terminal" / "server.py")], term_env)
        term_url = f"http://127.0.0.1:{a.terminal_port}"
        if not wait_http(term_url + "/api/state", 30):
            print(stack.tail("terminal"))
            raise SystemExit("laptop terminal did not start")
        print(f"  terminal  {term_url}")

        if a.console:
            ensure_console_build(a.api)
            npx = shutil.which("npx")
            stack.start("console", [npx, "next", "start", "-p", "3000"], {"NEXT_TELEMETRY_DISABLED": "1"},
                        cwd=ROOT / "console")
            if wait_http("http://localhost:3000/login", 60):
                print("  console   http://localhost:3000  (tokens: dev-rm-token, dev-sup-token)")
            else:
                print("  console   failed to start:\n" + stack.tail("console"))

        print(f"\nLogs: {stack.work}\nReady. Press Ctrl+C to stop.")
        if not a.no_browser:
            webbrowser.open(term_url)
        while True:
            for name, p in stack.procs:
                if p.poll() is not None:
                    print(f"\n{name} exited unexpectedly:\n{stack.tail(name)}")
                    shutdown()
            time.sleep(1)
    except SystemExit:
        stack.stop()
        raise
    except Exception:
        stack.stop()
        raise


if __name__ == "__main__":
    main()
