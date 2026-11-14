from __future__ import annotations

import argparse
import socket
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from .app import create_app
from .config import load_config


def _free_port(host: str, preferred: int) -> int:
    if preferred == 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            return int(sock.getsockname()[1])
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise SystemExit(f"No free port available on {host} (starting at {preferred})")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="patchbridge", description="PatchBridge local server")
    parser.add_argument("--data-dir", default=None, help="data directory, defaults to ./data")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="open the browser after starting")
    args = parser.parse_args(argv)

    config = load_config(args.data_dir)
    port = _free_port(args.host, args.port)
    url = f"http://{args.host}:{port}/"
    if args.open:
        def open_later() -> None:
            time.sleep(1.0)
            webbrowser.open(url)

        threading.Thread(target=open_later, daemon=True).start()
    print(f"PatchBridge: {url}")
    print(f"Data directory: {Path(config.data_dir)}")
    app = create_app(config)
    uvicorn.run(app, host=args.host, port=port, log_level="info")


if __name__ == "__main__":
    main()
