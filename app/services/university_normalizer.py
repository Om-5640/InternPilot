"""Deterministic university name canonicalization for alumni matching."""
from __future__ import annotations

import re

# Map normalized raw variants → canonical form.
# Values must be in the same form the generic fallback produces for the primary name.
# Add entries here to resolve new special cases without touching logic.
ALIAS_MAP: dict[str, str] = {
    # MIT
    "massachusetts institute of technology": "mit",
    # IISc
    "indian institute of science": "iisc bangalore",
    "iisc": "iisc bangalore",
    "iisc bengaluru": "iisc bangalore",
    "indian institute of science bangalore": "iisc bangalore",
    "indian institute of science bengaluru": "iisc bangalore",
    # IIT campus abbreviations (full names handled by pattern expansion)
    "iitb": "iit bombay",
    "iitd": "iit delhi",
    "iitm": "iit madras",
    "iitk": "iit kanpur",
    "iitr": "iit roorkee",
    "iitg": "iit guwahati",
    "iith": "iit hyderabad",
    "iitbhu": "iit bhu",
    "iit varanasi": "iit bhu",
    # NIT Trichy — city name alias
    "nit trichy": "nit tiruchirappalli",
    "national institute of technology trichy": "nit tiruchirappalli",
    # BITS — campus-specific to avoid cross-campus over-merge
    "birla institute of technology and science pilani": "bits pilani",
    "birla institute of technology and science hyderabad": "bits hyderabad",
    "birla institute of technology and science goa": "bits goa",
    # Carnegie Mellon
    "cmu": "carnegie mellon",
    "carnegie mellon university": "carnegie mellon",
    # Georgia Tech
    "georgia tech": "georgia institute of technology",
    "gatech": "georgia institute of technology",
    # ETH Zurich
    "eth": "eth zurich",
    "eidgenossische technische hochschule zurich": "eth zurich",
    "swiss federal institute of technology zurich": "eth zurich",
    # UC system
    "uc berkeley": "california berkeley",
    "ucb": "california berkeley",
    "ucla": "california los angeles",
}

_LEADING_THE = re.compile(r"^the\s+")
_LEADING_UNI_OF = re.compile(r"^university\s+of\s+")
_TRAILING_WORD = re.compile(r"\s+(university|college)\s*$")


def _raw(name: str) -> str:
    s = name.lower()
    # Remove dots used in abbreviations before general punctuation cleanup:
    # "I.I.T." → "iit", "U.S.A." → "usa"
    s = re.sub(r"(?<=[a-z])\.(?=[a-z\s])", "", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _expand_patterns(s: str) -> str:
    """Collapse long institute names to their short prefix + city."""
    s = re.sub(r"indian institute of information technology\s+(.+)", r"iiit \1", s)
    s = re.sub(r"indian institute of technology\s+(.+)", r"iit \1", s)
    s = re.sub(r"national institute of technology\s+(.+)", r"nit \1", s)
    return s


def _generic_slug(s: str) -> str:
    """Drop leading 'the'/'university of' and trailing 'university'/'college'."""
    s = _LEADING_THE.sub("", s)
    s = _LEADING_UNI_OF.sub("", s)
    s = _TRAILING_WORD.sub("", s)
    return s.strip()


def canonicalize(name: str) -> str:
    """Return a deterministic canonical string for a university name.

    Equal canonical strings mean the same institution.  Empty input → "".
    """
    if not name or not name.strip():
        return ""
    s = _raw(name)
    if s in ALIAS_MAP:
        return ALIAS_MAP[s]
    s = _expand_patterns(s)
    if s in ALIAS_MAP:
        return ALIAS_MAP[s]
    return _generic_slug(s)
