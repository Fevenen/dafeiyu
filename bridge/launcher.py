"""Portable launcher; all child interpreters use the active Python environment."""

import argparse
import json
import os
import subprocess
import csv
import io
import sys
import urllib.error
import urllib.request
from . import settings
from .net import urlopen
from .singleton import is_running, singleton


def health(url):
    try:
        with urlopen(url, timeout=2) as response:
            return json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return None


def spawn(args, cwd, name):
    settings.ensure_dirs()
    options = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    with (
        (settings.LOG_DIR / (name + ".out")).open("ab") as stdout,
        (settings.LOG_DIR / (name + ".err")).open("ab") as stderr,
    ):
        return subprocess.Popen(
            args, cwd=str(cwd), stdout=stdout, stderr=stderr, **options
        )


def desktop_running(target):
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq " + target.name, "/FO", "CSV", "/NH"],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return any(
        row and row[0].lower() == target.name.lower()
        for row in csv.reader(io.StringIO(result.stdout.decode(errors="replace")))
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pet-root")
    parser.add_argument("--workspace")
    parser.add_argument("--backend-only", action="store_true")
    args = parser.parse_args()
    root = settings.path("pet_root", settings.BRIDGE_ROOT.parent, args.pet_root)
    if not (root / "run_server.py").is_file():
        parser.error("pet_root must contain run_server.py")
    if not health(settings.PET_API + "/api/health"):
        spawn([sys.executable, str(root / "run_server.py")], root, "backend")
    if not args.backend_only:
        port = int(settings.get("kvmem_proxy_port", 18080))
        gateway = health("http://127.0.0.1:" + str(port) + "/health")
        if not gateway:
            spawn([sys.executable, "-m", "bridge.kvmem_proxy"], root, "gateway")
        elif gateway.get("service") != "pet-gateway":
            raise RuntimeError(
                "Gateway port is occupied by another/older service; stop it before restarting."
            )
        if not is_running("scheduler"):
            spawn([sys.executable, "-m", "bridge.reminder_daemon"], root, "scheduler")
        workspace = settings.path(
            "workspace", root.parent / "pet_workspace", args.workspace
        )
        if workspace.is_dir() and not is_running("watcher"):
            spawn(
                [sys.executable, "-m", "bridge.dsh_watch", "--dir", str(workspace)],
                root,
                "watcher",
            )
        client = settings.get("desktop_client")
        if client:
            target = settings.path("desktop_client", client)
            if target.is_file() and not desktop_running(target):
                spawn([str(target)], target.parent, "desktop")
        snow = settings.get("snowluma_launcher")
        if snow:
            target = settings.path("snowluma_launcher", snow)
            from urllib.parse import urlsplit
            import socket

            onebot = settings.CONFIG.get("onebot", {})
            address = urlsplit(
                str(
                    settings.get(
                        "onebot_url", onebot.get("url", "http://127.0.0.1:3000")
                    )
                )
            )
            try:
                with socket.create_connection(
                    (address.hostname, address.port or 80), timeout=1
                ):
                    qq_online = True
            except OSError:
                qq_online = False
            if target.is_file() and os.name == "nt" and not qq_online:
                spawn(["cmd.exe", "/c", str(target)], target.parent, "snowluma")
    print("Services requested. Logs:", settings.LOG_DIR)
    print("Health check:", sys.executable, "-m bridge.doctor --network")


if __name__ == "__main__":
    with singleton("launcher"):
        main()
