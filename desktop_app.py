"""Desktop entry point – starts Flask and opens the system browser."""
import os
import sys
import socket
import threading
import traceback
import webbrowser


def data_dir():
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    elif sys.platform == 'darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    else:
        base = os.path.expanduser('~')
    return os.path.join(base, 'BWIH Dispatch')


def find_free_port(preferred=8080):
    """Use the preferred port if available, otherwise pick a random free one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', preferred))
            return preferred
        except OSError:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]


def show_error(error):
    details = traceback.format_exc()
    log_path = os.path.join(data_dir(), 'startup-error.log')
    try:
        os.makedirs(data_dir(), exist_ok=True)
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(details)
    except OSError:
        pass

    msg = f'BWIH 调度系统无法启动。\n\n原因：{error}\n\n日志：{log_path}'
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, 'BWIH 调度系统', 0x10)
    else:
        print(msg, file=sys.stderr)


def main():
    from werkzeug.serving import make_server
    from app import app

    port = find_free_port(8080)
    server = make_server('127.0.0.1', port, app)
    url = f'http://127.0.0.1:{port}/'

    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f'BWIH 调度系统已启动：{url}')
    webbrowser.open(url)

    try:
        # Keep the main thread alive until user closes terminal / Ctrl-C.
        server_thread = threading.Event()
        server_thread.wait()
    except KeyboardInterrupt:
        print('\n已关闭。')
        server.shutdown()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        show_error(e)
