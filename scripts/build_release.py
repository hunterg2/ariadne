"""Build a Windows zip that runs with nothing installed.

    py -3 scripts/build_release.py [--python 3.12.7] [--out build] [--no-optional] [--skip-pip]

The zip holds one folder:

    Ariadne/
      Ariadne.bat             starts it and opens the browser
      Ariadne (tray).bat      starts it in the tray, no window
      app/                    the code and the built frontend
      python/                 the embeddable Python with the requirements
      data/                   made on first run: database, settings, caches

The launchers pass --app-dir data, so an upgrade is replacing app/ and
python/ and nothing else. Needs a network connection to fetch the
embeddable Python and the packages; both are cached under build/cache.
The packages are held to the versions in requirements.lock (written by
scripts/lock_requirements.py), so a rebuild of the same tag gets the same
packages and a newer one is a deliberate commit.
"""

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EMBED_URL = "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
OPTIONAL = ["pystray", "send2trash"]

# what ships: the code, the built frontend, the icons and the readme. Runtime
# data (database, settings, caches, keys) never does, so the list is explicit.
SHIP_FILES = ["app.py", "metadata.py", "tagger.py", "requirements.txt", "README.md",
              "icon.ico", "icon.png", "scripts/make_sample_library.py"]
SHIP_DIRS = ["ariadne", "web/dist"]
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".tmp")


def version():
    ns = {}
    for line in (ROOT / "ariadne" / "__init__.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            exec(line, ns)
    return ns.get("__version__", "0.0.0")


def files_to_ship(root=ROOT):
    """(source, relative destination) for everything that goes into app/."""
    out = []
    for name in SHIP_FILES:
        src = Path(root) / name
        if src.is_file():
            out.append((src, Path(name)))
    for name in SHIP_DIRS:
        base = Path(root) / name
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if any(part in SKIP_DIRS for part in rel.parts) or path.suffix in SKIP_SUFFIXES:
                continue
            out.append((path, rel))
    return out


def pip_args(with_optional=True, root=ROOT):
    """What pip installs into the embedded Python: the requirements, the
    optional packages unless told otherwise, held to requirements.lock as
    a constraints file when it exists (a constraint pins without
    installing, so --no-optional still leaves pystray out)."""
    root = Path(root)
    args = ["-r", str(root / "requirements.txt")] + (list(OPTIONAL) if with_optional else [])
    lock = root / "requirements.lock"
    if lock.is_file():
        args += ["-c", str(lock)]
    return args


def patch_pth(pth_path, app_rel="..\\app"):
    """The embeddable Python ignores site-packages until ``import site`` is
    uncommented; the app folder is added so the code imports wherever the
    launcher is run from."""
    lines = [line.rstrip("\r\n") for line in Path(pth_path).read_text(encoding="utf-8").splitlines()]
    out = []
    for line in lines:
        if line.strip() == "#import site":
            line = "import site"
        out.append(line)
    if app_rel not in out:
        out.insert(1 if out else 0, app_rel)
    if "import site" not in out:
        out.append("import site")
    Path(pth_path).write_text("\n".join(out) + "\n", encoding="utf-8")
    return out


def launcher_text(tray=False):
    args = "--tray --no-browser " if tray else ""
    return "\r\n".join([
        "@echo off",
        "title Ariadne",
        'cd /d "%~dp0"',
        "rem Everything the app writes goes into the data folder beside this file.",
        f'"%~dp0python\\python.exe" "%~dp0app\\app.py" {args}--app-dir "%~dp0data" %*',
        "if errorlevel 1 (",
        "  echo.",
        "  echo   It stopped with an error. The lines above say why.",
        "  echo.",
        "  pause",
        ")",
        "",
    ])


def fetch(url, dest):
    dest = Path(dest)
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[release] fetching {url}")
    with urllib.request.urlopen(url, timeout=120) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)
    return dest


def build(out_dir=ROOT / "build", python_version="3.12.7", with_optional=True, skip_pip=False):
    out_dir = Path(out_dir)
    cache = out_dir / "cache"
    stage = out_dir / "Ariadne"
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "app").mkdir(parents=True)

    for src, rel in files_to_ship():
        dest = stage / "app" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    if not (stage / "app" / "web" / "dist" / "index.html").exists():
        sys.exit("web/dist is missing: run `npm run build` in web/ first.")

    embed = fetch(EMBED_URL.format(v=python_version), cache / f"python-{python_version}-embed-amd64.zip")
    with zipfile.ZipFile(embed) as z:
        z.extractall(stage / "python")
    pth = next((stage / "python").glob("python3*._pth"))
    patch_pth(pth)

    python = stage / "python" / "python.exe"
    if not skip_pip:
        get_pip = fetch(GET_PIP_URL, cache / "get-pip.py")
        subprocess.run([str(python), str(get_pip), "--no-warn-script-location", "-q"], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "--no-warn-script-location", "-q",
                        *pip_args(with_optional)], check=True)
        subprocess.run([str(python), "-c", "import flask, PIL"], check=True)

    (stage / "Ariadne.bat").write_text(launcher_text(False), encoding="ascii")
    (stage / "Ariadne (tray).bat").write_text(launcher_text(True), encoding="ascii")
    (stage / "data").mkdir(exist_ok=True)
    (stage / "data" / "README.txt").write_text(
        "Ariadne keeps its database, settings, caches and key file here.\n"
        "Back this folder up; replace app/ and python/ to upgrade.\n", encoding="utf-8")

    name = f"Ariadne-{version()}-win64"
    archive = shutil.make_archive(str(out_dir / name), "zip", root_dir=out_dir, base_dir="Ariadne")
    size = os.path.getsize(archive) / 1e6
    print(f"[release] {archive} ({size:.1f} MB)")
    return Path(archive)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the Windows zip.")
    ap.add_argument("--python", default="3.12.7", help="embeddable Python version")
    ap.add_argument("--out", default=str(ROOT / "build"))
    ap.add_argument("--no-optional", action="store_true", help="leave out pystray and send2trash")
    ap.add_argument("--skip-pip", action="store_true", help="no packages (a quick layout check)")
    args = ap.parse_args(argv)
    build(args.out, args.python, not args.no_optional, args.skip_pip)


if __name__ == "__main__":
    main()
