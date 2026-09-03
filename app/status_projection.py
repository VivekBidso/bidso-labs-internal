from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, SLAClock, StageDecision, Submission

# Coarse public stage per internal status — mirrors bidso-labs-public's own
# STAGE_ORDER. Internal-only states (e.g. NDA_PENDING vs. NDA_EXECUTED) collapse
# onto one public label; see tech-architecture.md "Public status page".
COARSE_STAGE = {
    "STAGE1_SUBMITTED": "Received",
    "STAGE1_ACKNOWLEDGED": "Acknowledged",
    "SCREENING_IN_REVIEW": "Screening",
    "SCREEN_REJECTED": "Screening",
    "SCREEN_APPROVED": "Screening",
    "NDA_PENDING": "NDA & detail submission",
    "NDA_EXECUTED": "NDA & detail submission",
    "STAGE2_UNLOCKED": "NDA & detail submission",
    "STAGE2_COMPLETE": "NDA & detail submission",
    "STAGE2_WITHDRAWN_TIMEOUT": "NDA & detail submission",
    "PARALLEL_REVIEW_IN_PROGRESS": "In evaluation",
    "DESIGN_ASSESSMENT_REJECTED": "Decision",
    "COMMERCIAL_REJECTED": "Decision",
    "APPROVED": "Decision",
    "REJECTED": "Decision",
}


def format_date(dt) -> str:
    return dt.strftime("%-d %B %Y")


def build_status_projection(db: Session, submission: Submission) -> dict:
    stage_dates = {"Received": format_date(submission.created_at)}
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.submission_id == submission.id)
        .order_by(AuditEvent.created_at)
    )
    for event in events:
        label = COARSE_STAGE.get(event.to_status)
        if label and label not in stage_dates:
            stage_dates[label] = format_date(event.created_at)

    decision_due_by = None
    active_clock = db.scalars(
        select(SLAClock)
        .where(SLAClock.submission_id == submission.id)
        .where(SLAClock.status == "ACTIVE")
        .order_by(SLAClock.due_at.desc())
    ).first()
    if active_clock:
        decision_due_by = format_date(active_clock.due_at)

    rejection_message = None
    latest_reject = db.scalars(
        select(StageDecision)
        .where(StageDecision.submission_id == submission.id)
        .where(StageDecision.decision_type == "REJECT")
        .order_by(StageDecision.created_at.desc())
    ).first()
    if latest_reject:
        rejection_message = latest_reject.external_message

    return {
        "submitted_date": format_date(submission.created_at),
        "current_stage": COARSE_STAGE.get(submission.status, submission.status),
        "decision_due_by": decision_due_by,
        "rejection_message": rejection_message,
        "stage_dates": stage_dates,
    }
