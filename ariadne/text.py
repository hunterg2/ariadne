"""Text that arrives from outside: request bodies, file names.

SQLite and UTF-8 files refuse a lone surrogate (half of an emoji: a client
that cut a string by UTF-16 code units can send one, and NTFS allows one in
a file name). Here it becomes U+FFFD once, on the way in, instead of an
error in whichever table or file it would have reached.
"""


def encodable(s):
    """Can this text be stored?"""
    try:
        s.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def clean_text(s):
    """``s`` with every lone surrogate replaced by U+FFFD; the same object
    when there is nothing to replace."""
    if encodable(s):
        return s
    return s.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


MAX_DEPTH = 200     # no body the page sends nests past a dozen levels


class TooDeep(ValueError):
    """A body nested past ``MAX_DEPTH``: the parser took it, but what reads
    it (this, the settings coercion, the sidebar cleaner) recurses and would
    fail with a RecursionError somewhere inside a route."""


def scrub(value, depth=0):
    """``value`` with every string inside it cleaned. Dicts and lists are
    edited in place, so a request body Flask has already parsed and cached
    stays the same object."""
    if depth > MAX_DEPTH:
        raise TooDeep("nested too deeply")
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        for key, item in list(value.items()):
            new_key = clean_text(key) if isinstance(key, str) else key
            if new_key is not key:
                del value[key]
            value[new_key] = scrub(item, depth + 1)
        return value
    if isinstance(value, list):
        for i, item in enumerate(value):
            value[i] = scrub(item, depth + 1)
        return value
    return value
