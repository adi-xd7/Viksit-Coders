"""Tokenisation for BM25 and the documented normalisations for queries and quotes."""

from __future__ import annotations

import re
import unicodedata

_TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")
STOPWORDS = frozenset(
    "a an the of to in on for and or as at by is are was were be been it its this that these those with from "
    "after before into over under than then there their they them he she his her we our you your i not no do "
    "does did has have had will would can could should may might also about which who what when where how".split()
)

# Quote-character variants treated as equal by the citation validator.
_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "`": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"', "«": '"', "»": '"',
})


def _stem(tok: str) -> str:
    """Very light plural/verb stripping so 'exports'/'export' and 'shipped'/'ship' meet."""
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 4 and tok.endswith("ing"):
        return tok[:-3]
    if len(tok) > 4 and tok.endswith("ed"):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def tokenize(text: str) -> list[str]:
    t = unicodedata.normalize("NFKC", text).casefold()
    return [_stem(w) for w in _TOKEN.findall(t) if w not in STOPWORDS]


def normalise_query(q: str) -> str:
    """Cache key form: NFKC, case-folded, whitespace collapsed, outer punctuation stripped.

    Only this exact form is treated as 'the same query'; any change in wording is
    a new query and is executed.
    """
    t = " ".join(unicodedata.normalize("NFKC", q).casefold().split())
    return t.strip(" .,;:!?\"'")


def normalise_quote(text: str) -> str:
    """Citation matching normalisation (documented): NFKC, quote-character variants
    unified, case-folded, whitespace collapsed. Nothing else (no stemming, no
    punctuation removal, no ellipsis skipping)."""
    t = unicodedata.normalize("NFKC", text).translate(_QUOTE_MAP).casefold()
    return " ".join(t.split())
