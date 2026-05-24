"""
Prompt-injection detection (FR-26).

Single source of truth for injection patterns. Kept separate from PII
(security/pii.py) because the handling is different:
  - PII   → mask and pass through  ([MASKED])
  - Injection → block entirely     (HTTP 422)
"""

from __future__ import annotations

import re

INJECTION_RE = re.compile(
    r"ignore\s+(all\s+)?previous\s+instructions"
    r"|you\s+are\s+now\s+(an?\s+)?(unrestricted|uncensored|dev)"
    r"|developer\s+mode"
    r"|drop\s+table"
    r"|select\s+\*\s+from"
    r"|/etc/passwd"
    r"|<\s*script"
    r"|base64\s*decode",
    re.IGNORECASE,
)


def is_injection(text: str) -> bool:
    """Return True if *text* matches a known prompt-injection pattern (FR-26)."""
    return bool(INJECTION_RE.search(text))
