"""Time the image index against a synthetic library.

    py -3 scripts/bench_index.py            # 200k rows
    py -3 scripts/bench_index.py 50000      # smaller

Rows go straight into ``images``/``meta``/``ratings``/``tags`` in a temporary
app directory; no files are read. Each query runs twice and the second time
is reported, so what you see is the steady state the grid feels.
"""

import json
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ariadne import create_app  # noqa: E402
from ariadne.db import db  # noqa: E402

WORDS = ("dragon castle night neon portrait forest rain cyberpunk cat knight city "
         "sunset ocean mountain robot flower desert snow bridge temple fox owl "
         "detailed cinematic soft light wide angle macro film grain").split()
MODELS = [f"model_{i:02d}.safetensors" for i in range(20)]
TAGS = [f"t{i:02d}" for i in range(50)]


def seed(n, folders=400):
    rnd = random.Random(1)
    d = db()
    now = time.time()
    base = now - n * 60
    images, meta, ratings, tags = [], [], [], []
    for i in range(n):
        folder = f"C:\\lib\\f{i % folders:03d}"
        path = f"{folder}\\img_{i:06d}.png"
        ctime = base + i * 60
        images.append((path, folder, f"f{i % folders:03d}", f"img_{i:06d}.png", ".png",
                       int(ctime * 1e9), rnd.randint(200_000, 9_000_000), ctime,
                       rnd.choice((1024, 832, 1216)), rnd.choice((1024, 1216, 832)),
                       "generated" if i % 10 else "photo", 0, now, now))
        prompt = " ".join(rnd.choice(WORDS) for _ in range(rnd.randint(6, 18)))
        meta.append((path, int(ctime * 1e9), 1000, ctime, 1024, 1024, prompt, "blurry, lowres",
                     str(rnd.choice((20, 25, 30, 40))), str(rnd.choice((5, 7, 8))),
                     "dpm++ 2m", "karras", str(rnd.randint(1, 10**9)), "",
                     rnd.choice(MODELS), json.dumps(["lora_a"] if i % 7 == 0 else []),
                     f"{rnd.getrandbits(64):016x}", "a1111 text", "", 0, 0, "generated"))
        if i % 10 < 3:
            ratings.append((path, rnd.randint(1, 5), 1 if i % 37 == 0 else 0, None, now))
        if i % 5 == 0:
            for t in rnd.sample(TAGS, rnd.randint(1, 3)):
                tags.append((path, t))
    d.executemany("INSERT INTO images (path, folder, folder_name, name, ext, mtime, size, ctime, "
                  "width, height, kind, missing, indexed_at, seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  images)
    d.executemany("INSERT INTO meta (path, mtime, size, ctime, width, height, prompt, negative, steps, "
                  "cfg, sampler, scheduler, seed, denoise, model, loras, phash, source, prompt_list, "
                  "prompt_line, prompt_lines, kind) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  meta)
    d.executemany("INSERT INTO ratings (path, stars, rejected, label, updated) VALUES (?,?,?,?,?)", ratings)
    d.executemany("INSERT OR IGNORE INTO tags VALUES (?,?)", tags)
    d.commit()


def timed(label, fn):
    fn()
    t0 = time.perf_counter()
    out = fn()
    ms = (time.perf_counter() - t0) * 1000
    extra = ""
    if isinstance(out, dict) and "total" in out:
        extra = f"  total={out['total']}"
    elif isinstance(out, dict) and "groups" in out:
        extra = f"  groups={len(out['groups'])}"
    elif isinstance(out, (int, float)):
        extra = f"  ={out}"
    print(f"{ms:8.1f} ms  {label}{extra}")
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000
    from ariadne.services.index import indexer
    indexer.stop()
    tmp = tempfile.mkdtemp(prefix="ariadne-bench-")
    try:
        create_app(app_dir=tmp)
        indexer.stop()
        t0 = time.perf_counter()
        seed(n)
        print(f"seeded {n} rows in {time.perf_counter() - t0:.1f}s\n")

        from ariadne.services import duplicates, index
        q = index.query_images
        folder = "C:\\lib\\f007"
        timed("whole library, newest first, page 0", lambda: q(limit=200))
        timed("whole library, offset 150000", lambda: q(offset=min(150_000, n - 200), limit=200))
        timed("one folder, page 0", lambda: q(folder=folder, limit=200))
        timed("sort by stars", lambda: q(sort="stars_desc", limit=200))
        timed("sort by name", lambda: q(sort="name_asc", limit=200))
        timed("stars >= 4", lambda: q(stars_min=4, limit=200))
        timed("hide rejected", lambda: q(rejected=False, limit=200))
        timed("kind = photo", lambda: q(kind="photo", limit=200))
        timed("tag filter", lambda: q(tag="t07", limit=200))
        timed('q: prompt contains "dragon castle"', lambda: q(q='prompt: "...dragon castle..."', limit=200))
        timed('q: prompt starts "dragon"', lambda: q(q='prompt: "dragon..."', limit=200))
        timed('q: model exact', lambda: q(q="model: model_03.safetensors", limit=200))
        timed('q: steps 20...30 & tag', lambda: q(q="steps: 20...30; tag: t01", limit=200))
        timed('q: seed', lambda: q(q="seed: 12345", limit=200))
        timed("folder summary (one)", lambda: index.folder_summary(folder))
        timed("folder summaries (400 folders, one call)", lambda: len(index.folder_summaries([f"C:\\lib\\f{i:03d}" for i in range(400)])))
        timed("pending count", lambda: index.pending_count())
        timed("get_image", lambda: index.get_image("C:\\lib\\f007\\img_000007.png") and 1)
        timed("unique prompts (one folder)", lambda: len(duplicates.unique_prompts(folder)))
        timed("duplicates, one folder, similar", lambda: duplicates.find_groups(folder, "similar"))
        timed("duplicates, whole library, identical", lambda: duplicates.find_groups(None, "identical"))
        timed("duplicates, whole library, similar", lambda: duplicates.find_groups(None, "similar"))
    finally:
        from ariadne.db import retire_connections
        retire_connections()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
