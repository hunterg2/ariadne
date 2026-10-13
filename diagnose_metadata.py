#!/usr/bin/env python3
"""Report what an image generator actually wrote into a folder of PNGs.

Usage:
    python diagnose_metadata.py PATH/TO/FOLDER        inspects the first 5 files
    python diagnose_metadata.py PATH/TO/FOLDER 8      inspects the first 8

Prints, and writes the same text to metadata_report.txt in the current
directory:

  * which metadata chunks each file carries, and how big they are
  * whether those chunks are identical across files. This is the usual reason
    every image in a batch shows the same prompt: a prompt-list node picked
    its line at run time and never wrote the chosen line to disk.
  * every node type present, and the widget layout of the sampler nodes
  * what metadata.py, the app's own parser, pulls out of each file

Nothing is modified. Safe to run on any folder.
"""

import glob
import hashlib
import json
import os
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is not installed. Run:  pip install pillow")

# Imported rather than reimplemented, so this report always matches what the
# app actually does. It lives in the ariadne package beside this script.
from ariadne import metadata

Image.MAX_IMAGE_PIXELS = None

REPORT_FILE = "metadata_report.txt"
DEFAULT_LIMIT = 5

OUT = []


def say(line=""):
    print(line)
    OUT.append(line)


def sha(text):
    if isinstance(text, str):
        text = text.encode("utf-8", "replace")
    return hashlib.sha1(text).hexdigest()[:12]


def size_of(text):
    n = len(text.encode("utf-8", "replace")) if isinstance(text, str) else len(text)
    return f"{n / 1024:.1f} KB" if n >= 1024 else f"{n} B"


def short(text, n=68):
    text = (text or "").replace("\n", " | ").strip()
    return (text[:n] + "...") if len(text) > n else (text or "(nothing)")


def report_chunks(picked):
    """What each file carries. Returns {filename: {chunk key: text}}."""
    chunks = {}
    say("\n--- WHAT EACH FILE CARRIES " + "-" * 50)
    for path in picked:
        name = os.path.basename(path)
        try:
            with Image.open(path) as im:
                info = dict(im.info or {})
        except (OSError, ValueError) as exc:
            say(f"\n{name}\n    could not open: {exc}")
            continue

        text_keys = {k: v for k, v in info.items() if isinstance(v, (str, bytes))}
        chunks[name] = text_keys

        say(f"\n{name}")
        if not text_keys:
            say("    no text metadata at all")
        for k, v in text_keys.items():
            say(f"    {k:<14} {size_of(v):>9}   sha1:{sha(v)}")
    return chunks


def report_sameness(chunks):
    all_keys = set()
    for kv in chunks.values():
        all_keys.update(kv)

    say("\n--- ARE THE CHUNKS THE SAME ACROSS FILES? " + "-" * 35)
    say("(this is the important part)")
    for key in sorted(all_keys):
        hashes = {}
        for name, kv in chunks.items():
            if key in kv:
                hashes.setdefault(sha(kv[key]), []).append(name)
        present = sum(len(v) for v in hashes.values())
        if len(hashes) == 1 and present > 1:
            say(f"\n  {key}: IDENTICAL in all {present} files  <-- same data for every image")
        else:
            say(f"\n  {key}: {len(hashes)} distinct value(s) across {present} files  <-- varies per image")
            for h, names in hashes.items():
                say(f"      {h}  {', '.join(names[:4])}{' ...' if len(names) > 4 else ''}")


def report_nodes(chunks):
    """Node inventory from the first file that carries a workflow."""
    say("\n--- NODES IN THE WORKFLOW " + "-" * 51)
    sample = None
    for name, kv in chunks.items():
        if "workflow" in kv:
            try:
                sample = (name, json.loads(kv["workflow"]))
                break
            except ValueError:
                continue
    if not sample:
        say("\n  no 'workflow' chunk in any inspected file")
        return

    name, wf = sample
    nodes = wf.get("nodes", []) or []
    say(f"\n  from {name}: {len(nodes)} nodes")
    types = {}
    for n in nodes:
        t = n.get("type") or n.get("class_type") or "?"
        types[t] = types.get(t, 0) + 1
    for t, c in sorted(types.items(), key=lambda x: -x[1]):
        say(f"    {c:>3} x {t}")

    say("\n  sampler-ish nodes and their widget layout:")
    found = False
    for n in nodes:
        t = str(n.get("type") or n.get("class_type") or "")
        if "sampler" in t.lower():
            found = True
            w = n.get("widgets_values", [])
            say(f"    type={t}  title={n.get('title')!r}  widgets_values has {len(w)} entries:")
            for i, val in enumerate(w if isinstance(w, list) else [w]):
                say(f"        [{i}] {short(str(val), 46)}")
    if not found:
        say("    none matched 'sampler' by name; the workflow may use a custom sampler node")

    say("\n  nodes holding text (candidates for the prompt):")
    for n in nodes:
        t = str(n.get("type") or n.get("class_type") or "")
        w = n.get("widgets_values", [])
        if isinstance(w, list) and w and isinstance(w[0], str) and len(w[0]) > 12:
            say(f"    type={t}  title={n.get('title')!r}")
            say(f"        {short(w[0])}")


def report_extraction(picked):
    """What the app's parser reads. Returns the set of distinct prompts."""
    say("\n--- WHAT THE ORGANIZER EXTRACTS " + "-" * 45)
    prompts = set()
    for path in picked:
        name = os.path.basename(path)
        m = metadata.extract(path, want_hash=False)
        say(f"\n  {name}   [{m['source']}]")
        say(f"      steps={m['steps'] or '-'}  cfg={m['cfg'] or '-'}  "
            f"sampler={m['sampler'] or '-'}  scheduler={m['scheduler'] or '-'}"
            f"  seed={m['seed'] or '-'}")
        say(f"      model:    {m['model'] or '-'}")
        for lora in m["loras"]:
            say(f"      lora:     {lora}")
        say(f"      prompt:   {short(m['prompt'])}")
        if m["negative"]:
            say(f"      negative: {short(m['negative'])}")
        prompts.add(m["prompt"])
    return prompts


def report_verdict(picked, prompts):
    say("\n--- VERDICT " + "-" * 65)
    if len(picked) > 1 and len(prompts) == 1:
        if next(iter(prompts)):
            say("\n  Every file gave the SAME prompt. Either they really are one")
            say("  generation, or the per-image text was never written to disk")
            say("  (a prompt-list node that picks its line during execution).")
            say("  Check whether the 'prompt' chunk above varies per file: if it")
            say("  does not, no tool can recover the individual lines.")
        else:
            say("\n  No prompt found in any file. The parser does not recognise these")
            say("  nodes yet; the node inventory above shows what they are.")
    else:
        say(f"\n  {len(prompts)} distinct prompts across {len(picked)} files. Working as intended.")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    folder = argv[0] if argv else "."
    try:
        limit = int(argv[1]) if len(argv) > 1 else DEFAULT_LIMIT
    except ValueError:
        sys.exit(f"The second argument must be a number of files, not {argv[1]!r}")

    if not os.path.isdir(folder):
        sys.exit(f"Not a folder: {folder}")

    files = []
    for ext in ("*.png", "*.PNG"):
        files.extend(glob.glob(os.path.join(folder, ext)))
    files = sorted(set(files))
    if not files:
        sys.exit(f"No PNG files found in {folder}")

    picked = files[:limit]
    say("=" * 78)
    say(f"Folder: {folder}")
    say(f"{len(files)} PNG files found, inspecting the first {len(picked)}")
    say("=" * 78)

    chunks = report_chunks(picked)
    if not chunks:
        say("\nNothing readable. Stop here.")
        return
    report_sameness(chunks)
    report_nodes(chunks)
    prompts = report_extraction(picked)
    report_verdict(picked, prompts)
    say("\n" + "=" * 78)

    try:
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(OUT))
    except OSError as exc:
        print(f"\nCould not write {REPORT_FILE}: {exc}")
    else:
        print(f"\nAlso saved to {REPORT_FILE}")


if __name__ == "__main__":
    main()
