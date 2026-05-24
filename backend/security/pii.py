"""
PII detection and masking utilities (FR-25a/b/c, FR-27).

Single source of truth for PII patterns used at:
  - Input layer  : api/routes.py  (mask before reaching LLM)
  - Output layer : agents/graph_agent.py  (mask LLM answer before returning to user)
"""

from __future__ import annotations

import re

# Patterns covered:
#   FR-25a  — email address
#   FR-25b  — Russian mobile phone (+7 / 8 prefix)
#   FR-25c  — passport series+number (4+6 digits)
#   FR-25c  — INN (10 or 12 digits)
#   FR-25c  — SNILS (XXX-XXX-XXX-XX)
PII_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"           # email
    r"|(?<!\d)(\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)"  # RU phone
    r"|\b\d{4}\s?\d{6}\b"                                                # passport
    r"|\bИНН\s*\d{10,12}\b"                                              # INN
    r"|\bСНИЛС\s*\d{3}[\s\-]\d{3}[\s\-]\d{3}[\s\-]\d{2}\b",            # SNILS
    re.IGNORECASE,
)

_MASK = "[MASKED]"


def mask_pii(text: str) -> str:
    """Replace all PII occurrences in *text* with ``[MASKED]``."""
    return PII_RE.sub(_MASK, text)


def contains_pii(text: str) -> bool:
    """Return True if *text* contains at least one PII pattern."""
    return bool(PII_RE.search(text))
