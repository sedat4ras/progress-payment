"""Text normalisation shared by the alias lookup and the fuzzy matcher.

Accents are folded to ASCII on purpose: field technicians type on keyboards
and phones that may or may not produce them, so "Legionella", "légionella"
and "LEGIONELLA" must all collapse to the same key.
"""

import re
import unicodedata

_PUNCT = re.compile(r"[^a-z0-9]+")

# Filler words a technician writes but that carry no matching signal. Units of
# measure are deliberately absent: "hr" distinguishes a callout from a fixed
# price service, so dropping it would lose real information.
_STOPWORDS = {
    "a", "an", "the", "and", "with", "for", "to", "of", "on", "at", "in",
    "was", "were", "is", "are", "been", "did", "done", "completed", "carried",
    "out", "performed", "please", "note", "x", "no",
}


def normalize(text: str) -> str:
    """Casefold, strip accents, drop punctuation, collapse spaces."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = _PUNCT.sub(" ", folded)
    return " ".join(cleaned.split())


def normalize_for_match(text: str) -> str:
    """Normalisation plus stopword removal, used for fuzzy scoring only.

    Alias lookups deliberately use plain `normalize` so an expert's confirmed
    phrasing is stored verbatim rather than lossily.
    """
    tokens = [t for t in normalize(text).split() if t not in _STOPWORDS]
    return " ".join(tokens) if tokens else normalize(text)
