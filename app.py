"""Ariadne launcher.

Run it with ``python app.py`` (or start.bat on Windows). It listens on
http://127.0.0.1:5000 by default and opens a browser tab once the server is
up. Options:

    --port N        listen on another port (--port=N also works)
    --host ADDR     listen on another address; --lan is short for 0.0.0.0, so
                    phones and laptops on the same network can open it. Other
                    devices are asked for the PIN set under Settings, Other
                    devices; until one is set they are turned away.
    --no-browser    do not open a browser tab (same as ORGANIZER_NO_BROWSER=1)
    --reload        restart whenever a source file changes (development)
    --tray          keep running from a tray icon (needs pystray), with no
                    console window
    --app-dir DIR   keep the database, settings, caches and key file in DIR
                    instead of beside this file (a second library, a
                    portable copy, or the browser tests)

Everything the app writes lives beside this file: organizer.db, cache/,
backups/, settings.json, history.json and projects.json.
What it reports goes to ariadne.log there as well (1 MB, three older
copies kept), which is the place to look when a scheduled post failed.
Image folders are only ever changed by explicit actions taken in the UI
(trash, move, export, edit).

The application itself lives in the ``ariadne`` package; this file only
decides how to start it.
"""

import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

from ariadne import config, create_app


def port_is_open(port, host="127.0.0.1", timeout=0.4):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def is_our_app(port):
    """Distinguish our own already-running copy from some unrelated service."""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/stats", timeout=1.5) as res:
            return "images_indexed" in json.loads(res.read())
    except (OSError, ValueError):
        return False


def find_free_port(start, tries=20):
    for port in range(start, start + tries):
        if not port_is_open(port):
            return port
    return None


def open_browser_when_ready(url, port, timeout=15):
    """Wait until the server is actually listening, then open the browser.
    Polling beats a fixed sleep: no blank tab if startup is slow."""
    def wait():
        deadline = time.time() + timeout
        while time.time() < deadline:
            if port_is_open(port):
                break
            time.sleep(0.15)
        try:
            webbrowser.open(url)
        except (webbrowser.Error, OSError):
            pass   # headless or no browser configured; the URL is printed anyway

    threading.Thread(target=wait, daemon=True).start()


def parse_args(argv):
    opts = {"port": config.DEFAULT_PORT, "host": config.DEFAULT_HOST,
            "launch": True, "reload": False, "tray": False, "app_dir": None}
    for i, arg in enumerate(argv):
        if arg in ("--no-browser", "-n"):
            opts["launch"] = False
        elif arg in ("--reload", "--dev", "-r"):
            opts["reload"] = True
        elif arg == "--tray":
            opts["tray"] = True
        elif arg == "--lan":
            opts["host"] = "0.0.0.0"
        elif arg == "--app-dir" and i + 1 < len(argv):
            opts["app_dir"] = argv[i + 1].strip() or None
        elif arg.startswith("--app-dir="):
            opts["app_dir"] = arg.split("=", 1)[1].strip() or None
        elif arg == "--host" and i + 1 < len(argv):
            opts["host"] = argv[i + 1].strip() or config.DEFAULT_HOST
        elif arg.startswith("--host="):
            opts["host"] = arg.split("=", 1)[1].strip() or config.DEFAULT_HOST
        elif arg == "--port" and i + 1 < len(argv):
            try:
                opts["port"] = int(argv[i + 1])
            except ValueError:
                pass
        elif arg.startswith("--port="):
            try:
                opts["port"] = int(arg.split("=", 1)[1])
            except ValueError:
                pass
    if config.env_flag(config.NO_BROWSER_ENV):
        opts["launch"] = False
    return opts


def start_workers():
    from ariadne.services import index, updates
    index.request_all()
    updates.check_soon()        # once a day at most; Settings shows the answer


def main(argv=None):
    opts = parse_args(sys.argv[1:] if argv is None else argv)
    port, host = opts["port"], opts["host"]
    launch, reload_on, tray_on = opts["launch"], opts["reload"], opts["tray"]
    config.BIND_HOST = host

    # With --reload the watcher runs the module twice: once to watch, once to
    # serve. Only the first pass should greet you, open a browser or take a
    # backup, or you get two of each every time you save a file.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        port = int(os.environ.get(config.PORT_ENV, port))
        config.BIND_PORT = port
        app = create_app(app_dir=opts["app_dir"])
        start_workers()
        app.run(debug=False, threaded=True, host=host, port=port, use_reloader=True)
        return

    # Running it twice should just bring up the window, not fail with a stack
    # trace about the port being taken.
    if port_is_open(port):
        if is_our_app(port):
            print(f"{config.APP_NAME} is already running on http://127.0.0.1:{port}")
            if launch:
                webbrowser.open(f"http://127.0.0.1:{port}")
            return
        free = find_free_port(port + 1)
        if free is None:
            sys.exit(f"Port {port} is busy and nothing nearby is free. "
                     f"Try: python app.py --port 8080")
        print(f"Port {port} is in use by something else, switching to {free}.")
        port = free

    config.BIND_PORT = port
    app = create_app(app_dir=opts["app_dir"])
    from ariadne.db import backup_db
    from ariadne.services import system
    start_workers()
    if opts["app_dir"]:
        print(f"[data] library and settings in {config.APP_DIR}")
    saved = backup_db()
    if saved:
        print(f"[backup] library copied to {saved.name} (last {config.BACKUPS_KEPT} kept)")

    url = f"http://127.0.0.1:{port}"
    print(f"{config.APP_NAME} running on {url}")
    lan = system.lan_urls()
    for address in lan:
        print(f"  also reachable on your network at {address}")
    if lan:
        from ariadne.services import auth
        if auth.has_pin():
            print("  other devices are asked for the PIN (Settings, Other devices).")
        else:
            print("  no PIN is set yet, so other devices are turned away until you set one "
                  "(Settings, Other devices).")
    if reload_on:
        print("Watching for changes: edit a file and it restarts by itself.")

    if tray_on:
        from ariadne import tray
        if tray.available():
            print("Tray mode: use the tray icon to open the app or quit.")
            tray.run(app, port, launch, host)
            return
        print("Tray mode needs the pystray package (py -m pip install pystray). "
              "Running normally instead.")

    if launch:
        print("Opening your browser... (use --no-browser to stop this)")
        open_browser_when_ready(url, port)

    os.environ[config.PORT_ENV] = str(port)
    app.run(debug=False, threaded=True, host=host, port=port, use_reloader=reload_on)


if __name__ == "__main__":
    main()
