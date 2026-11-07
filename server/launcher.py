"""Double-click launcher for the downloadable Training Dashboard app.

On first run it asks for your Garmin sign-in in this window (your password is not
stored, only Garmin's login tokens). Then it starts the dashboard and opens it in
your browser. Keep this window open while you use the dashboard; close it to stop.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as server  # noqa: E402


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def has_tokens() -> bool:
    p = server.TOKENS
    return p.exists() and (p.is_file() or any(p.iterdir()))


def pause(msg: str = "Press Enter to close.") -> None:
    try:
        input(msg)
    except EOFError:
        pass


def main() -> None:
    print("Training Dashboard")
    print("==================")
    print(f"Your data folder: {server.DATA.parent if server.FROZEN else server.DATA}\n")

    if "--login" in sys.argv or not has_tokens():
        print("First, sign in to Garmin Connect. This happens once.")
        print("Your password is sent only to Garmin and is not saved.\n")
        try:
            server.interactive_login()
        except Exception as e:
            print(f"\nCouldn't sign in to Garmin: {e}")
            pause()
            sys.exit(1)
        print()

    port = int(os.getenv("T100_PORT", "8100"))
    url = f"http://127.0.0.1:{port}"
    if not port_free(port):
        print(f"The dashboard already seems to be running. Opening {url}")
        webbrowser.open(url)
        time.sleep(2)
        return

    def open_browser():
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    print(f"Dashboard running at {url}")
    print("Keep this window open while you use it. Close it to stop.\n")
    import logging

    logging.basicConfig(level=logging.WARNING)
    server.app.run(host="127.0.0.1", port=port, threaded=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:  # keep the window open so people can read the error
        print(f"\nSomething went wrong: {e}")
        pause()
        sys.exit(1)
