import uuid

from sqlalchemy.orm import Session

from app.models import AuditEvent, Submission


def record_transition(
    db: Session,
    *,
    submission_id: uuid.UUID,
    to_status: str,
    event_type: str,
    actor_id: uuid.UUID | None = None,
    event_metadata: dict | None = None,
) -> Submission:
    """The only function allowed to change submissions.status.

    Updates the submission's status and inserts the matching audit row in a
    single transaction — nothing else in this codebase should call
    `submission.status = ...` directly.
    """
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise ValueError(f"Submission {submission_id} not found")

    from_status = submission.status
    submission.status = to_status

    db.add(
        AuditEvent(
            submission_id=submission_id,
            event_type=event_type,
            actor_id=actor_id,
            from_status=from_status,
            to_status=to_status,
            event_metadata=event_metadata or {},
        )
    )

    db.commit()
    db.refresh(submission)
    return submission
