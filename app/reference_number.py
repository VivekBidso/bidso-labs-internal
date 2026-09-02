from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import SequenceCounter


def next_reference_number(db: Session) -> str:
    """Issue the next LABS-YYYY-NNNN, race-safe via SELECT ... FOR UPDATE."""
    year = datetime.now(timezone.utc).year
    key = f"LABS-{year}"

    counter = db.execute(
        text("SELECT key, last_value FROM sequence_counters WHERE key = :key FOR UPDATE"),
        {"key": key},
    ).first()

    if counter is None:
        db.add(SequenceCounter(key=key, last_value=1))
        next_value = 1
    else:
        next_value = counter.last_value + 1
        db.execute(
            text("UPDATE sequence_counters SET last_value = :val WHERE key = :key"),
            {"val": next_value, "key": key},
        )

    db.commit()
    return f"LABS-{year}-{next_value:04d}"
