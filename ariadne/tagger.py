"""Suggest tags for images.

Four ways to do it, in rising order of cost and falling order of speed:

  prompt     Read the tags out of the generation prompt the image already
             carries. No model, no network, instant, free. For a library of
             generated images this covers most of it.
  ollama     A vision model running on your own machine through Ollama.
             Private and free, but you need Ollama installed and a model
             pulled.
  openai     Anything speaking the OpenAI chat API: OpenAI itself, LM Studio,
             llama.cpp's server, OpenRouter, vLLM.
  anthropic  Claude's messages API.

Nothing here writes tags. It proposes them, and the review screen decides.
"""

import base64
import io
import json
import re
import urllib.error
import urllib.request

from PIL import Image, ImageOps

# ---------------------------------------------------------------------------
# reading tags out of a prompt
# ---------------------------------------------------------------------------

# Words that describe how the picture was made rather than what is in it. They
# are the same in every prompt, so as tags they tell you nothing.
BOILERPLATE = {
    "masterpiece", "best quality", "high quality", "highest quality", "hires",
    "highres", "high resolution", "ultra detailed", "extremely detailed",
    "highly detailed", "detailed", "intricate details", "sharp focus",
    "8k", "4k", "uhd", "hd", "raw photo", "photorealistic", "photo realistic",
    "realistic", "hyperrealistic", "hyper realistic", "professional",
    "award winning", "trending on artstation", "artstation", "cgsociety",
    "unreal engine", "octane render", "rendered", "render", "digital art",
    "concept art", "illustration", "artwork", "wallpaper", "beautiful",
    "stunning", "gorgeous", "perfect", "amazing", "absurdres", "very detailed",
    "cinematic", "cinematic lighting", "dramatic lighting", "studio lighting",
    "volumetric lighting", "global illumination", "ray tracing", "bokeh",
    "depth of field", "film grain", "35mm", "50mm", "dslr", "canon", "nikon",
    "score_9", "score_8_up", "score_7_up", "score_6_up", "source_anime",
    "bad quality", "worst quality", "low quality", "lowres", "jpeg artifacts",
}

WEIGHTS = re.compile(r"[\(\)\[\]\{\}]|:\s*-?\d+(?:\.\d+)?")
EMBEDDING = re.compile(r"<[^>]*>")


def tags_from_prompt(meta, max_tags=14, include_model=False, include_loras=False):
    """Pull the descriptive phrases out of a generation prompt."""
    text = (meta.get("guessed_text") or meta.get("prompt") or "").strip()
    out, seen = [], set()

    if text:
        cleaned = EMBEDDING.sub(" ", text)
        cleaned = WEIGHTS.sub(" ", cleaned)
        for chunk in re.split(r"[,\n]", cleaned):
            phrase = " ".join(chunk.split()).strip(" .-_").lower()
            if not phrase or phrase in seen or phrase in BOILERPLATE:
                continue
            if len(phrase) < 3 or len(phrase) > 52:
                continue
            phrase = re.sub(r"^(?:a|an|the)\s+", "", phrase)
            if len(phrase.split()) > 8:      # a paragraph is not a tag
                continue
            if phrase.replace(".", "").isdigit():
                continue
            seen.add(phrase)
            out.append(phrase)

    if include_model and meta.get("model"):
        stem = re.sub(r"\.(safetensors|ckpt|pt|pth|sft)$", "", str(meta["model"]),
                      flags=re.I)
        stem = stem.replace("\\", "/").split("/")[-1].strip().lower()
        if stem and stem not in seen:
            out.append(stem)
            seen.add(stem)

    if include_loras:
        for lora in (meta.get("loras") or []):
            stem = re.sub(r"\.(safetensors|ckpt|pt|pth|sft)$", "", str(lora),
                          flags=re.I)
            stem = stem.replace("\\", "/").split("/")[-1].strip().lower()
            if stem and stem not in seen:
                out.append(stem)
                seen.add(stem)

    return out[:max_tags]


# ---------------------------------------------------------------------------
# talking to a vision model
# ---------------------------------------------------------------------------

INSTRUCTION = (
    "Look at this image and describe what is actually in it.\n"
    "Reply with a JSON array of {n} short lowercase tags and nothing else. "
    "No prose, no code fence, no explanation.\n"
    "Tag the subject, the setting, the composition and the mood. Do not tag "
    "image quality, resolution, or the fact that it is art.\n"
)

VOCAB_HINT = (
    "Prefer these tags where they fit, so the library stays consistent: {vocab}. "
    "Add new ones only when nothing in that list describes what you see.\n"
)


def _encode(path, side=768, quality=80):
    """A small JPEG. Vision models do not need the full resolution and sending
    it wastes time and, on a paid API, money."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        im.thumbnail((side, side), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _instruction(cfg, vocabulary):
    text = INSTRUCTION.format(n=cfg.get("max_tags", 12))
    if vocabulary:
        text += VOCAB_HINT.format(vocab=", ".join(vocabulary[:60]))
    if cfg.get("extra"):
        text += str(cfg["extra"]).strip() + "\n"
    return text


def _post(url, body, headers, timeout):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def parse_tags(text, limit=20):
    """Models answer with a JSON array most of the time and prose the rest of
    the time, so accept either."""
    if not text:
        return []
    text = str(text).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()

    found = None
    match = re.search(r"\[.*\]", text, re.S)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                found = parsed
        except ValueError:
            found = None
    if found is None:
        text = re.sub(r"^[^,\n:]{0,60}:\s*", "", text.strip())   # "Here are the tags:"
        found = re.split(r"[,\n]", text)

    out, seen = [], set()
    for item in found:
        tag = " ".join(str(item).split()).strip(" .-\"'*•").lower()
        tag = re.sub(r"^(?:a|an|the)\s+", "", tag)
        tag = tag.lstrip("#").strip()
        if not tag or tag in seen or len(tag) > 40 or len(tag.split()) > 4:
            continue
        if tag in BOILERPLATE:
            continue
        seen.add(tag)
        out.append(tag)
    return out[:limit]


def ask_ollama(path, cfg, vocabulary):
    url = (cfg.get("url") or "http://localhost:11434").rstrip("/") + "/api/generate"
    body = {
        "model": cfg.get("model") or "llava",
        "prompt": _instruction(cfg, vocabulary),
        "images": [_encode(path, cfg.get("side", 768))],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    data = _post(url, body, {}, cfg.get("timeout", 120))
    return parse_tags(data.get("response", ""), cfg.get("max_tags", 12))


def ask_openai(path, cfg, vocabulary):
    base = (cfg.get("url") or "https://api.openai.com/v1").rstrip("/")
    url = base + "/chat/completions"
    b64 = _encode(path, cfg.get("side", 768))
    body = {
        "model": cfg.get("model") or "gpt-4o-mini",
        "temperature": 0.2,
        "max_tokens": 300,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": _instruction(cfg, vocabulary)},
            {"type": "image_url",
             "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ]}],
    }
    headers = {}
    if cfg.get("api_key"):
        headers["Authorization"] = "Bearer " + cfg["api_key"]
    data = _post(url, body, headers, cfg.get("timeout", 120))
    choice = (data.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content", "")
    return parse_tags(text, cfg.get("max_tags", 12))


def ask_anthropic(path, cfg, vocabulary):
    base = (cfg.get("url") or "https://api.anthropic.com/v1").rstrip("/")
    url = base + "/messages"
    body = {
        "model": cfg.get("model") or "claude-3-5-haiku-latest",
        "max_tokens": 300,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
                                         "media_type": "image/jpeg",
                                         "data": _encode(path, cfg.get("side", 768))}},
            {"type": "text", "text": _instruction(cfg, vocabulary)},
        ]}],
    }
    headers = {"anthropic-version": "2023-06-01"}
    if cfg.get("api_key"):
        headers["x-api-key"] = cfg["api_key"]
    data = _post(url, body, headers, cfg.get("timeout", 120))
    parts = data.get("content") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    return parse_tags(text, cfg.get("max_tags", 12))


BACKENDS = {"ollama": ask_ollama, "openai": ask_openai, "anthropic": ask_anthropic}


def suggest(path, meta, cfg, vocabulary=None):
    """Tags for one image. Returns (tags, error). An error on one image should
    not stop a run of five hundred, so problems come back rather than raise."""
    backend = (cfg or {}).get("backend") or "prompt"
    vocabulary = vocabulary or []

    if backend == "prompt":
        return tags_from_prompt(
            meta,
            max_tags=cfg.get("max_tags", 12),
            include_model=cfg.get("include_model", False),
            include_loras=cfg.get("include_loras", False),
        ), None

    fn = BACKENDS.get(backend)
    if not fn:
        return [], f"No such tagger: {backend}"
    try:
        return fn(path, cfg, vocabulary), None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        return [], f"{exc.code} from the model: {detail}"
    except urllib.error.URLError as exc:
        return [], f"Could not reach it: {exc.reason}"
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        return [], str(exc)[:200]


def check(cfg):
    """Is this backend reachable and configured? Returns (ok, message)."""
    backend = (cfg or {}).get("backend") or "prompt"
    if backend == "prompt":
        return True, "Reads the prompt already stored in each image."

    if backend == "ollama":
        url = (cfg.get("url") or "http://localhost:11434").rstrip("/") + "/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                names = [m.get("name", "") for m in
                         json.loads(resp.read().decode()).get("models", [])]
        except (OSError, ValueError) as exc:
            return False, (f"Ollama did not answer at {cfg.get('url') or 'localhost:11434'}. "
                           f"Is it running? ({exc})")
        if not names:
            return False, "Ollama is running but has no models. Try: ollama pull llava"
        want = cfg.get("model") or "llava"
        if not any(n.split(":")[0] == want.split(":")[0] for n in names):
            return False, (f"Ollama is running but '{want}' is not pulled. "
                           f"It has: {', '.join(names[:6])}")
        return True, f"Ollama is up with {want}."

    if not cfg.get("api_key"):
        return False, "That service needs an API key."
    return True, "Configured. Nothing is sent until you tag something."
