"""The release build's pure parts: what ships, the path file patch and the
launchers. The full build (a download and a pip install) runs in the release
workflow, not here."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _module():
    spec = importlib.util.spec_from_file_location("build_release", ROOT / "scripts" / "build_release.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_files_to_ship_is_code_and_frontend_only():
    rel = {str(r).replace("\\", "/") for _, r in _module().files_to_ship()}
    assert {"app.py", "ariadne/__init__.py", "ariadne/services/index.py", "requirements.txt", "README.md"} <= rel
    assert any(r.startswith("web/dist/assets/") for r in rel)
    assert "web/dist/index.html" in rel
    for banned in ("organizer.db", "settings.json", "history.json", "ariadne.key", "accounts.json"):
        assert banned not in rel
    assert not any("__pycache__" in r or r.endswith(".pyc") for r in rel)
    assert not any(r.startswith("tests/") or r.startswith("web/src/") or r.startswith("web/node_modules/") for r in rel)


def test_patch_pth_enables_site_and_adds_the_app(tmp_path):
    pth = tmp_path / "python312._pth"
    pth.write_text("python312.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n", encoding="utf-8")
    out = _module().patch_pth(pth)
    assert out[0] == "python312.zip" and out[1] == "..\\app"
    assert "import site" in out and "#import site" not in out
    # idempotent
    assert _module().patch_pth(pth) == out


def test_launchers_point_python_at_the_app_and_the_data_folder():
    mod = _module()
    plain, tray = mod.launcher_text(False), mod.launcher_text(True)
    for text in (plain, tray):
        assert 'python\\python.exe" "%~dp0app\\app.py"' in text and '--app-dir "%~dp0data"' in text
        assert "\r\n" in text
    assert "--tray --no-browser" in tray and "--tray" not in plain
    # the zip is named after it, so it has to be a plain version number
    assert re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", mod.version())
