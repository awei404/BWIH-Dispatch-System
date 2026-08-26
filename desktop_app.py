"""Desktop entry point used by the macOS and Windows standalone apps."""
import threading

import webview
from werkzeug.serving import make_server

from app import app


if __name__ == '__main__':
    # Bind first, so the desktop window never opens before its local page is ready.
    server = make_server('127.0.0.1', 8080, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    webview.create_window(
        'BWIH 调度系统',
        'http://127.0.0.1:8080/',
        width=1440,
        height=900,
        min_size=(1100, 700),
    )
    webview.start()
