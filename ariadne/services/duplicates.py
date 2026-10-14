"""Duplicate detection over the index, using the perceptual hash each image
carries in ``meta.phash`` (64 bits as 16 hex characters).

Comparing every pair is fine to a few thousand images and hopeless beyond
that. Each fingerprint is split into four 16-bit bands: two hashes within
Hamming distance d must agree on at least one band to within d // 4 bits
(pigeonhole), so only images whose band values match, or differ in one bit,
need comparing. With 65536 possible band values the candidate lists stay
short even at 200k images, where the old 8-bit banding spent a minute.
Levels looser than seven bits would need wider neighbourhoods, so they
keep the pairwise comparison and are limited to a folder.
"""


from ariadne.db import db
from ariadne.services import tags as tags_svc

# How alike two images have to be: a Hamming distance between fingerprints.
# The strictest level also insists the dimensions and file size match.
LEVELS = [
    {"key": "identical", "d": 0, "label": "Identical",
     "note": "Same fingerprint, same dimensions, same file size. A re-save or a "
             "format change of one picture, not two pictures that look alike."},
    {"key": "nearly", "d": 2, "label": "Nearly identical",
     "note": "A couple of bits apart. Catches a light recompress or a tiny crop."},
    {"key": "very", "d": 4, "label": "Very similar",
     "note": "Small edits: a colour tweak, a watermark added, a minor retouch."},
    {"key": "similar", "d": 6, "label": "Similar",
     "note": "The usual setting. Same scene, noticeably different treatment."},
    {"key": "loose", "d": 10, "label": "Loosely similar",
     "note": "Same composition from a different seed. Expect some false pairs."},
    {"key": "wide", "d": 14, "label": "Same sort of thing",
     "note": "Very broad. Good for sweeping a folder, poor for deleting from."},
]

PAIRWISE_LIMIT = 20_000     # images a loose or wide scan will compare pair by pair
BANDS = 4
BAND_BITS = 16
BAND_MASK = (1 << BAND_BITS) - 1


class TooMany(ValueError):
    """A broad level over more images than pairwise comparison can handle."""


def level(key):
    return next((lvl for lvl in LEVELS if lvl["key"] == key), LEVELS[3])


def _pool(folder, recursive=False):
    from ariadne.services.index import scope_sql
    d = db()
    where = "WHERE i.missing=0 AND length(m.phash)=16"
    args = []
    if folder:
        sql, params = scope_sql(folder, recursive)
        where += f" AND {sql}"
        args.extend(params)
    rows = d.execute(
        f"SELECT i.path, i.name, i.folder, i.width, i.height, i.size, i.ctime, m.phash, "
        f"i.stars, i.rejected FROM images i JOIN meta m ON m.path=i.path {where}",
        args).fetchall()
    return [dict(r) for r in rows]


def _candidates(hashes, threshold):
    """Yield index pairs worth comparing: every pair within ``threshold``
    bits is among them, plus some that are not."""
    n = len(hashes)
    if n < 3000 or threshold > 7:
        for i in range(n):
            for j in range(i + 1, n):
                yield i, j
        return
    radius = threshold // BANDS          # 0 or 1 for the levels that get here
    flips = [1 << k for k in range(BAND_BITS)] if radius else []
    for band in range(BANDS):
        shift = band * BAND_BITS
        buckets = {}
        for i, h in enumerate(hashes):
            buckets.setdefault((h >> shift) & BAND_MASK, []).append(i)
        for value, members in buckets.items():
            for a in range(len(members)):
                for b in range(a + 1, len(members)):
                    yield members[a], members[b]
            for flip in flips:
                other = buckets.get(value ^ flip)
                # each unordered pair of buckets is visited from both sides;
                # keep the visit from the smaller value
                if other and value < value ^ flip:
                    for i in members:
                        for j in other:
                            yield (i, j) if i < j else (j, i)


def keeper(items):
    """Which copy is worth keeping: ratings and tags first (they took your
    time), then resolution, then file size, then the oldest file."""
    def key(i):
        return (-(i["stars"] * 1_000_000 + len(i.get("user_tags") or []) * 100_000),
                -(i["width"] or 0) * (i["height"] or 0), -(i.get("bytes") or 0), i.get("time") or 0)
    return min(items, key=key)


def find_groups(folder=None, level_key="similar", recursive=False):
    lvl = level(level_key)
    threshold, exact = lvl["d"], lvl["key"] == "identical"
    pool = _pool(folder, recursive)
    n = len(pool)
    if n < 2:
        return {"level": lvl, "groups": [], "total": n}
    if threshold > 7 and n > PAIRWISE_LIMIT:
        raise TooMany(f"\"{lvl['label']}\" compares every pair, which is too slow for "
                      f"{n:,} images. Pick a stricter level, or run it on one folder.")

    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[b] = a

    # identical fingerprints are duplicates by definition; join them up front
    # and compare one representative each so flat images do not collapse into
    # one enormous bucket
    def key_of(i):
        p = pool[i]
        return f"{p['phash']}|{p['width']}x{p['height']}|{p['size']}" if exact else p["phash"]

    seen, reps = {}, []
    for i in range(n):
        k = key_of(i)
        if k in seen:
            union(seen[k], i)
        else:
            seen[k] = i
            reps.append(i)

    best = {}
    if not exact:
        hashes = [int(pool[i]["phash"], 16) for i in reps]
        for a, b in _candidates(hashes, threshold):
            dist = (hashes[a] ^ hashes[b]).bit_count()
            if dist > threshold:
                continue
            i, j = reps[a], reps[b]
            union(i, j)
            root = find(i)
            if root not in best or dist < best[root]:
                best[root] = dist

    buckets = {}
    for i in range(n):
        buckets.setdefault(find(i), []).append(pool[i])
    groups = [(root, items) for root, items in buckets.items() if len(items) > 1]

    paths = [p["path"] for _, items in groups for p in items]
    tags = tags_svc.tags_of(paths)
    out = []
    for root, items in groups:
        for p in items:
            p["user_tags"] = tags.get(p["path"], [])
            p["bytes"] = p.pop("size", 0)
            p["time"] = p.pop("ctime", 0)
        out.append({"distance": best.get(root, 0), "items": items, "keep": keeper(items)["path"]})
    out.sort(key=lambda g: -len(g["items"]))

    redundant = sum(len(g["items"]) - 1 for g in out)
    freed = sum(i["bytes"] or 0 for g in out for i in g["items"] if i["path"] != g["keep"])
    return {"level": lvl, "groups": out, "total": n,
            "stats": {"groups": len(out), "images": sum(len(g["items"]) for g in out),
                      "redundant": redundant, "bytes": freed,
                      "pct": round(redundant / max(1, n) * 1000) / 10}}


def unique_prompts(folder, recursive=False):
    """Distinct prompts in a folder with counts, newest first by default."""
    from ariadne.services.index import scope_sql
    where, args = scope_sql(folder, recursive)
    d = db()
    rows = d.execute(
        "SELECT COALESCE(m.prompt,'') text, COUNT(*) n, MAX(i.ctime) newest "
        "FROM images i LEFT JOIN meta m ON m.path=i.path "
        f"WHERE {where} AND i.missing=0 GROUP BY COALESCE(m.prompt,'') ORDER BY n DESC",
        args).fetchall()
    return [{"text": r["text"], "count": r["n"], "newest": r["newest"]} for r in rows]
