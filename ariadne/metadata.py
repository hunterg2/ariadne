#!/usr/bin/env python3
"""
Workflow-agnostic image metadata extraction.

The problem this solves: node class names and node titles are chosen freely by
workflow authors, so matching on them ("KSampler", "Positive Prompt") breaks the
moment somebody uses a custom sampler or retitles a box. Widget positions are no
better - KSampler, KSamplerAdvanced and the Efficiency variant all put steps at a
different index.

What is stable is the graph. ComfyUI matches submitted values against each node's
declared input NAMES, so a node that renames `steps` simply stops working. That
makes `steps`, `cfg`, `sampler_name`, `ckpt_name`, `lora_name` and `text` a
de facto contract across the whole ecosystem. This module reads those, and walks
the links to work out which text node actually feeds the sampler's positive input.

Five strategies, tried in order, each filling only what earlier ones missed:

  1. prompt graph      the API-format `prompt` chunk. Named inputs plus real
                       links, so this is exact. Resolved per execution.
  2. workflow graph    the UI `workflow` chunk. Links are present, so structure
                       still works, but scalars are positional widgets.
  3. widget anchor     for widgets, find a known sampler name in the array and
                       read relative to it. One rule covers every KSampler
                       variant because they differ in absolute position only.
  4. a1111 / exif      `parameters` text chunk, or EXIF UserComment for jpg/webp.
  5. deep scan         last resort: walk any JSON present and pick up values by
                       key name wherever they sit.

Every result carries `source`, naming which strategies produced it, so a partial
read is visible rather than silent.

The tail of the file does two more things. ``read_camera`` turns the EXIF a
photo carries (camera, lens, exposure, dates, location) into text for the
index and the inspector, driven by one table of tags. And when the image
editor saves a copy, ``collect_chunks`` and ``write_image`` carry the
original's text chunks and EXIF across, trimmed to the generation data, or
dropped, as the user chose; location data is stripped unless asked for.

Public API:
    extract(path, want_hash=True) -> dict     generation settings, size, phash
    read_chunks(img) -> dict                  every text blob in the file
    read_camera(path) -> dict                 camera EXIF tags, as text
    dhash(img) -> str                         16 hex characters
    oriented(img) -> Image                    EXIF rotation applied
    collect_chunks(path, mode) -> dict        chunks to carry into a copy
    write_image(img, dest, fmt, ...) -> list of notes

Run ``python metadata.py IMAGE [IMAGE ...]`` to print what it reads from each.
"""

import json
import os
import re
import sys

from PIL import Image, ImageOps
from PIL.PngImagePlugin import PngInfo

Image.MAX_IMAGE_PIXELS = None

# --------------------------------------------------------------------------
# vocabulary
# --------------------------------------------------------------------------

SAMPLERS = {
    "euler", "euler_cfg_pp", "euler_ancestral", "euler_ancestral_cfg_pp", "heun",
    "heunpp2", "dpm_2", "dpm_2_ancestral", "lms", "dpm_fast", "dpm_adaptive",
    "dpmpp_2s_ancestral", "dpmpp_2s_ancestral_cfg_pp", "dpmpp_sde", "dpmpp_sde_gpu",
    "dpmpp_2m", "dpmpp_2m_cfg_pp", "dpmpp_2m_sde", "dpmpp_2m_sde_gpu", "dpmpp_3m_sde",
    "dpmpp_3m_sde_gpu", "ddpm", "lcm", "ipndm", "ipndm_v", "deis", "res_multistep",
    "res_multistep_cfg_pp", "gradient_estimation", "er_sde", "seeds_2", "seeds_3",
    "ddim", "uni_pc", "uni_pc_bh2", "restart", "sa_solver",
}

SCHEDULERS = {
    "normal", "karras", "exponential", "sgm_uniform", "simple", "ddim_uniform",
    "beta", "linear_quadratic", "kl_optimal", "align_your_steps", "gits", "ays",
    "ays_30", "ays_30+", "beta57",
}

# widget values that are control flags, never a prompt
CONTROL_WORDS = {
    "enable", "disable", "randomize", "fixed", "increment", "decrement", "none",
    "true", "false", "yes", "no", "auto", "default", "bypass", "mute",
}

WEIGHT_FILE = re.compile(
    r"\.(safetensors|ckpt|pt|pth|bin|gguf|sft|onnx|vae|yaml|json)$", re.I
)

# field name -> input keys that carry it, most specific first
FIELD_KEYS = {
    "steps": ("steps", "num_steps", "sampling_steps", "total_steps"),
    "cfg": ("cfg", "cfg_scale", "guidance_scale", "guidance", "cfg_scale_positive"),
    "sampler": ("sampler_name", "sampler"),
    "scheduler": ("scheduler", "scheduler_name", "schedule", "sigma_schedule"),
    "seed": ("seed", "noise_seed", "rand_seed"),
    "denoise": ("denoise", "denoising_strength"),
}

MODEL_KEYS = (
    "ckpt_name", "unet_name", "model_name", "model_path", "base_ckpt_name",
    "checkpoint", "checkpoint_name", "diffusion_model",
)

TEXT_KEYS = (
    "text", "string", "prompt", "text_g", "text_l", "populated_text",
    "wildcard_text", "text_positive", "positive_prompt", "value", "content",
)

# links to follow when hunting for the positive prompt
POSITIVE_LINKS = (
    "positive", "conditioning", "cond", "positive_conditioning", "base_positive",
    "guider", "positive_g", "text",
)
NEGATIVE_LINKS = (
    "negative", "negative_conditioning", "base_negative", "negative_g",
)

# some loaders (Efficiency, Impact pipes) carry the prompt text directly rather
# than linking out to a text node, so the polarity is in the key name itself
POSITIVE_TEXT_KEYS = (
    "positive", "text_positive", "positive_prompt", "positive_g", "prompt_positive",
)
NEGATIVE_TEXT_KEYS = (
    "negative", "text_negative", "negative_prompt", "negative_g", "prompt_negative",
)

MODEL_LINKS = ("model", "unet", "base_model", "model1", "patch_model")

# A prompt-list node holds every line at once and picks one per run. The line
# number is usually right there on the same node as an index input, which is
# what makes the used line recoverable.
INDEX_KEYS = (
    "index", "current_index", "line_index", "list_index", "select", "selected",
    "line", "line_number", "counter", "iteration", "batch_index",
)
LIST_HINT = re.compile(
    r"(prompt.?list|list.?prompt|multi.?line|one per line|line.?from|text.?list|"
    r"iterat|batch.?prompt|prompt.?queue|cycle|from.?file)", re.I
)

# inputs that never lead to prompt text
NON_TEXT_LINKS = {
    "negative", "model", "clip", "vae", "latent_image", "image", "mask", "samples",
    "pixels", "control_net", "sigmas", "noise", "guider", "sampler", "clip_vision",
}

LINK = "__link__"


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def _is_api_link(v):
    """API format encodes a link as [node_id, output_slot]."""
    return (
        isinstance(v, (list, tuple)) and len(v) == 2
        and isinstance(v[0], (str, int)) and not isinstance(v[0], bool)
        and isinstance(v[1], int) and not isinstance(v[1], bool)
    )


def _mk_link(node_id, slot):
    return (LINK, str(node_id), slot)


def _is_link(v):
    return isinstance(v, tuple) and len(v) == 3 and v[0] == LINK


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def looks_like_prompt(s):
    if not isinstance(s, str):
        return False
    s = s.strip()
    if len(s) < 2:
        return False
    low = s.lower()
    if low in SAMPLERS or low in SCHEDULERS or low in CONTROL_WORDS:
        return False
    if WEIGHT_FILE.search(low):
        return False
    if re.fullmatch(r"[-+0-9.,;:\s]+", s):          # pure numbers
        return False
    if re.fullmatch(r"[a-z0-9_\-]{1,24}", low) and " " not in s and "," not in s:
        return False                                 # bare identifier, e.g. "sdxl_v1"
    return True


def _clean(v):
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("none", "null") else s


def blank():
    return {
        "width": 0, "height": 0, "prompt": "", "negative": "", "steps": "",
        "cfg": "", "sampler": "", "scheduler": "", "seed": "", "denoise": "",
        "model": "", "loras": [], "phash": "", "source": "",
        # set only when the prompt turned out to be a list of prompts
        "prompt_list": "", "prompt_line": 0, "prompt_lines": 0,
    }


# --------------------------------------------------------------------------
# graph construction - both chunk formats become the same shape
#   node: {"class_type": str, "title": str, "inputs": {name: value|link},
#          "widgets": [...]}
# --------------------------------------------------------------------------

def graph_from_api(obj):
    """The `prompt` chunk: {node_id: {class_type, inputs}}."""
    if not isinstance(obj, dict):
        return {}
    graph = {}
    for nid, node in obj.items():
        if not isinstance(node, dict):
            continue
        inputs = {}
        for name, val in (node.get("inputs") or {}).items():
            inputs[name] = _mk_link(val[0], val[1]) if _is_api_link(val) else val
        graph[str(nid)] = {
            "class_type": str(node.get("class_type") or ""),
            "title": (node.get("_meta") or {}).get("title") if isinstance(node.get("_meta"), dict) else None,
            "inputs": inputs,
            "widgets": [],
        }
    return graph


def graph_from_workflow(wf):
    """The `workflow` chunk: {nodes: [...], links: [...]}."""
    if not isinstance(wf, dict):
        return {}
    nodes = wf.get("nodes")
    if not isinstance(nodes, list):
        return {}

    # link id -> (origin node id, origin slot); two schemas exist in the wild
    links = {}
    raw_links = wf.get("links") or []
    if isinstance(raw_links, list):
        for l in raw_links:
            if isinstance(l, (list, tuple)) and len(l) >= 3:
                links[l[0]] = (str(l[1]), l[2])
            elif isinstance(l, dict) and l.get("id") is not None:
                links[l["id"]] = (str(l.get("origin_id")), l.get("origin_slot") or 0)
    elif isinstance(raw_links, dict):
        for lid, l in raw_links.items():
            if isinstance(l, dict):
                links[lid] = (str(l.get("origin_id")), l.get("origin_slot") or 0)

    graph = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = str(node.get("id"))
        inputs = {}
        for inp in node.get("inputs") or []:
            if not isinstance(inp, dict):
                continue
            link_id = inp.get("link")
            name = str(inp.get("name") or "")
            if link_id is not None and link_id in links:
                origin, slot = links[link_id]
                inputs[name] = _mk_link(origin, slot)
            elif inp.get("widget") and inp.get("value") is not None:
                inputs[name] = inp["value"]
        widgets = node.get("widgets_values")
        if isinstance(widgets, dict):                 # some frontends emit a dict
            for k, v in widgets.items():
                inputs.setdefault(str(k), v)
            widgets = list(widgets.values())
        graph[nid] = {
            "class_type": str(node.get("type") or ""),
            "title": node.get("title"),
            "inputs": inputs,
            "widgets": widgets if isinstance(widgets, list) else [],
        }
    return graph


# --------------------------------------------------------------------------
# traversal
# --------------------------------------------------------------------------

def _upstream(graph, start, max_depth=250):
    """Breadth-first walk against the direction of the links."""
    if start not in graph:
        return []
    order, seen, queue = [], {start}, [(start, 0)]
    while queue:
        nid, depth = queue.pop(0)
        order.append((nid, depth))
        if depth >= max_depth:
            continue
        for val in graph[nid]["inputs"].values():
            if _is_link(val) and val[1] not in seen and val[1] in graph:
                seen.add(val[1])
                queue.append((val[1], depth + 1))
    return order


def _resolve(graph, val, depth=0):
    """Follow a link to whatever literal sits behind it."""
    if not _is_link(val) or depth > 12:
        return val if not _is_link(val) else None
    node = graph.get(val[1])
    if not node:
        return None
    for key in ("value", "string", "text", "number", "int", "float", "seed"):
        v = node["inputs"].get(key)
        if v is not None and not _is_link(v):
            return v
        if _is_link(v):
            return _resolve(graph, v, depth + 1)
    for w in node["widgets"]:
        if isinstance(w, (str, int, float)):
            return w
    return None


def _widget_sampler_index(widgets):
    for i, w in enumerate(widgets):
        if isinstance(w, str) and w.strip().lower() in SAMPLERS:
            return i
    return None


def _widget_scheduler_index(widgets):
    for i, w in enumerate(widgets):
        if isinstance(w, str) and w.strip().lower() in SCHEDULERS:
            return i
    return None


def _score_sampler(node):
    """How much does this node look like the thing that did the sampling?"""
    keys = set(node["inputs"])
    score = len(keys & {"steps", "cfg", "sampler_name", "scheduler", "denoise",
                        "positive", "negative", "latent_image", "noise_seed"})
    ct = (node["class_type"] or "").lower()
    if "sampler" in ct:
        score += 3
    if _widget_sampler_index(node["widgets"]) is not None:
        score += 3
    if {"steps", "cfg"} <= keys:
        score += 2
    return score


def _output_nodes(graph):
    """Nodes that end the pipeline - save or preview."""
    out = []
    for nid, node in graph.items():
        ct = (node["class_type"] or "").lower()
        if ("save" in ct or "preview" in ct) and "image" in ct.replace("_", ""):
            out.append(nid)
    if not out:
        out = [nid for nid, n in graph.items() if "images" in n["inputs"]]
    return out


def _pick_sampler(graph):
    """Best sampler node, preferring one that actually feeds a save node."""
    if not graph:
        return None

    depths = {}
    for out in _output_nodes(graph):
        for nid, d in _upstream(graph, out):
            if nid not in depths or d < depths[nid]:
                depths[nid] = d

    best, best_key = None, None
    for nid, node in graph.items():
        score = _score_sampler(node)
        if score < 3:
            continue
        reachable = nid in depths
        # highest score, then closest to the save node
        key = (1 if reachable else 0, score, -depths.get(nid, 999))
        if best_key is None or key > best_key:
            best, best_key = nid, key
    return best


# --------------------------------------------------------------------------
# field extraction
# --------------------------------------------------------------------------

def _text_from(graph, nid, seen=None, depth=0, prefer=(), avoid=(), widget_pick=0, origin=None):
    """Nearest prompt-looking string upstream of this node.

    `prefer` are polarity-specific keys tried before the generic ones, so a
    loader that stores `positive`/`negative` inline is read correctly.
    `avoid` are keys never followed, which keeps the negative prompt out of
    the positive result.
    """
    seen = seen if seen is not None else set()
    if nid in seen or depth > 64 or nid not in graph:
        return ""
    seen.add(nid)
    node = graph[nid]
    avoid_set = {a.lower() for a in avoid}

    for key in tuple(prefer) + TEXT_KEYS:
        if key.lower() in avoid_set:
            continue
        val = node["inputs"].get(key)
        if isinstance(val, str) and looks_like_prompt(val):
            if origin is not None:
                origin["node"] = nid
            return val.strip()
        if _is_link(val):
            found = _text_from(graph, val[1], seen, depth + 1, prefer, avoid,
                               widget_pick, origin)
            if found:
                return found

    # positional widgets: a node holding both prompts lists positive first
    cands = [w.strip() for w in node["widgets"]
             if isinstance(w, str) and looks_like_prompt(w)]
    if cands:
        if origin is not None:
            origin["node"] = nid
        return cands[min(widget_pick, len(cands) - 1)]

    for key, val in node["inputs"].items():
        kl = key.lower()
        if _is_link(val) and kl not in NON_TEXT_LINKS and kl not in avoid_set:
            found = _text_from(graph, val[1], seen, depth + 1, prefer, avoid,
                               widget_pick, origin)
            if found:
                return found
    return ""


def _prompt_via(graph, sampler_id, link_keys, prefer, avoid, widget_pick, origin=None):
    node = graph.get(sampler_id)
    if not node:
        return ""
    for key in tuple(prefer) + tuple(link_keys):
        val = node["inputs"].get(key)
        if isinstance(val, str) and looks_like_prompt(val):
            if origin is not None:
                origin["node"] = sampler_id
            return val.strip()
        if _is_link(val):
            found = _text_from(graph, val[1], set(), 0, prefer, avoid,
                               widget_pick, origin)
            if found:
                return found
    return ""


# --------------------------------------------------------------------------
# prompt lists
# --------------------------------------------------------------------------

def _looks_like_list(text, node):
    """Several complete prompts stacked in one box, rather than one prompt
    that happens to contain newlines."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        return []
    if node:
        label = f"{node.get('class_type') or ''} {node.get('title') or ''}"
        if LIST_HINT.search(label):
            return lines
        if any(k in node["inputs"] for k in INDEX_KEYS):
            return lines
    # no naming help: only call it a list if the lines really read as separate
    # prompts, which keeps ordinary two-line prompts intact
    if len(lines) >= 4 and all(len(l) > 15 for l in lines):
        return lines
    return []


def _list_index(graph, node):
    """The line number this run used, if the graph recorded one."""
    if not node:
        return None
    for key in INDEX_KEYS:
        if key not in node["inputs"]:
            continue
        val = node["inputs"][key]
        if _is_link(val):
            val = _resolve(graph, val)
        n = _num(val)
        if n is not None and n == int(n) and n >= 0:
            return int(n)
    # widget form: an integer sitting on a node whose text we just used
    text_seen = False
    for w in node["widgets"]:
        if isinstance(w, str) and "\n" in w:
            text_seen = True
            continue
        if text_seen:
            n = _num(w)
            if n is not None and n == int(n) and 0 <= n < 10000 and not isinstance(w, bool):
                return int(n)
    return None


def _resolve_list(graph, text, node_id, meta):
    """Turn a whole prompt list into the single line that was used."""
    node = graph.get(node_id) if node_id else None
    lines = _looks_like_list(text, node)
    if not lines:
        return text

    meta["prompt_lines"] = len(lines)
    meta["prompt_list"] = "\n".join(lines)

    idx = _list_index(graph, node)
    if idx is not None:
        picked = idx % len(lines)
        meta["prompt_line"] = picked + 1
        return lines[picked]
    return text


def _settings_from_inputs(graph, sampler_id, meta, mark):
    """Named inputs, sampler first then upstream. Covers decomposed samplers
    such as SamplerCustom, where steps sits on a linked BasicScheduler."""
    for nid, _ in _upstream(graph, sampler_id):
        node = graph[nid]
        for field, keys in FIELD_KEYS.items():
            if meta[field]:
                continue
            for key in keys:
                if key not in node["inputs"]:
                    continue
                val = node["inputs"][key]
                if _is_link(val):
                    val = _resolve(graph, val)
                val = _clean(val)
                if val:
                    meta[field] = val
                    mark(field)
                    break


def _settings_from_widgets(graph, sampler_id, meta, mark):
    """Positional widgets, anchored on a recognised sampler name.

    KSampler         [seed, control, steps, cfg, SAMPLER, scheduler, denoise]
    KSamplerAdvanced [add_noise, seed, control, steps, cfg, SAMPLER, scheduler, ...]
    KSampler (Eff.)  [seed, control, steps, cfg, SAMPLER, scheduler, denoise, ...]

    Absolute indexes differ, offsets from the sampler name do not.
    """
    for nid, _ in _upstream(graph, sampler_id):
        widgets = graph[nid]["widgets"]
        if not widgets:
            continue

        i = _widget_sampler_index(widgets)
        if i is not None:
            if not meta["sampler"]:
                meta["sampler"] = str(widgets[i]).lower()
                mark("sampler")
            if not meta["scheduler"] and i + 1 < len(widgets):
                nxt = widgets[i + 1]
                if isinstance(nxt, str) and nxt.strip().lower() in SCHEDULERS:
                    meta["scheduler"] = nxt.strip().lower()
                    mark("scheduler")
            if not meta["cfg"] and i >= 1 and _num(widgets[i - 1]) is not None:
                meta["cfg"] = _clean(widgets[i - 1])
                mark("cfg")
            if not meta["steps"] and i >= 2:
                n = _num(widgets[i - 2])
                if n is not None and n == int(n) and 0 < n <= 1000:
                    meta["steps"] = str(int(n))
                    mark("steps")
            continue

        # BasicScheduler and friends: [scheduler, steps, denoise]
        j = _widget_scheduler_index(widgets)
        if j is not None:
            if not meta["scheduler"]:
                meta["scheduler"] = str(widgets[j]).lower()
                mark("scheduler")
            if not meta["steps"] and j + 1 < len(widgets):
                n = _num(widgets[j + 1])
                if n is not None and n == int(n) and 0 < n <= 1000:
                    meta["steps"] = str(int(n))
                    mark("steps")


def _find_model(graph, sampler_id, mark):
    for nid, _ in _upstream(graph, sampler_id):
        node = graph[nid]
        for key in MODEL_KEYS:
            val = node["inputs"].get(key)
            if _is_link(val):
                val = _resolve(graph, val)
            if isinstance(val, str) and val.strip():
                mark("model")
                return val.strip()
        ct = (node["class_type"] or "").lower()
        if ("checkpoint" in ct or "unet" in ct or "diffusion" in ct) and "lora" not in ct:
            for w in node["widgets"]:
                if isinstance(w, str) and WEIGHT_FILE.search(w):
                    mark("model")
                    return w.strip()
    return ""


def _find_loras(graph, sampler_id, mark):
    found, seen = [], set()
    for nid, _ in _upstream(graph, sampler_id):
        node = graph[nid]
        ct = (node["class_type"] or "").lower()

        name = node["inputs"].get("lora_name")
        if _is_link(name):
            name = _resolve(graph, name)
        sm = _clean(node["inputs"].get("strength_model", ""))
        cl = _clean(node["inputs"].get("strength_clip", sm))

        if not isinstance(name, str) or not name.strip():
            name = None
            if "lora" in ct:
                # rgthree-style stacks keep each lora in a dict widget
                for w in node["widgets"]:
                    if isinstance(w, dict):
                        cand = w.get("lora") or w.get("name") or w.get("lora_name")
                        if isinstance(cand, str) and cand.strip():
                            st = _clean(w.get("strength") or w.get("strength_model") or "")
                            if w.get("on") is False:
                                continue
                            key = cand.strip().lower()
                            if key not in seen:
                                seen.add(key)
                                found.append(f"{cand.strip()} (Model: {st}, CLIP: {st})" if st
                                             else cand.strip())
                names = [w for w in node["widgets"]
                         if isinstance(w, str) and WEIGHT_FILE.search(w)]
                nums = [w for w in node["widgets"] if _num(w) is not None
                        and not isinstance(w, str)]
                if names:
                    name = names[0]
                    sm = _clean(nums[0]) if nums else ""
                    cl = _clean(nums[1]) if len(nums) > 1 else sm

        if isinstance(name, str) and name.strip():
            key = name.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(f"{name.strip()} (Model: {sm}, CLIP: {cl})" if sm else name.strip())

    if found:
        mark("loras")
    return found


# --------------------------------------------------------------------------
# strategy 4: a1111 / forge text block
# --------------------------------------------------------------------------

A1111_MAP = {
    "steps": "steps", "cfg scale": "cfg", "sampler": "sampler",
    "schedule type": "scheduler", "scheduler": "scheduler", "seed": "seed",
    "model": "model", "denoising strength": "denoise",
}


def _from_a1111(params, meta, mark):
    if not isinstance(params, str) or not params.strip():
        return
    text = params.strip()

    neg_at = text.find("Negative prompt:")
    if neg_at != -1:
        head = text[:neg_at]
        rest = text[neg_at + len("Negative prompt:"):]
        line_end = rest.find("\nSteps:")
        negative = rest if line_end == -1 else rest[:line_end]
    else:
        head, negative = text, ""

    settings_at = head.rfind("\nSteps:")
    if settings_at != -1 and neg_at == -1:
        head = head[:settings_at]

    if not meta["prompt"] and head.strip():
        meta["prompt"] = head.strip()
        mark("prompt")
    if not meta["negative"] and negative.strip():
        meta["negative"] = negative.strip()
        mark("negative")

    tail_at = text.rfind("Steps:")
    if tail_at == -1:
        return
    tail = text[tail_at:].splitlines()[0]

    # split on commas that are not inside quotes
    for part in re.split(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", tail):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        field = A1111_MAP.get(k.strip().lower())
        if field and not meta[field]:
            meta[field] = v.strip().strip('"')
            mark(field)

    lora_tags = re.findall(r"<lora:([^:>]+):([\d.]+)>", meta["prompt"] or "")
    if lora_tags and not meta["loras"]:
        meta["loras"] = [f"{n} (Model: {s}, CLIP: {s})" for n, s in lora_tags]
        mark("loras")


# --------------------------------------------------------------------------
# strategy 5: deep scan
# --------------------------------------------------------------------------

def _deep_scan(obj, meta, mark, allow_prompt=True):
    texts, stack, guard = [], [obj], 0
    while stack and guard < 200000:
        guard += 1
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                kl = str(k).strip().lower()
                if isinstance(v, (dict, list)):
                    if not _is_api_link(v):
                        stack.append(v)
                    continue
                for field, keys in FIELD_KEYS.items():
                    if kl in keys and not meta[field]:
                        val = _clean(v)
                        if val:
                            meta[field] = val
                            mark(field)
                if kl in MODEL_KEYS and not meta["model"] and isinstance(v, str) and v.strip():
                    meta["model"] = v.strip()
                    mark("model")
                if kl in ("text", "prompt", "string") and looks_like_prompt(v):
                    texts.append(str(v).strip())
        elif isinstance(cur, list):
            for x in cur:
                if isinstance(x, (dict, list)):
                    stack.append(x)
                elif looks_like_prompt(x) and len(str(x)) > 20:
                    texts.append(str(x).strip())

    # never let the last-resort scan promote the negative prompt to positive
    if meta["negative"]:
        texts = [t for t in texts if t.strip() != meta["negative"].strip()]
    if allow_prompt and not meta["prompt"] and texts:
        meta["prompt"] = max(texts, key=len)
        mark("prompt")


# --------------------------------------------------------------------------
# perceptual hash
# --------------------------------------------------------------------------

def dhash(img):
    try:
        small = img.convert("L").resize((9, 8), Image.LANCZOS)
        px = list(small.getdata())
        bits = 0
        for row in range(8):
            base = row * 9
            for col in range(8):
                bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
        return f"{bits:016x}"
    except Exception:
        return ""


# --------------------------------------------------------------------------
# chunk gathering
# --------------------------------------------------------------------------

def read_chunks(img):
    """Every text blob the file carries, from PNG chunks and EXIF alike."""
    chunks = {}
    for k, v in (img.info or {}).items():
        if isinstance(v, str) and v.strip():
            chunks[k] = v
        elif isinstance(v, bytes) and k != "exif":
            try:
                chunks[k] = v.decode("utf-8", "ignore")
            except Exception:
                pass
    try:
        exif = img.getexif()
        for tag, key in ((0x9286, "UserComment"), (0x010E, "ImageDescription"),
                         (0x9C9C, "XPComment"), (0x9C9E, "XPKeywords")):
            raw = exif.get(tag)
            if raw is None:
                continue
            if isinstance(raw, bytes):
                for prefix, enc in ((b"UNICODE\x00", "utf-16-be"), (b"ASCII\x00\x00\x00", "utf-8")):
                    if raw.startswith(prefix):
                        raw = raw[len(prefix):]
                        try:
                            raw = raw.decode(enc, "ignore")
                        except Exception:
                            raw = raw.decode("utf-8", "ignore")
                        break
                else:
                    try:
                        raw = raw.decode("utf-16-le", "ignore") if b"\x00" in raw[:8] \
                            else raw.decode("utf-8", "ignore")
                    except Exception:
                        continue
            text = str(raw).replace("\x00", "").strip()
            if text:
                chunks.setdefault(key, text)
    except Exception:
        pass
    return chunks


def _maybe_json(text):
    if not isinstance(text, str):
        return None
    s = text.strip()
    if not s or s[0] not in "{[":
        return None
    try:
        return json.loads(s)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------

def oriented(img):
    """Apply the EXIF orientation flag. Browsers do this automatically, so
    anything we render ourselves has to as well or it disagrees with them."""
    try:
        return ImageOps.exif_transpose(img) or img
    except Exception:
        return img


def extract(path, want_hash=True):
    meta = blank()
    used = []

    def marker(label):
        def mark(_field):
            if label not in used:
                used.append(label)
        return mark

    try:
        with Image.open(path) as img:
            chunks = read_chunks(img)
            shown = oriented(img)
            # report the size the image actually displays at, not the stored one
            meta["width"], meta["height"] = shown.size
            if want_hash:
                meta["phash"] = dhash(shown)
    except (OSError, ValueError) as exc:
        meta["source"] = f"unreadable ({exc.__class__.__name__})"
        return meta

    def run_graph(graph, label):
        if not graph:
            return False
        sampler = _pick_sampler(graph)
        mark = marker(label)
        if sampler is None:
            # no sampler, but text may still be reachable from an output node
            for out in _output_nodes(graph):
                if not meta["prompt"]:
                    found = _text_from(graph, out, set(), 0,
                                       POSITIVE_TEXT_KEYS, NEGATIVE_TEXT_KEYS, 0)
                    if found:
                        meta["prompt"] = found
                        mark("prompt")
            return bool(meta["prompt"])

        if not meta["prompt"]:
            origin = {}
            p = _prompt_via(graph, sampler, POSITIVE_LINKS,
                            POSITIVE_TEXT_KEYS, NEGATIVE_TEXT_KEYS, 0, origin)
            if p:
                meta["prompt"] = _resolve_list(graph, p, origin.get("node"), meta)
                mark("prompt")
                if meta["prompt_line"]:
                    mark("list index")
        if not meta["negative"]:
            n = _prompt_via(graph, sampler, NEGATIVE_LINKS,
                            NEGATIVE_TEXT_KEYS, POSITIVE_TEXT_KEYS, 1)
            if n:
                meta["negative"] = n
                mark("negative")

        _settings_from_inputs(graph, sampler, meta, mark)
        _settings_from_widgets(graph, sampler, meta, marker(
            "widget anchor" if label == "workflow graph" else label))

        if not meta["model"]:
            meta["model"] = _find_model(graph, sampler, mark)
        if not meta["loras"]:
            meta["loras"] = _find_loras(graph, sampler, mark)
        return True

    # 1. API prompt graph - resolved per execution, so it wins
    api = _maybe_json(chunks.get("prompt", ""))
    if api is not None:
        run_graph(graph_from_api(api), "prompt graph")

    # 2 + 3. UI workflow graph, then positional widgets
    wf = _maybe_json(chunks.get("workflow", ""))
    if wf is not None:
        run_graph(graph_from_workflow(wf), "workflow graph")

    # 4. a1111 / forge / exif text
    for key in ("parameters", "Parameters", "UserComment", "ImageDescription",
                "Comment", "description"):
        if meta["prompt"] and meta["steps"]:
            break
        if key in chunks and _maybe_json(chunks[key]) is None:
            _from_a1111(chunks[key], meta, marker("a1111 text"))

    # 5. deep scan of anything left
    if not (meta["prompt"] and meta["steps"] and meta["model"]):
        for key, text in chunks.items():
            obj = _maybe_json(text)
            if obj is not None:
                _deep_scan(obj, meta, marker("deep scan"),
                           allow_prompt=not meta["negative"])

    # tidy up
    meta["sampler"] = meta["sampler"].lower()
    meta["scheduler"] = meta["scheduler"].lower()
    for field in ("steps", "seed"):
        n = _num(meta[field])
        if n is not None and n == int(n):
            meta[field] = str(int(n))
    if meta["prompt"] == meta["negative"]:
        meta["negative"] = ""

    meta["source"] = " + ".join(used) if used else "nothing found"
    return meta


# ==========================================================================
# carrying metadata into a saved copy
# ==========================================================================

# The chunks that carry generation data. Everything else is camera/software
# cruft that a "clean" export should drop.
GEN_CHUNKS = ("workflow", "prompt", "parameters", "Parameters")

# A JPEG APP1 segment cannot exceed 64 KB, and a ComfyUI workflow routinely
# blows past that. We check rather than let the save fail or truncate.
EXIF_LIMIT = 60000

GPS_IFD = 0x8825
EXIF_IFD = 0x8769
INTEROP_IFD = 0xA005
# These hold byte offsets into the source file, not values. Copying them into a
# fresh Exif leaves it pointing at a file it cannot read, so the sub-directories
# are carried across explicitly instead.
IFD_POINTERS = {EXIF_IFD, GPS_IFD, INTEROP_IFD, 0x014A}


def collect_chunks(source_path, mode):
    """Text chunks carried over from the original. mode: all | generation | none"""
    if mode == "none" or not source_path or not os.path.isfile(source_path):
        return {}
    try:
        with Image.open(source_path) as im:
            chunks = read_chunks(im)
    except (OSError, ValueError):
        return {}
    chunks.pop("exif", None)
    if mode == "generation":
        chunks = {k: v for k, v in chunks.items() if k in GEN_CHUNKS}
    return chunks


def _build_png_info(chunks):
    info = PngInfo()
    for key, val in chunks.items():
        if isinstance(val, str) and val:
            try:
                info.add_text(key, val)
            except (ValueError, UnicodeError):
                pass
    return info


def _build_exif(chunks, notes, base=None, strip_gps=True):
    """An EXIF block for a jpeg or webp copy. "Keep everything" starts from
    the file's own EXIF, or camera and date tags the user never touched would
    be quietly dropped; the GPS directory only comes along when asked."""
    exif = Image.Exif()
    if base is not None:
        try:
            for tag, value in base.items():
                if tag not in IFD_POINTERS:
                    exif[tag] = value
            src_sub = dict(base.get_ifd(EXIF_IFD) or {})
            if src_sub:
                exif.get_ifd(EXIF_IFD).update(
                    {t: v for t, v in src_sub.items() if t not in IFD_POINTERS})
            if not strip_gps:
                src_gps = dict(base.get_ifd(GPS_IFD) or {})
                if src_gps:
                    exif.get_ifd(GPS_IFD).update(src_gps)
        except (OSError, ValueError, TypeError, KeyError):
            pass

    # text chunks have no EXIF home of their own, so they go into UserComment
    spill = []
    for key, val in chunks.items():
        if isinstance(val, str) and val:
            spill.append(f"{key}: {val}" if key not in ("parameters", "Parameters") else val)

    if spill:
        blob = "\n".join(spill)
        encoded = b"UNICODE\x00" + blob.encode("utf-16-be", "replace")
        if len(encoded) > EXIF_LIMIT:
            notes.append(
                "Generation data was too large for this format's metadata block "
                "(EXIF caps out at 64 KB) so it was left out. Export as PNG to keep it."
            )
        else:
            exif[0x9286] = encoded
    return exif


# ==========================================================================
# the EXIF tags a photo carries
#
# Tag numbers and every enumerated value below come from the Exif 2.32
# specification, so those are exact. One table names the tags; read_camera
# presents whatever the file has as text, keyed by the table's ``key``.
# ==========================================================================

IFD_MAIN = "0"      # IFD0, the main image directory
IFD_EXIF = "exif"   # the Exif sub-directory at 0x8769
IFD_GPS = "gps"     # the GPS sub-directory at 0x8825

EXIF_FIELDS = [
    # ---- camera body -----------------------------------------------------
    {"key": "make", "tag": 0x010F, "ifd": IFD_MAIN, "type": "str",
     "label": "Make", "section": "Camera"},
    {"key": "model", "tag": 0x0110, "ifd": IFD_MAIN, "type": "str",
     "label": "Model", "section": "Camera"},
    {"key": "software", "tag": 0x0131, "ifd": IFD_MAIN, "type": "str",
     "label": "Software / firmware", "section": "Camera"},
    {"key": "body_serial", "tag": 0xA431, "ifd": IFD_EXIF, "type": "str",
     "label": "Body serial", "section": "Camera"},
    {"key": "host_computer", "tag": 0x013C, "ifd": IFD_MAIN, "type": "str",
     "label": "Host computer", "section": "Camera"},

    # ---- lens ------------------------------------------------------------
    {"key": "lens_make", "tag": 0xA433, "ifd": IFD_EXIF, "type": "str",
     "label": "Lens make", "section": "Lens"},
    {"key": "lens", "tag": 0xA434, "ifd": IFD_EXIF, "type": "str",
     "label": "Lens model", "section": "Lens",
     "hint": "Phones put front/back in here; there is no separate tag for it."},
    {"key": "lens_serial", "tag": 0xA435, "ifd": IFD_EXIF, "type": "str",
     "label": "Lens serial", "section": "Lens"},
    {"key": "focal", "tag": 0x920A, "ifd": IFD_EXIF, "type": "rational",
     "label": "Focal length (mm)", "section": "Lens"},
    {"key": "focal_35mm", "tag": 0xA405, "ifd": IFD_EXIF, "type": "int",
     "label": "35mm equivalent (mm)", "section": "Lens"},
    {"key": "max_aperture", "tag": 0x9205, "ifd": IFD_EXIF, "type": "rational",
     "label": "Max aperture (APEX)", "section": "Lens"},
    {"key": "digital_zoom", "tag": 0xA404, "ifd": IFD_EXIF, "type": "rational",
     "label": "Digital zoom ratio", "section": "Lens"},

    # ---- exposure --------------------------------------------------------
    {"key": "exposure", "tag": 0x829A, "ifd": IFD_EXIF, "type": "rational",
     "label": "Exposure time (s)", "section": "Exposure",
     "hint": "Write it as 1/250 or as 0.004."},
    {"key": "aperture", "tag": 0x829D, "ifd": IFD_EXIF, "type": "rational",
     "label": "F number", "section": "Exposure"},
    {"key": "iso", "tag": 0x8827, "ifd": IFD_EXIF, "type": "int",
     "label": "ISO", "section": "Exposure"},
    {"key": "exposure_bias", "tag": 0x9204, "ifd": IFD_EXIF, "type": "srational",
     "label": "Exposure bias (EV)", "section": "Exposure"},
    {"key": "shutter_value", "tag": 0x9201, "ifd": IFD_EXIF, "type": "srational",
     "label": "Shutter speed (APEX)", "section": "Exposure"},
    {"key": "aperture_value", "tag": 0x9202, "ifd": IFD_EXIF, "type": "rational",
     "label": "Aperture (APEX)", "section": "Exposure"},
    {"key": "brightness", "tag": 0x9203, "ifd": IFD_EXIF, "type": "srational",
     "label": "Brightness (APEX)", "section": "Exposure"},
    {"key": "subject_distance", "tag": 0x9206, "ifd": IFD_EXIF, "type": "rational",
     "label": "Subject distance (m)", "section": "Exposure"},

    # ---- how the shot was taken (all enumerated by the spec) -------------
    {"key": "exposure_program", "tag": 0x8822, "ifd": IFD_EXIF, "type": "enum",
     "label": "Exposure program", "section": "Capture", "options": [
         [0, "Not defined"], [1, "Manual"], [2, "Normal program"],
         [3, "Aperture priority"], [4, "Shutter priority"], [5, "Creative"],
         [6, "Action"], [7, "Portrait"], [8, "Landscape"]]},
    {"key": "metering", "tag": 0x9207, "ifd": IFD_EXIF, "type": "enum",
     "label": "Metering mode", "section": "Capture", "options": [
         [0, "Unknown"], [1, "Average"], [2, "Centre weighted average"],
         [3, "Spot"], [4, "Multi spot"], [5, "Pattern"], [6, "Partial"],
         [255, "Other"]]},
    {"key": "flash", "tag": 0x9209, "ifd": IFD_EXIF, "type": "enum",
     "label": "Flash", "section": "Capture", "options": [
         [0, "Did not fire"], [1, "Fired"], [5, "Fired, no return detected"],
         [7, "Fired, return detected"], [8, "On, did not fire"],
         [9, "On, fired"], [13, "On, fired, no return"],
         [15, "On, fired, return detected"], [16, "Off, did not fire"],
         [24, "Auto, did not fire"], [25, "Auto, fired"],
         [29, "Auto, fired, no return"], [31, "Auto, fired, return detected"],
         [32, "No flash function"]]},
    {"key": "white_balance", "tag": 0xA403, "ifd": IFD_EXIF, "type": "enum",
     "label": "White balance", "section": "Capture", "options": [
         [0, "Auto"], [1, "Manual"]]},
    {"key": "exposure_mode", "tag": 0xA402, "ifd": IFD_EXIF, "type": "enum",
     "label": "Exposure mode", "section": "Capture", "options": [
         [0, "Auto"], [1, "Manual"], [2, "Auto bracket"]]},
    {"key": "light_source", "tag": 0x9208, "ifd": IFD_EXIF, "type": "enum",
     "label": "Light source", "section": "Capture", "options": [
         [0, "Unknown"], [1, "Daylight"], [2, "Fluorescent"],
         [3, "Tungsten"], [4, "Flash"], [9, "Fine weather"],
         [10, "Cloudy weather"], [11, "Shade"], [12, "Daylight fluorescent"],
         [13, "Day white fluorescent"], [14, "Cool white fluorescent"],
         [15, "White fluorescent"], [17, "Standard light A"],
         [18, "Standard light B"], [19, "Standard light C"], [20, "D55"],
         [21, "D65"], [22, "D75"], [23, "D50"], [24, "ISO studio tungsten"],
         [255, "Other"]]},
    {"key": "scene_capture", "tag": 0xA406, "ifd": IFD_EXIF, "type": "enum",
     "label": "Scene type", "section": "Capture", "options": [
         [0, "Standard"], [1, "Landscape"], [2, "Portrait"], [3, "Night"]]},
    {"key": "sensing_method", "tag": 0xA217, "ifd": IFD_EXIF, "type": "enum",
     "label": "Sensing method", "section": "Capture", "options": [
         [1, "Not defined"], [2, "One chip colour area"],
         [3, "Two chip colour area"], [4, "Three chip colour area"],
         [5, "Colour sequential area"], [7, "Trilinear"],
         [8, "Colour sequential linear"]]},
    {"key": "custom_rendered", "tag": 0xA401, "ifd": IFD_EXIF, "type": "enum",
     "label": "Custom rendered", "section": "Capture", "options": [
         [0, "Normal"], [1, "Custom"]]},
    {"key": "gain_control", "tag": 0xA407, "ifd": IFD_EXIF, "type": "enum",
     "label": "Gain control", "section": "Capture", "options": [
         [0, "None"], [1, "Low gain up"], [2, "High gain up"],
         [3, "Low gain down"], [4, "High gain down"]]},
    {"key": "contrast", "tag": 0xA408, "ifd": IFD_EXIF, "type": "enum",
     "label": "Contrast", "section": "Capture", "options": [
         [0, "Normal"], [1, "Soft"], [2, "Hard"]]},
    {"key": "saturation", "tag": 0xA409, "ifd": IFD_EXIF, "type": "enum",
     "label": "Saturation", "section": "Capture", "options": [
         [0, "Normal"], [1, "Low"], [2, "High"]]},
    {"key": "sharpness", "tag": 0xA40A, "ifd": IFD_EXIF, "type": "enum",
     "label": "Sharpness", "section": "Capture", "options": [
         [0, "Normal"], [1, "Soft"], [2, "Hard"]]},
    {"key": "subject_range", "tag": 0xA40C, "ifd": IFD_EXIF, "type": "enum",
     "label": "Subject distance range", "section": "Capture", "options": [
         [0, "Unknown"], [1, "Macro"], [2, "Close view"], [3, "Distant view"]]},

    # ---- image ------------------------------------------------------------
    {"key": "orientation", "tag": 0x0112, "ifd": IFD_MAIN, "type": "enum",
     "label": "Orientation", "section": "Image", "options": [
         [1, "Normal"], [2, "Mirrored"], [3, "Rotated 180"],
         [4, "Mirrored, rotated 180"], [5, "Mirrored, rotated 90 CCW"],
         [6, "Rotated 90 CW"], [7, "Mirrored, rotated 90 CW"],
         [8, "Rotated 90 CCW"]]},
    {"key": "colour_space", "tag": 0xA001, "ifd": IFD_EXIF, "type": "enum",
     "label": "Colour space", "section": "Image", "options": [
         [1, "sRGB"], [65535, "Uncalibrated"]]},
    {"key": "x_resolution", "tag": 0x011A, "ifd": IFD_MAIN, "type": "rational",
     "label": "X resolution", "section": "Image"},
    {"key": "y_resolution", "tag": 0x011B, "ifd": IFD_MAIN, "type": "rational",
     "label": "Y resolution", "section": "Image"},
    {"key": "resolution_unit", "tag": 0x0128, "ifd": IFD_MAIN, "type": "enum",
     "label": "Resolution unit", "section": "Image", "options": [
         [1, "None"], [2, "Inches"], [3, "Centimetres"]]},

    # ---- when -------------------------------------------------------------
    {"key": "date_taken", "tag": 0x9003, "ifd": IFD_EXIF, "type": "str",
     "label": "Date taken", "section": "Dates",
     "hint": "EXIF format is YYYY:MM:DD HH:MM:SS."},
    {"key": "date_digitised", "tag": 0x9004, "ifd": IFD_EXIF, "type": "str",
     "label": "Date digitised", "section": "Dates"},
    {"key": "date_modified", "tag": 0x0132, "ifd": IFD_MAIN, "type": "str",
     "label": "File date", "section": "Dates"},
    {"key": "offset_time_original", "tag": 0x9011, "ifd": IFD_EXIF, "type": "str",
     "label": "UTC offset (taken)", "section": "Dates",
     "hint": "Real files carry all three offsets and they always match."},
    {"key": "offset_time_digitised", "tag": 0x9012, "ifd": IFD_EXIF, "type": "str",
     "label": "UTC offset (digitised)", "section": "Dates"},
    {"key": "components", "tag": 0x9101, "ifd": IFD_EXIF, "type": "bytes4",
     "label": "Components", "section": "Camera",
     "hint": "1 2 3 0 means YCbCr. Present in essentially every camera file."},
    {"key": "flashpix", "tag": 0xA000, "ifd": IFD_EXIF, "type": "version",
     "label": "FlashPix version", "section": "Camera", "hint": "Always 0100."},
    {"key": "ycbcr_positioning", "tag": 0x0213, "ifd": IFD_MAIN, "type": "enum",
     "label": "YCbCr positioning", "section": "Image",
     "options": [[1, "Centred"], [2, "Co-sited"]]},
    {"key": "gps_speed_ref", "tag": 0x000C, "ifd": IFD_GPS, "type": "choice",
     "label": "Speed unit", "section": "Location",
     "options": [["K", "km/h"], ["M", "mph"], ["N", "knots"]]},
    {"key": "gps_speed", "tag": 0x000D, "ifd": IFD_GPS, "type": "rational",
     "label": "Speed", "section": "Location"},
    {"key": "gps_accuracy", "tag": 0x001F, "ifd": IFD_GPS, "type": "rational",
     "label": "Position error (m)", "section": "Location"},
    {"key": "gps_dest_bearing_ref", "tag": 0x0017, "ifd": IFD_GPS, "type": "choice",
     "label": "Bearing is", "section": "Location",
     "options": [["T", "True north"], ["M", "Magnetic north"]]},
    {"key": "gps_dest_bearing", "tag": 0x0018, "ifd": IFD_GPS, "type": "rational",
     "label": "Destination bearing", "section": "Location"},
    {"key": "offset_time", "tag": 0x9010, "ifd": IFD_EXIF, "type": "str",
     "label": "UTC offset", "section": "Dates",
     "hint": "Such as +01:00. Filled in for you when you set the date taken."},

    # ---- where -----------------------------------------------------------
    # EXIF stores these as degrees/minutes/seconds plus a hemisphere letter.
    # Maps give you decimal degrees, so that is what gets typed and the
    # conversion happens on the way in and out.
    {"key": "latitude", "tag": 0x0002, "ifd": IFD_GPS, "type": "latitude",
     "label": "Latitude", "section": "Location",
     "hint": "Decimal degrees, negative for south. -90 to 90."},
    {"key": "longitude", "tag": 0x0004, "ifd": IFD_GPS, "type": "longitude",
     "label": "Longitude", "section": "Location",
     "hint": "Decimal degrees, negative for west. -180 to 180."},
    {"key": "altitude", "tag": 0x0006, "ifd": IFD_GPS, "type": "altitude",
     "label": "Altitude (m)", "section": "Location",
     "hint": "Negative means below sea level."},
    {"key": "direction", "tag": 0x0011, "ifd": IFD_GPS, "type": "rational",
     "label": "Camera direction", "section": "Location",
     "hint": "Degrees clockwise from north, 0 to 360."},
    {"key": "direction_ref", "tag": 0x0010, "ifd": IFD_GPS, "type": "choice",
     "label": "Direction is", "section": "Location",
     "options": [["T", "True north"], ["M", "Magnetic north"]]},
    {"key": "gps_date", "tag": 0x001D, "ifd": IFD_GPS, "type": "str",
     "label": "GPS date (UTC)", "section": "Location",
     "hint": "YYYY:MM:DD, in UTC rather than local time."},
    {"key": "gps_time", "tag": 0x0007, "ifd": IFD_GPS, "type": "time",
     "label": "GPS time (UTC)", "section": "Location", "hint": "HH:MM:SS, in UTC."},
    {"key": "map_datum", "tag": 0x0012, "ifd": IFD_GPS, "type": "str",
     "label": "Map datum", "section": "Location",
     "hint": "Almost always WGS-84."},

    # ---- the structural tags a real file always carries ------------------
    {"key": "exif_version", "tag": 0x9000, "ifd": IFD_EXIF, "type": "version",
     "label": "EXIF version", "section": "Camera",
     "hint": "Almost every real file says 0232 or 0231. Its absence is one of "
             "the first things a metadata viewer flags."},
    {"key": "subsec_original", "tag": 0x9291, "ifd": IFD_EXIF, "type": "str",
     "label": "Sub-second (taken)", "section": "Dates",
     "hint": "Fractions of a second, such as 47. Phones almost always write it."},
    {"key": "subsec_digitised", "tag": 0x9292, "ifd": IFD_EXIF, "type": "str",
     "label": "Sub-second (digitised)", "section": "Dates"},
    {"key": "image_unique_id", "tag": 0xA420, "ifd": IFD_EXIF, "type": "str",
     "label": "Image unique ID", "section": "Camera",
     "hint": "A 32 character hex identifier, one per shot."},
    {"key": "owner_name", "tag": 0xA430, "ifd": IFD_EXIF, "type": "str",
     "label": "Camera owner", "section": "Camera"},
    {"key": "lens_spec", "tag": 0xA432, "ifd": IFD_EXIF, "type": "quad",
     "label": "Lens specification", "section": "Lens",
     "hint": "Min focal, max focal, min f, max f. Such as 24/70/2.8/2.8."},
    {"key": "rating", "tag": 0x4746, "ifd": IFD_MAIN, "type": "enum",
     "label": "Rating (stars)", "section": "Image", "options": [
         [0, "None"], [1, "1 star"], [2, "2 stars"], [3, "3 stars"],
         [4, "4 stars"], [5, "5 stars"]],
     "hint": "What Windows and Lightroom show as stars."},
    {"key": "rating_percent", "tag": 0x4749, "ifd": IFD_MAIN, "type": "int",
     "label": "Rating (percent)", "section": "Image"},
    {"key": "scene_type", "tag": 0xA301, "ifd": IFD_EXIF, "type": "byte_enum",
     "label": "Scene type", "section": "Capture", "options": [
         [1, "Directly photographed"]]},
    {"key": "file_source", "tag": 0xA300, "ifd": IFD_EXIF, "type": "byte_enum",
     "label": "File source", "section": "Capture", "options": [
         [1, "Film scanner"], [2, "Reflective scanner"], [3, "Digital camera"]]},
    {"key": "sensitivity_type", "tag": 0x8830, "ifd": IFD_EXIF, "type": "enum",
     "label": "Sensitivity type", "section": "Exposure", "options": [
         [0, "Unknown"], [1, "Standard output sensitivity"],
         [2, "Recommended exposure index"], [3, "ISO speed"],
         [4, "SOS and REI"], [5, "SOS and ISO"], [6, "REI and ISO"],
         [7, "SOS, REI and ISO"]]},
    {"key": "xp_title", "tag": 0x9C9B, "ifd": IFD_MAIN, "type": "xp",
     "label": "Windows title", "section": "Image"},
    {"key": "xp_keywords", "tag": 0x9C9E, "ifd": IFD_MAIN, "type": "xp",
     "label": "Windows keywords", "section": "Image",
     "hint": "Semicolon separated, as Windows Explorer writes them."},
]


def _ref_byte(value, default=0):
    """GPSAltitudeRef is a BYTE, so Pillow hands it back as b'\x00'."""
    if isinstance(value, (bytes, bytearray)):
        return value[0] if value else default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _from_dms(dms, ref, negative_refs):
    try:
        degrees, minutes, seconds = (float(part) for part in dms)
    except (TypeError, ValueError):
        return None
    value = degrees + minutes / 60 + seconds / 3600
    if str(ref).strip().upper().startswith(tuple(negative_refs)):
        value = -value
    return value


def _present(field, value):
    """Turn what is in the file into something editable."""
    if value in (None, ""):
        return ""
    if field["type"] == "bytes4":
        raw = value if isinstance(value, (bytes, bytearray)) else bytes(value or b"")
        return " ".join(str(b) for b in raw[:4])
    if field["type"] == "version":
        raw = value if isinstance(value, (bytes, bytearray)) else str(value).encode()
        return raw.decode("ascii", "ignore").strip("\x00")
    if field["type"] == "xp":
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-16-le", "ignore").strip("\x00")
        if isinstance(value, tuple):
            return bytes(value).decode("utf-16-le", "ignore").strip("\x00")
        return str(value)
    if field["type"] == "byte_enum":
        return str(_ref_byte(value))
    if field["type"] == "quad":
        try:
            return " ".join(str(round(float(v), 2)).rstrip("0").rstrip(".") for v in value)
        except (TypeError, ValueError):
            return str(value)
    if field["type"] in ("rational", "srational"):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if field["key"] == "exposure" and 0 < number < 1:
            return f"1/{int(round(1 / number))}"      # photographers read 1/250
        return str(round(number, 6)).rstrip("0").rstrip(".") or "0"
    if field["type"] in ("int", "enum"):
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return str(value)
    return str(value).strip("\x00").strip()


def read_camera(path):
    """The camera tags the file carries, as text, keyed as in EXIF_FIELDS."""
    out = {}
    try:
        with Image.open(path) as img:
            main = img.getexif()
            sub = main.get_ifd(EXIF_IFD)
            gps = main.get_ifd(GPS_IFD) or {}
    except Exception:
        return out

    for field in EXIF_FIELDS:
        if field["ifd"] == IFD_GPS:
            continue
        source = main if field["ifd"] == IFD_MAIN else sub
        shown = _present(field, source.get(field["tag"]))
        if shown != "":
            out[field["key"]] = shown

    if gps:
        lat = _from_dms(gps.get(0x0002), gps.get(0x0001, "N"), ("S",))
        lon = _from_dms(gps.get(0x0004), gps.get(0x0003, "E"), ("W",))
        if lat is not None:
            out["latitude"] = f"{lat:.6f}".rstrip("0").rstrip(".")
        if lon is not None:
            out["longitude"] = f"{lon:.6f}".rstrip("0").rstrip(".")
        if gps.get(0x0006) is not None:
            try:
                alt = float(gps[0x0006])
                if _ref_byte(gps.get(0x0005)) == 1:
                    alt = -alt
                out["altitude"] = str(round(alt, 3)).rstrip("0").rstrip(".") or "0"
            except (TypeError, ValueError):
                pass
        if gps.get(0x0011) is not None:
            try:
                out["direction"] = str(round(float(gps[0x0011]), 3)).rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                pass
        for key, tag in (("direction_ref", 0x0010), ("gps_date", 0x001D),
                         ("map_datum", 0x0012), ("gps_speed_ref", 0x000C),
                         ("gps_dest_bearing_ref", 0x0017)):
            if gps.get(tag):
                out[key] = str(gps[tag]).strip("\x00").strip()
        for key, tag in (("gps_speed", 0x000D), ("gps_accuracy", 0x001F),
                         ("gps_dest_bearing", 0x0018)):
            if gps.get(tag) is not None:
                try:
                    out[key] = str(round(float(gps[tag]), 3)).rstrip("0").rstrip(".") or "0"
                except (TypeError, ValueError):
                    pass
        stamp = gps.get(0x0007)
        if stamp:
            try:
                h, m, sec = (float(x) for x in stamp)
                out["gps_time"] = f"{int(h):02d}:{int(m):02d}:{int(round(sec)):02d}"
            except (TypeError, ValueError):
                pass
    return out


def write_image(im, dest, fmt, quality=92, chunks=None, background="#000000",
                base_exif=None, strip_gps=True, icc_profile=None):
    """Save a PIL image as png, jpeg or webp with the metadata asked for.
    Returns a list of notes worth showing the user."""
    notes = []
    chunks = chunks or {}
    fmt = (fmt or "png").lower()
    if fmt == "jpg":
        fmt = "jpeg"

    if fmt == "jpeg":
        if im.mode in ("RGBA", "LA", "P", "PA"):
            rgba = im.convert("RGBA")
            flat = Image.new("RGB", im.size, background)
            flat.paste(rgba, mask=rgba.split()[-1])
            im = flat
            notes.append(f"JPEG has no transparency, so it was flattened onto {background}.")
        elif im.mode != "RGB":
            im = im.convert("RGB")

    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    icc = icc_profile or im.info.get("icc_profile")
    extra = {"icc_profile": icc} if icc else {}

    if fmt == "png":
        png_kwargs = {}
        if base_exif is not None:
            png_kwargs["exif"] = _build_exif({}, notes, base_exif, strip_gps).tobytes()
        im.save(dest, "PNG", pnginfo=_build_png_info(chunks),
                optimize=True, **png_kwargs, **extra)
    elif fmt == "jpeg":
        exif = _build_exif(chunks, notes, base_exif, strip_gps)
        im.save(dest, "JPEG", quality=int(quality), subsampling=0,
                exif=exif.tobytes(), optimize=True, **extra)
    elif fmt == "webp":
        exif = _build_exif(chunks, notes, base_exif, strip_gps)
        im.save(dest, "WEBP", quality=int(quality), method=4,
                exif=exif.tobytes(), **extra)
    else:
        raise ValueError(f"Unsupported format: {fmt}")
    return notes


def main(argv=None):
    """Print what extract() reads from each file named on the command line."""
    paths = sys.argv[1:] if argv is None else argv
    if not paths:
        sys.exit("Usage: python metadata.py IMAGE [IMAGE ...]")
    for p in paths:
        m = extract(p)
        print(f"\n{os.path.basename(p)}  [{m['source']}]")
        for k in ("prompt", "negative", "steps", "cfg", "sampler", "scheduler",
                  "seed", "model", "loras"):
            v = m[k]
            if v:
                v = str(v)
                print(f"   {k:<10} {v[:100]}{'...' if len(v) > 100 else ''}")


if __name__ == "__main__":
    main()
