"""Put a launcher for Ariadne on your desktop. Run this once:

    python make_shortcut.py

It draws the icon (icon.png and icon.ico, next to this file), then makes a
desktop shortcut that points at the launcher sitting next to app.py: start.bat
on Windows, start.command on macOS, start.sh (via a .desktop entry) on Linux.
Because the shortcut points at the launcher rather than at a copy of anything,
you can keep editing the code and it keeps working. You only need to run this
again if you move the whole folder somewhere else.

    python make_shortcut.py --dev     shortcut that restarts on every save
    python make_shortcut.py --name X  call it something else

Needs Pillow for the icon; without it the shortcut gets the default icon.
"""

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


# --------------------------------------------------------------------------
# the icon
# --------------------------------------------------------------------------

def draw_icon(size):
    """A stack of photos, drawn large and scaled down so it stays legible at
    the 16px Windows uses in the taskbar."""
    from PIL import Image, ImageDraw

    big = size * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = big / 64.0                       # one unit of a 64x64 design

    bg, back, front, accent = ((30, 30, 46, 255), (108, 112, 134, 255),
                               (203, 166, 247, 255), (249, 226, 175, 255))

    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=14 * u, fill=bg)
    # the photo behind, tilted away
    d.rounded_rectangle([16 * u, 12 * u, 50 * u, 40 * u], radius=3 * u,
                        fill=back)
    # the one in front
    d.rounded_rectangle([12 * u, 20 * u, 46 * u, 50 * u], radius=3 * u,
                        fill=front)
    # a hill and a sun inside it, so it reads as a picture and not a card
    d.polygon([(15 * u, 46 * u), (25 * u, 33 * u), (33 * u, 46 * u)], fill=bg)
    d.polygon([(28 * u, 46 * u), (36 * u, 36 * u), (44 * u, 46 * u)], fill=bg)
    d.ellipse([35 * u, 24 * u, 41 * u, 30 * u], fill=accent)

    return img.resize((size, size), Image.LANCZOS)


def write_icons():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [draw_icon(s) for s in sizes]
    png = HERE / "icon.png"
    frames[-1].save(png)

    ico = HERE / "icon.ico"
    try:
        frames[-1].save(ico, format="ICO",
                        sizes=[(s, s) for s in sizes])
    except (OSError, ValueError):
        ico = None
    return ico, png


# --------------------------------------------------------------------------
# the shortcut, per platform
# --------------------------------------------------------------------------

def desktop_dir():
    for candidate in (Path.home() / "Desktop", Path.home() / "desktop"):
        if candidate.is_dir():
            return candidate
    # Linux with a translated desktop folder
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        if out and Path(out).is_dir():
            return Path(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def make_windows(name, args, ico):
    target = HERE / "start.bat"
    desk = desktop_dir()
    if desk is None:
        return None, "Could not find your Desktop folder."
    link = desk / f"{name}.lnk"

    def quoted(value):
        """A single-quoted PowerShell literal; only the quote itself needs
        escaping, so a folder called O'Brien no longer breaks the script."""
        return "'" + str(value).replace("'", "''") + "'"

    ps = f"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut({quoted(link)})
$s.TargetPath = {quoted(target)}
$s.Arguments = {quoted(args)}
$s.WorkingDirectory = {quoted(HERE)}
$s.Description = 'Image Organizer'
{f"$s.IconLocation = {quoted(ico)}" if ico else ""}
$s.Save()
"""
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-Command", ps], check=True, capture_output=True,
                       timeout=30)
    except FileNotFoundError:
        return None, "PowerShell was not found, so the shortcut could not be made."
    except subprocess.CalledProcessError as exc:
        return None, f"Windows refused to make the shortcut: {exc.stderr.decode()[:200]}"
    return link, None


def make_macos(name, args):
    desk = desktop_dir()
    if desk is None:
        return None, "Could not find your Desktop folder."
    launcher = HERE / "start.command"
    launcher.chmod(0o755)
    link = desk / f"{name}.command"
    body = f'#!/bin/sh\nexec "{launcher}" {args}\n'
    link.write_text(body, encoding="utf-8")
    link.chmod(0o755)
    return link, None


def make_linux(name, args, png):
    desk = desktop_dir()
    if desk is None:
        return None, "Could not find your Desktop folder."
    (HERE / "start.sh").chmod(0o755)
    link = desk / f"{name.lower().replace(' ', '-')}.desktop"
    link.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={name}\n"
        "Comment=Browse and organise your generated images\n"
        f"Exec=\"{HERE / 'start.sh'}\" {args}\n"
        f"Path={HERE}\n"
        f"Icon={png}\n"
        "Terminal=true\n"
        "Categories=Graphics;Viewer;\n",
        encoding="utf-8")
    link.chmod(0o755)
    return link, None


# --------------------------------------------------------------------------

def main():
    argv = sys.argv[1:]
    dev = any(a in ("--dev", "--reload", "-r") for a in argv)
    name = "Image Organizer"
    for i, a in enumerate(argv):
        if a == "--name" and i + 1 < len(argv):
            name = argv[i + 1]
        elif a.startswith("--name="):
            name = a.split("=", 1)[1]
    if dev and name == "Image Organizer":
        name = "Image Organizer (dev)"

    if not (HERE / "app.py").exists():
        sys.exit("Put make_shortcut.py in the same folder as app.py, then run it again.")

    try:
        ico, png = write_icons()
        print(f"Icon written to {png.name}" + (f" and {ico.name}" if ico else ""))
    except ImportError:
        ico = png = None
        print("Pillow is not installed yet, so the shortcut gets the default icon.")

    args = "--reload" if dev else ""
    if os.name == "nt":
        link, problem = make_windows(name, args, ico)
    elif sys.platform == "darwin":
        link, problem = make_macos(name, args)
    else:
        link, problem = make_linux(name, args, png)

    if problem:
        print("\n" + problem)
        print(f"You can still start it by double-clicking the launcher in\n  {HERE}")
        return

    print(f"\nDone. '{link.name}' is on your desktop.")
    if dev:
        print("It runs with --reload, so saving a file restarts the server.")
    print("\nThe shortcut points at the launcher in this folder, so editing the\n"
          "code changes what it runs. Only run this again if you move the folder.")
    if sys.platform == "darwin":
        print("\nmacOS may ask once whether you trust it. Right-click, Open, "
              "then Open again.")
    elif os.name != "nt":
        print("\nSome desktops ask you to right-click the new file and choose\n"
              "'Allow launching' the first time.")


if __name__ == "__main__":
    main()
