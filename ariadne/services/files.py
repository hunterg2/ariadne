"""Small file helpers shared by the export, edit and metadata routes."""

import os

from PIL import Image

from ariadne import config


def unique_dest(directory, filename):
    dest = os.path.join(directory, filename)
    if not os.path.exists(dest):
        return dest
    stem, ext = os.path.splitext(filename)
    i = 1
    while True:
        candidate = os.path.join(directory, f"{stem} ({i}){ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1


def forget(d, path):
    """Drop every library row that points at a file that is gone."""
    d.execute("DELETE FROM tags WHERE path=?", (path,))


def ext_for(fmt):
    return ".jpg" if fmt in ("jpg", "jpeg") else "." + fmt


def rewrite_format(path):
    """Pillow format name for a file whose metadata can be rewritten in its
    own format, or None when it is not one we write."""
    fmt = (os.path.splitext(path)[1].lstrip(".") or "png").lower()
    if fmt == "jpg":
        fmt = "jpeg"
    return fmt if fmt in config.REWRITABLE_FORMATS else None


def source_exif(path):
    """The file's own EXIF block, or None if it cannot be read. "Keep all
    metadata" starts from this so untouched camera tags survive a rewrite."""
    try:
        with Image.open(path) as probe:
            return probe.getexif()
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def edit_dest(source_path, fmt, dest_mode, dest_dir):
    """Where an edited copy goes. Originals are never the default target."""
    ext = ext_for(fmt)
    stem = os.path.splitext(os.path.basename(source_path))[0]
    if dest_mode == "folder":
        if not dest_dir or not os.path.isdir(dest_dir):
            raise ValueError("Pick a destination folder that exists.")
        return unique_dest(dest_dir, stem + ext)
    if dest_mode == "overwrite":
        return os.path.join(os.path.dirname(source_path), stem + ext)
    return unique_dest(os.path.dirname(source_path), stem + "_edit" + ext)
