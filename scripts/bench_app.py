"""Time the app the way a user feels it: a cold start, and the routes each
screen calls, against a sample library of real files.

    py -3 scripts/bench_app.py                 # 20,000 sample images
    py -3 scripts/bench_app.py 5000            # smaller
    py -3 scripts/bench_app.py 20000 --keep    # keep the library for a rerun

The first run makes the library under the OS temp folder (three folders of
small PNGs from ``make_sample_library.py``), indexes it with thumbnails and
reports how long that took; ``--keep`` leaves it there so later runs skip
that. Every route is called through Flask's test client, warmed once, then
timed seven times (the median and the best are printed), so what you see
is the server's own cost without the browser. The cold start is the real
launcher, ``app.py``, timed from the process starting to the port
answering, three times. Compare runs before and after a change.
"""

import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PORT = 5057


def make_library(root, count):
    from scripts.make_sample_library import make_png
    folders = []
    shares = (count // 2, count // 4, count - count // 2 - count // 4)
    for name, n in zip("abc", shares, strict=True):
        folder = os.path.join(root, name)
        os.makedirs(folder, exist_ok=True)
        for i in range(n):
            make_png(os.path.join(folder, f"sample_{i:05d}.png"), i)
        folders.append(folder)
    return folders


def timed(label, fn, n=7, size_of=None):
    fn()
    times = []
    out = None
    for _ in range(n):
        t = time.perf_counter()
        out = fn()
        times.append((time.perf_counter() - t) * 1000)
    extra = f"  {size_of(out) / 1024:.0f} KB" if size_of else ""
    print(f"{statistics.median(times):9.1f} ms  (best {min(times):7.1f})  {label}{extra}")


def routes(app, folders):
    client = app.test_client()
    enc = urllib.parse.quote

    def get(url):
        r = client.get(url)
        assert r.status_code == 200, (url, r.status_code, r.data[:200])
        return r.data

    def post(url, body):
        r = client.post(url, data=json.dumps(body), content_type="application/json")
        assert r.status_code == 200, (url, r.status_code, r.data[:200])
        return r.data

    fa = enc(folders[0])
    print("\nthe app shell and the dashboard")
    timed("GET /", lambda: get("/"))
    timed("GET /api/settings", lambda: get("/api/settings"))
    timed("GET /api/history", lambda: get("/api/history"))
    timed("GET /api/history/check?counts=1", lambda: get("/api/history/check?counts=1"), n=3)
    timed("POST /api/images/summaries", lambda: post("/api/images/summaries", {"folders": folders, "recursive": []}))
    print("\nthe library")
    page = get("/api/images?limit=200")
    timed("GET /api/images (all, page 0)", lambda: get("/api/images?limit=200"), size_of=len)
    timed("GET /api/images (folder a, last page)", lambda: get(f"/api/images?folder={fa}&limit=200&offset=9800"))
    paths = [r["path"] for r in json.loads(page)["rows"]]
    timed("POST /api/images/scan (folder a, unchanged)", lambda: post("/api/images/scan", {"folder": folders[0]}), n=3)
    timed("GET /thumb x100 (cached)", lambda: [get("/thumb?path=" + enc(p)) for p in paths[:100]], n=3)
    print("\nsettings")
    timed("GET /api/cache/stats", lambda: get("/api/cache/stats"), n=3)
    timed("GET /api/system", lambda: get("/api/system"))


def cold_start(app_dir):
    """The real launcher, timed from the process starting to its "running
    on" line (printed just before the server binds) and to the first
    answer. The port is not polled with connects: Windows drops a connect
    to a port nothing listens on and, done a hundred times a second, that
    slowed the server's own acceptance by hundreds of milliseconds."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print("\ncold start (app.py)")
    for i in range(3):
        t0 = time.perf_counter()
        proc = subprocess.Popen([sys.executable, os.path.join(root, "app.py"), "--no-browser",
                                 "--port", str(PORT), "--app-dir", app_dir],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=root, text=True)
        banner = None
        for line in proc.stdout:
            if "running on" in line:
                banner = time.perf_counter() - t0
                break
        if banner is None:
            proc.kill()
            sys.exit("the server never came up")
        while True:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/stats", timeout=5):
                    break
            except OSError:
                time.sleep(0.005)
        t_api = time.perf_counter() - t0
        print(f"run {i + 1}: 'running on' at {banner * 1000:.0f} ms, first answer {t_api * 1000:.0f} ms")
        proc.terminate()
        proc.wait(10)
        time.sleep(1.0)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    count = int(args[0]) if args else 20_000
    keep = "--keep" in sys.argv
    base = os.path.join(tempfile.gettempdir(), f"ariadne-bench-{count}")
    lib = os.path.join(base, "lib")
    app_dir = os.path.join(base, "app")
    fresh = not os.path.isdir(app_dir)
    if fresh:
        os.makedirs(lib, exist_ok=True)
        t0 = time.perf_counter()
        folders = make_library(lib, count)
        print(f"made {count} sample images in {time.perf_counter() - t0:.0f} s")
    else:
        folders = [os.path.join(lib, n) for n in "abc"]
        print(f"reusing {base}")

    from ariadne import create_app, store
    from ariadne.services import index
    from ariadne.services.index import indexer

    indexer.stop()
    t0 = time.perf_counter()
    app = create_app(app_dir=app_dir)
    print(f"create_app: {(time.perf_counter() - t0) * 1000:.0f} ms")
    indexer.stop()
    if fresh:
        store.save_history([{"type": "folder", "path": f, "alias": "", "status": ""} for f in folders])
        with app.app_context():
            t0 = time.perf_counter()
            for f in folders:
                index.index_folder(f)
            dt = time.perf_counter() - t0
            print(f"first index with thumbnails: {dt:.0f} s ({dt / count * 1000:.1f} ms per file)")
    with app.app_context():
        routes(app, folders)
    from ariadne.db import retire_connections
    retire_connections()
    cold_start(app_dir)
    if not keep:
        shutil.rmtree(base, ignore_errors=True)
    else:
        print(f"\nkept {base}; rerun with the same count to reuse it")


if __name__ == "__main__":
    main()
