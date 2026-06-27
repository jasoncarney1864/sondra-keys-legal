"""
Pure-function text utilities for legal document pre-processing.

These helpers are intentionally framework-free — no Azure SDK, no database,
no Pydantic. AbstractChunker implementations call these from their split_document
methods; nothing else in the stack should depend on them directly.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Matches common legal section openers in contracts and statutes.
# Ordered so the most specific alternatives appear first.
_LEGAL_SECTION_RE = re.compile(
    r"""
    (?:
        (?:ARTICLE|SECTION|EXHIBIT|SCHEDULE|ADDENDUM)   # All-caps structural keywords
        \s+[IVXLCDM\d]+                                 # followed by Roman or Arabic numeral
        |
        (?:Article|Section)                             # Mixed-case variants
        \s+\d+(?:\.\d+)*                                # e.g. Section 12.3.1
        |
        \d+\.\d+(?:\.\d+)*\s+(?=[A-Z])                 # Decimal-numbered paragraphs: 3.2 Term
        |
        (?:WHEREAS|NOW,?\s+THEREFORE|IN\s+WITNESS\s+WHEREOF)  # Recital / execution markers
    )
    """,
    re.VERBOSE | re.MULTILINE,
)

_MULTI_WHITESPACE_RE = re.compile(r"[ \t]{2,}")
_HYPHEN_NEWLINE_RE = re.compile(r"-\n\s*")
_BLANK_LINE_RE = re.compile(r"\n{3,}")


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def split_on_legal_boundaries(text: str) -> list[str]:
    """Split *text* at legal section headers without discarding the header text.

    Each returned segment begins with its own header (if one was matched),
    so downstream chunkers can preserve clause provenance.

    Returns the unsplit text as a single-element list when no legal boundaries
    are detected — the caller should fall back to character-level chunking.
    """
    if not text:
        return []

    matches = list(_LEGAL_SECTION_RE.finditer(text))
    if not matches:
        return [text]

    sections: list[str] = []

    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(preamble)

    for i, match in enumerate(matches):
        segment_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segment = text[match.start() : segment_end].strip()
        if segment:
            sections.append(segment)

    return sections


def normalize_whitespace(text: str) -> str:
    """Collapse extraction artifacts introduced by PDF/DOCX parsers.

    Handles:
    - Soft-hyphen line breaks (``word-\\nbreak`` → ``wordbreak``)
    - Multiple consecutive spaces or tabs
    - More than two consecutive blank lines
    """
    text = _HYPHEN_NEWLINE_RE.sub("", text)
    text = _MULTI_WHITESPACE_RE.sub(" ", text)
    text = _BLANK_LINE_RE.sub("\n\n", text)
    return text.strip()


def estimate_token_count(text: str) -> int:
    """Approximate GPT token count using the 4-chars-per-token heuristic.

    Not suitable for exact budget calculations — use tiktoken for that.
    Useful as a fast guard against obviously oversized chunks.
    """
    return max(1, len(text) // 4)


def char_limit_from_tokens(token_limit: int) -> int:
    """Convert a token budget to a conservative character budget."""
    return token_limit * 4
