"""Launcher for the local web version of TXT Translator."""
import os
import threading
import time
import webbrowser

from app import app

HOST = os.getenv("TXT_TRANSLATOR_HOST", "127.0.0.1")
PORT = int(os.getenv("TXT_TRANSLATOR_PORT", "5000"))


def open_browser():
    time.sleep(0.8)
    webbrowser.open(f"http://{HOST}:{PORT}/")


if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False, threaded=True)
