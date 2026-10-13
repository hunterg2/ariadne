"""Tray mode: keep the server alive with no console window, with a tray
icon to open the app or quit. Handy when phones on the network use it.

pystray is optional. Without it, ``--tray`` falls back to the normal run and
says how to install it.
"""

import os
import threading
import webbrowser

from ariadne import config


def available():
    try:
        import pystray  # noqa: F401
        return True
    except ImportError:
        return False


def run(app, port, open_browser, host=config.DEFAULT_HOST):
    """Serve Flask on a background thread and block on the tray loop. Quit
    from the menu ends the process (the server thread is a daemon)."""
    import pystray
    from PIL import Image

    url = f"http://127.0.0.1:{port}"

    def serve():
        app.run(debug=False, threaded=True, host=host, port=port, use_reloader=False)

    threading.Thread(target=serve, daemon=True, name="flask").start()
    if open_browser:
        webbrowser.open(url)

    icon_file = config.ROOT_DIR / "icon.png"
    image = Image.open(icon_file) if icon_file.exists() else Image.new("RGB", (64, 64), (203, 166, 247))

    def on_open(icon, item):
        webbrowser.open(url)

    def on_quit(icon, item):
        icon.visible = False
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Ariadne", on_open, default=True),
        pystray.MenuItem(f"Running on port {port}", None, enabled=False),
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("ariadne", image, "Ariadne", menu)
    icon.run()
    os._exit(0)
