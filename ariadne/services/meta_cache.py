"""Cached generation metadata. The extraction itself lives in ariadne.metadata;
this wrapper remembers the result per file, keyed on mtime and size."""

import json
import os

from ariadne import metadata
from ariadne.db import db


def meta_from_row(row):
    """A cached meta row in the shape metadata.extract() returns."""
    return {
        "width": row["width"] or 0, "height": row["height"] or 0,
        "prompt": row["prompt"] or "", "negative": row["negative"] or "",
        "steps": row["steps"] or "", "cfg": row["cfg"] or "",
        "sampler": row["sampler"] or "", "scheduler": row["scheduler"] or "",
        "seed": row["seed"] or "", "denoise": row["denoise"] or "",
        "model": row["model"] or "", "loras": json.loads(row["loras"] or "[]"),
        "phash": row["phash"] or "", "source": row["source"] or "",
        "prompt_list": row["prompt_list"] or "",
        "prompt_line": row["prompt_line"] or 0,
        "prompt_lines": row["prompt_lines"] or 0,
    }


def get_metadata(full_path, st=None):
    """Cached wrapper. Re-reads the file only when mtime or size changed."""
    try:
        st = st or os.stat(full_path)
    except OSError:
        return metadata.blank()

    d = db()
    row = d.execute("SELECT * FROM meta WHERE path=?", (full_path,)).fetchone()
    if row and row["mtime"] == st.st_mtime_ns and row["size"] == st.st_size:
        return meta_from_row(row)

    meta = metadata.extract(full_path)
    # an upsert rather than REPLACE: the row keeps its rowid, which the
    # prompt search index is keyed on
    d.execute(
        "INSERT INTO meta (path, mtime, size, ctime, width, height, "
        "prompt, negative, steps, cfg, sampler, scheduler, seed, denoise, model, "
        "loras, phash, source, prompt_list, prompt_line, prompt_lines) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, size=excluded.size, "
        "ctime=excluded.ctime, width=excluded.width, height=excluded.height, "
        "prompt=excluded.prompt, negative=excluded.negative, steps=excluded.steps, "
        "cfg=excluded.cfg, sampler=excluded.sampler, scheduler=excluded.scheduler, "
        "seed=excluded.seed, denoise=excluded.denoise, model=excluded.model, "
        "loras=excluded.loras, phash=excluded.phash, source=excluded.source, "
        "prompt_list=excluded.prompt_list, prompt_line=excluded.prompt_line, "
        "prompt_lines=excluded.prompt_lines",
        (full_path, st.st_mtime_ns, st.st_size, st.st_ctime,
         meta["width"], meta["height"], meta["prompt"], meta["negative"],
         meta["steps"], meta["cfg"], meta["sampler"], meta["scheduler"],
         meta["seed"], meta["denoise"], meta["model"],
         json.dumps(meta["loras"]), meta["phash"], meta["source"],
         meta["prompt_list"], meta["prompt_line"], meta["prompt_lines"]),
    )
    d.commit()
    return meta
