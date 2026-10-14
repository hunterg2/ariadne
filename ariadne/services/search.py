"""The search query language, translated to SQL over the image index.

    prompt: "red dress" & night; tag: portrait; steps: 20...30
"""

import re

from ariadne import db

_QUOTED = re.compile(r'"([^"]+)"')
_TAG_SHORTHAND = re.compile(r"#([\w-]+)")
_STASH = re.compile(r"\$S(\d+)\$")

# SQLite refuses a LIKE pattern past 50,000 bytes ("pattern too complex"),
# and nobody types a query a tenth of that: the rest is dropped
MAX_QUERY = 4000
# the trigram phrase is a prefix of the needle (a row that holds the whole
# holds the prefix), and a phrase of thousands of trigrams is slow to match
MAX_PHRASE = 200


def parse_search(query):
    rules = {}
    for part in (query or "")[:MAX_QUERY].split(";"):
        if ":" not in part:
            continue
        key, _, raw = part.partition(":")
        key = key.strip().lower()
        strings = []

        def stash(match, strings=strings):        # bound per part, not to the loop's last
            strings.append(match.group(1))
            return f"$S{len(strings) - 1}$"

        clean = _QUOTED.sub(stash, raw.strip())
        groups = []
        for or_part in clean.split("||"):
            ands = []
            for and_part in or_part.split("&"):
                hit = _STASH.search(and_part)
                if hit:
                    ands.append(strings[int(hit.group(1))])
                else:
                    bare = and_part.strip()
                    if bare:
                        ands.append(bare)
            if ands:
                groups.append(ands)
        if groups:
            rules[key] = groups
    return rules


def prepare_query(query):
    return parse_search(_TAG_SHORTHAND.sub(r'tag: "\1"', query or ""))


# --------------------------------------------------------------------------
# the same rules as SQL, for the image index
# --------------------------------------------------------------------------

# query field -> SQL column (i = images, m = meta)
TEXT_COLUMNS = {
    "prompt": "m.prompt", "negative": "m.negative", "title": "i.name",
    "model": "m.model", "folder": "i.folder_name", "sampler": "m.sampler",
    "scheduler": "m.scheduler", "camera": "m.camera_model", "lens": "m.lens",
    "software": "m.software", "label": "r.label", "kind": "i.kind",
}
NUMBER_COLUMNS = {
    "steps": "m.steps", "cfg": "m.cfg", "width": "i.width", "height": "i.height",
    "seed": "m.seed", "stars": "i.stars", "iso": "m.iso",
}


ESCAPE_CHAR = "\\"
LIKE = f"LIKE ? ESCAPE '{ESCAPE_CHAR}'"


def _like_escape(text):
    return (text.replace(ESCAPE_CHAR, ESCAPE_CHAR * 2)
                .replace("%", ESCAPE_CHAR + "%")
                .replace("_", ESCAPE_CHAR + "_"))


def _core(needle):
    """The literal part of a needle, without the ... wildcards."""
    n = str(needle).lower()
    if n.startswith("...") and n.endswith("...") and len(n) > 6:
        return n[3:-3]
    if n.startswith("..."):
        return n[3:]
    if n.endswith("..."):
        return n[:-3]
    return n


def _text_sql(column, needle):
    n = str(needle).lower()
    if n.startswith("...") and n.endswith("...") and len(n) > 6:
        return f"lower({column}) {LIKE}", [f"%{_like_escape(n[3:-3])}%"]
    if n.startswith("..."):
        return f"lower({column}) {LIKE}", [f"%{_like_escape(n[3:])}"]
    if n.endswith("..."):
        return f"lower({column}) {LIKE}", [f"{_like_escape(n[:-3])}%"]
    return f"lower({column}) = ?", [n]


def fts_match(rules):
    """A MATCH expression over the trigram index that every row satisfying
    the rules also satisfies, or "" when no rule can give one.

    Rules are ANDed, so any one prompt or negative rule is enough: a row that
    matches it contains at least one needle from each of its OR groups, and
    the longest needle of each group is the most selective. Needles shorter
    than three characters have no trigrams, so a rule containing one is
    skipped. The LIKE clauses still decide the exact match."""
    if not db.FTS_ENABLED:
        return ""
    for key, column in (("prompt", "prompt"), ("negative", "negative")):
        groups = rules.get(key)
        if not groups:
            continue
        phrases = []
        for group in groups:
            cores = [_core(n) for n in group]
            if not all(len(c) >= 3 for c in cores):
                phrases = []
                break
            best = max(cores, key=len)[:MAX_PHRASE].replace('"', '""')
            phrases.append(f'{column}: "{best}"')
        if phrases:
            return " OR ".join(phrases)
    return ""


def _number_sql(column, needle):
    value = f"CAST({column} AS REAL)"
    present = f"({column} IS NOT NULL AND {column} <> '' AND {column} <> '-')"
    if "..." in needle:
        low, _, high = needle.partition("...")
        parts, params = [present], []
        try:
            if low.strip():
                parts.append(f"{value} >= ?")
                params.append(float(low))
            if high.strip():
                parts.append(f"{value} <= ?")
                params.append(float(high))
        except ValueError:
            return "0", []
        return "(" + " AND ".join(parts) + ")", params
    try:
        return f"({present} AND {value} = ?)", [float(needle)]
    except ValueError:
        return "0", []


def _groups_sql(groups, one):
    """OR across groups, AND within a group. ``one(needle)`` -> (sql, params)."""
    ors, params = [], []
    for group in groups:
        ands = []
        for needle in group:
            sql, p = one(needle)
            ands.append(sql)
            params.extend(p)
        ors.append("(" + " AND ".join(ands) + ")")
    return "(" + " OR ".join(ors) + ")", params


def to_sql(rules):
    """Translate parsed rules into (where, params, match): a WHERE fragment
    over the index join (images i, ratings r, meta m) and, when a prompt or
    negative rule allows it, a MATCH expression for the trigram index that
    the query can be driven from. Unknown fields are ignored."""
    where, params = _where_sql(rules)
    return where, params, (fts_match(rules) if where else "")


def _where_sql(rules):
    clauses, params = [], []
    for key, groups in rules.items():
        if key in TEXT_COLUMNS:
            col = TEXT_COLUMNS[key]
            sql, p = _groups_sql(groups, lambda n, c=col: _text_sql(c, n))
        elif key in NUMBER_COLUMNS:
            col = NUMBER_COLUMNS[key]
            sql, p = _groups_sql(groups, lambda n, c=col: _number_sql(c, n))
        elif key == "tag":
            def one_tag(n):
                inner, ip = _text_sql("t.tag", n)
                return f"EXISTS (SELECT 1 FROM tags t WHERE t.path=i.path AND {inner})", ip
            sql, p = _groups_sql(groups, one_tag)
        elif key == "lora":
            def one_lora(n):
                inner, ip = _text_sql("je.value", n)
                return (f"EXISTS (SELECT 1 FROM json_each(COALESCE(m.loras,'[]')) je "
                        f"WHERE {inner})"), ip
            sql, p = _groups_sql(groups, one_lora)
        elif key == "rejected":
            sql, p = _groups_sql(groups, lambda n: ("i.rejected = ?",
                                                    [1 if str(n).lower() in ("1", "yes", "true") else 0]))
        elif key == "collection":
            def one_col(n):
                inner, ip = _text_sql("c.name", n)
                return (f"EXISTS (SELECT 1 FROM collection_items ci JOIN collections c "
                        f"ON c.id=ci.collection_id WHERE ci.path=i.path AND {inner})"), ip
            sql, p = _groups_sql(groups, one_col)
        else:
            continue
        clauses.append(sql)
        params.extend(p)
    return (" AND ".join(clauses), params) if clauses else ("", [])
