"""Desktop entry point used by the macOS and Windows standalone apps."""
import ctypes
import os
import sys
import threading
import traceback

import webview
from werkzeug.serving import make_server

from app import app
import config


def show_startup_error(error):
    """Make a Windows startup problem visible instead of silently closing."""
    details = traceback.format_exc()
    log_path = os.path.join(config.DATA_DIR, 'startup-error.log')
    try:
        with open(log_path, 'w', encoding='utf-8') as log_file:
            log_file.write(details)
    except OSError:
        pass

    message = (
        'BWIH 调度系统无法启动。\n\n'
        f'原因：{error}\n\n'
        f'详细日志：{log_path}\n\n'
        '请确认已安装 Microsoft Edge WebView2 Runtime，然后重新打开。'
    )
    if sys.platform == 'win32':
        ctypes.windll.user32.MessageBoxW(None, message, 'BWIH 调度系统', 0x10)
    else:
        print(message, file=sys.stderr)


if __name__ == '__main__':
    try:
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
    except Exception as error:
        show_startup_error(error)
