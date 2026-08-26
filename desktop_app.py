"""Desktop entry point used by the macOS and Windows standalone apps."""
import ctypes
import os
import sys
import threading
import traceback


def startup_data_dir():
    """Return a safe log location even if the application itself cannot import."""
    if sys.platform == 'win32':
        base_dir = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    elif sys.platform == 'darwin':
        base_dir = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    else:
        base_dir = os.path.expanduser('~')
    return os.path.join(base_dir, 'BWIH Dispatch')


def show_startup_error(error):
    """Make a Windows startup problem visible instead of silently closing."""
    details = traceback.format_exc()
    log_dir = startup_data_dir()
    log_path = os.path.join(log_dir, 'startup-error.log')
    try:
        os.makedirs(log_dir, exist_ok=True)
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


def main():
    """Load optional desktop dependencies inside the error boundary."""
    import webview
    from werkzeug.serving import make_server
    from app import app

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


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        show_startup_error(error)
