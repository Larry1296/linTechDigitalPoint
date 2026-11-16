"""Forgiving name matching for item search: the words typed need not be spelt exactly. Each typed word must be found
in the item's text, either as written or with a small slip (a wrong, missing, extra or swapped letter), and the
closest items come first. client/src/core/text/fuzzy.js matches the same way for lists searched in the browser."""
import re

_SPLIT = re.compile(r"[^0-9a-z]+")


def _words(text):
    return [w for w in _SPLIT.split(str(text or "").lower()) if w]


def _distance(a, b):
    """Letters to change, add, drop or swap to turn a into b (optimal string alignment)."""
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if prev2 is not None and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def _allowed(word):
    return 0 if len(word) <= 2 else 1 if len(word) <= 5 else 2


def _word_score(word, tokens, joined):
    if word in joined:
        return 1.0
    allowed = _allowed(word)
    if not allowed:
        return None
    best = None
    for token in tokens:
        # Compare with the whole word and with its start, so a half-typed word with a slip still finds it.
        d = min(_distance(word, token), _distance(word, token[:len(word)]))
        if d <= allowed and (best is None or d < best):
            best = d
    return None if best is None else 1 - best / (2 * len(word))


def fuzzy_score(query, *texts):
    """None when the item does not match; otherwise 0..1, higher is closer. An empty query matches everything."""
    typed = _words(query)
    if not typed:
        return 1.0
    tokens = [t for text in texts for t in _words(text)]
    joined = " ".join(tokens) + " " + "".join(tokens)
    total = 0.0
    for word in typed:
        score = _word_score(word, tokens, joined)
        if score is None:
            return None
        total += score
    return total / len(typed)
