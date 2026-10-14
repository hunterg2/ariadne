"""Write requirements.lock: every package the release zip installs, pinned
to the version pip would pick today for the embedded Python (3.12 on
64-bit Windows), dependencies included.

    py -3 scripts/lock_requirements.py [--python 3.12]

build_release.py hands the file to pip as a constraints file, so a rebuild
of the same tag gets the same packages and a newer version is a deliberate
commit: run this, look at the diff, commit it with the version bump. Needs
pip and a network connection; the wheels are downloaded into a temp folder
only to learn their versions and thrown away.
"""

import argparse
import importlib.util
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "requirements.lock"
PLATFORM = "win_amd64"


def optional_packages():
    spec = importlib.util.spec_from_file_location("build_release", ROOT / "scripts" / "build_release.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.OPTIONAL)


def resolve(python_version, dest):
    """{name: version} for everything pip would install, from the wheel
    names it downloads for that interpreter and platform."""
    cmd = [sys.executable, "-m", "pip", "download", "-q", "--only-binary=:all:",
           "--python-version", python_version, "--platform", PLATFORM, "--implementation", "cp",
           "--dest", str(dest), "-r", str(ROOT / "requirements.txt"), *optional_packages()]
    subprocess.run(cmd, check=True)
    pins = {}
    for wheel in sorted(Path(dest).glob("*.whl")):
        name, version = wheel.name.split("-")[:2]
        pins[name.replace("_", "-").lower()] = version
    if not pins:
        sys.exit("pip downloaded nothing; is the network up?")
    return pins


def lock_text(pins, python_version):
    head = [
        "# The exact packages the release zip installs (scripts/build_release.py),",
        f"# resolved for Python {python_version} on {PLATFORM} on {time.strftime('%Y-%m-%d')}.",
        "# Regenerate with: py -3 scripts/lock_requirements.py",
        "# requirements.txt says what the app needs; this says what it shipped with.",
    ]
    return "\n".join(head + [f"{name}=={version}" for name, version in sorted(pins.items())]) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pin the release zip's packages.")
    ap.add_argument("--python", default="3.12", help="the embedded Python's version")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        pins = resolve(args.python, tmp)
    LOCK.write_text(lock_text(pins, args.python), encoding="utf-8")
    print(f"[lock] {len(pins)} packages written to {LOCK.name}")
    for name, version in sorted(pins.items()):
        print(f"  {name}=={version}")


if __name__ == "__main__":
    main()
