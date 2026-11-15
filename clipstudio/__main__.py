"""`python -m clipstudio` — start the local server (127.0.0.1 only) and open the browser."""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import webbrowser


def _free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="clipstudio", description="Clip Studio local server")
    ap.add_argument("--port", type=int, default=int(os.environ.get("CLIPSTUDIO_PORT", 8765)))
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser")
    args = ap.parse_args()

    from .media import have_ffmpeg, ffmpeg_missing_message
    if not have_ffmpeg():
        print("\n  !! " + ffmpeg_missing_message() + "\n  (Clip Studio will start, but can't make clips until ffmpeg is installed.)\n")

    url = f"http://127.0.0.1:{args.port}"
    if not _free(args.port):
        print(f"Clip Studio already seems to be running at {url}")
        if not args.no_browser:
            webbrowser.open(url)
        sys.exit(0)

    import uvicorn
    from .app import app
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"\n  Clip Studio is running at {url}  (close this window or press Ctrl+C to stop)\n")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
