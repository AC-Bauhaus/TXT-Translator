"""Desktop shell for TXT Tradutor Offline."""
import base64
import socket
import threading
import time
from pathlib import Path

from app import app


class DesktopAPI:
    def save_file(self, filename, content_base64):
        import webview

        path = webview.windows[0].create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=Path(filename).name,
            file_types=(
                "Arquivos TXT (*.txt)",
                "Documentos PDF (*.pdf)",
                "Documentos Word (*.docx)",
                "Todos os arquivos (*.*)",
            ),
        )

        if not path:
            return {"success": False, "cancelled": True}

        if isinstance(path, (list, tuple)):
            path = path[0]

        try:
            content = base64.b64decode(content_base64, validate=True)
            Path(path).write_bytes(content)
            return {"success": True, "path": str(path)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run_server(port):
    app.run(
        host="127.0.0.1",
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


if __name__ == "__main__":
    port = free_port()

    threading.Thread(
        target=run_server,
        args=(port,),
        daemon=True,
    ).start()

    url = f"http://127.0.0.1:{port}"
    time.sleep(1)

    import webview

    webview.create_window(
        "TXT Translator",
        url,
        width=1200,
        height=820,
        min_size=(800, 600),
        js_api=DesktopAPI(),
    )

    webview.start(gui="qt")
