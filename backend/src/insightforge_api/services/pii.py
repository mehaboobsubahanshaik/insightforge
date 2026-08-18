"""PII detection (R1): regex-based scanners over sampled values. Suggests
classification labels — the user approves via governance; nothing is
auto-applied (house rule: AI/automation suggests, humans decide)."""

import re

PATTERNS = {
    "email": re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I),
    "phone": re.compile(r"^\+?[\d\s().-]{10,15}$"),
    "credit_card": re.compile(r"^(?:\d[ -]?){13,19}$"),
    "national_id": re.compile(r"^\d{4}\s?\d{4}\s?\d{4}$"),  # aadhaar-like
    "ip_address": re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$"),
}


def _luhn(s: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", s)]
    if len(digits) < 13:
        return False
    total, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def scan_column(values: list) -> str | None:
    """Return a PII type if >=60% of non-empty sampled values match one."""
    vals = [str(v).strip() for v in values if v not in (None, "")][:200]
    if not vals:
        return None
    for kind, rx in PATTERNS.items():
        hits = sum(1 for v in vals if rx.match(v))
        if kind == "credit_card":
            hits = sum(1 for v in vals if rx.match(v) and _luhn(v))
        if hits / len(vals) >= 0.6:
            return kind
    return None
