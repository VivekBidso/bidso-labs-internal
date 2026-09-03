from datetime import datetime, timedelta

# Per tech-architecture.md's locked default (Stage 0, 2026-09-01): Mon-Fri plus a
# manually-seeded holiday table. No holidays seeded yet — add ISO dates here as
# they're confirmed; the SLA math below already accounts for whatever's in it.
HOLIDAYS: set[str] = set()


def add_business_days(start: datetime, n: int) -> datetime:
    """Return the timestamp `n` business days after `start` (Mon-Fri, minus HOLIDAYS)."""
    current = start
    remaining = n
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5 and current.date().isoformat() not in HOLIDAYS:
            remaining -= 1
    return current
