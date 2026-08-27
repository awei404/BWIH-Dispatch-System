"""Desktop entry point – keeps the local server separate from the app launcher."""
import json
import os
import subprocess
import sys
import socket
import time
import traceback
import urllib.request
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


def state_path():
    return os.path.join(data_dir(), 'server-state.json')


def server_url(port):
    return f'http://127.0.0.1:{port}/'


def server_is_ready(port):
    try:
        with urllib.request.urlopen(server_url(port), timeout=0.75) as response:
            return response.status < 500
    except Exception:
        return False


def read_running_port():
    try:
        with open(state_path(), 'r', encoding='utf-8') as state_file:
            port = int(json.load(state_file)['port'])
        return port if server_is_ready(port) else None
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def write_server_state(port):
    os.makedirs(data_dir(), exist_ok=True)
    with open(state_path(), 'w', encoding='utf-8') as state_file:
        json.dump({'port': port, 'pid': os.getpid()}, state_file)


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
    elif sys.platform == 'darwin':
        safe_msg = msg.replace('\\', '\\\\').replace('"', '\\"')
        subprocess.run(
            ['/usr/bin/osascript', '-e', f'display alert "BWIH 调度系统" message "{safe_msg}" as critical'],
            check=False,
        )
    else:
        print(msg, file=sys.stderr)


def run_server():
    from werkzeug.serving import make_server
    from app import app

    port = find_free_port(8080)
    server = make_server('127.0.0.1', port, app, threaded=True)
    write_server_state(port)
    server.serve_forever()


def launch_server():
    os.makedirs(data_dir(), exist_ok=True)
    log_path = os.path.join(data_dir(), 'app.log')

    with open(log_path, 'a', encoding='utf-8') as log_file:
        options = {
            'stdin': subprocess.DEVNULL,
            'stdout': log_file,
            'stderr': subprocess.STDOUT,
            'cwd': data_dir(),
        }
        if sys.platform == 'win32':
            options['creationflags'] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            options['start_new_session'] = True

        subprocess.Popen([sys.executable, '--server'], **options)

    for _ in range(100):
        port = read_running_port()
        if port:
            webbrowser.open(server_url(port))
            return
        time.sleep(0.1)

    raise RuntimeError(f'后台服务未能在 10 秒内启动，请查看 {log_path}')


def main():
    if '--server' in sys.argv:
        run_server()
        return

    running_port = read_running_port()
    if running_port:
        webbrowser.open(server_url(running_port))
        return

    launch_server()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        show_error(e)
