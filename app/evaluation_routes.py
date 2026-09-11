"""Evaluation engine routes — Tier 0 (evaluation-engine-phased-plan.md).

Designer track only, one deterministic pass each through First Screen,
Detailed Screen, and Decision. Staff-only, same role gate as the rest of
`/admin`. No deal-shape selection, no notice templates — both deliberately
Tier 2, per the phased plan's justification.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.evaluation_engine import compute_composite, compute_markup, compute_screen_rule
from app.models import DetailedScoreSheet, EvaluationDecision, ScreenAssessment, Submission, User
from app.schemas import (
    DecisionRequest,
    DecisionResponse,
    DetailedScreenRequest,
    DetailedScreenResponse,
    FirstScreenRequest,
    FirstScreenResponse,
)
from app.transitions import record_transition

router = APIRouter(prefix="/internal/submissions", tags=["evaluation"])

_STAFF_ROLES = ("ADMIN", "DESIGN_REVIEWER", "COMMERCIAL_REVIEWER")


def _get_submission_or_404(db: Session, submission_id: str) -> Submission:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    return submission


@router.post("/{submission_id}/first-screen", response_model=FirstScreenResponse)
def first_screen(
    submission_id: str,
    payload: FirstScreenRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_STAFF_ROLES)),
):
    submission = _get_submission_or_404(db, submission_id)

    existing = db.query(ScreenAssessment).filter(ScreenAssessment.submission_id == submission.id).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="First screen already recorded for this submission.",
        )

    reads = {k: v.model_dump() for k, v in payload.reads.items()}
    rule_result = compute_screen_rule(reads)

    db.add(
        ScreenAssessment(
            submission_id=submission.id,
            knockouts=payload.knockouts.model_dump(),
            gates=payload.gates.model_dump(),
            reads=reads,
            rule_result=rule_result,
            reviewer_id=user.id,
        )
    )
    db.commit()

    to_status = "FIRST_SCREEN_GO" if rule_result == "GO" else "FIRST_SCREEN_DECLINE"
    updated = record_transition(
        db,
        submission_id=submission.id,
        to_status=to_status,
        event_type="FIRST_SCREEN_RECORDED",
        actor_id=user.id,
        event_metadata={"rule_result": rule_result},
    )

    return FirstScreenResponse(submission_id=str(submission.id), rule_result=rule_result, status=updated.status)


@router.post("/{submission_id}/detailed-screen", response_model=DetailedScreenResponse)
def detailed_screen(
    submission_id: str,
    payload: DetailedScreenRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_STAFF_ROLES)),
):
    submission = _get_submission_or_404(db, submission_id)

    if submission.status != "FIRST_SCREEN_GO":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Detailed screen requires a first-screen GO — submission is at {submission.status!r}.",
        )
    existing = db.query(DetailedScoreSheet).filter(DetailedScoreSheet.submission_id == submission.id).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Detailed screen already recorded for this submission.",
        )

    markup_pct, band = compute_markup(payload.bom_cost, payload.target_price)
    composite, zone = compute_composite(payload.scores)

    db.add(
        DetailedScoreSheet(
            submission_id=submission.id,
            bom_cost=payload.bom_cost,
            target_price=payload.target_price,
            markup_pct=markup_pct,
            markup_band=band,
            scores=payload.scores,
            composite=composite,
            zone=zone,
            rationale=payload.rationale,
            reviewer_id=user.id,
        )
    )
    db.commit()

    updated = record_transition(
        db,
        submission_id=submission.id,
        to_status="DETAILED_SCREEN_SCORED",
        event_type="DETAILED_SCREEN_RECORDED",
        actor_id=user.id,
        event_metadata={"composite": composite, "zone": zone},
    )

    return DetailedScreenResponse(
        submission_id=str(submission.id),
        markup_pct=markup_pct,
        markup_band=band,
        composite=composite,
        zone=zone,
        status=updated.status,
    )


@router.post("/{submission_id}/decision", response_model=DecisionResponse)
def decision(
    submission_id: str,
    payload: DecisionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_STAFF_ROLES)),
):
    submission = _get_submission_or_404(db, submission_id)

    if submission.status != "DETAILED_SCREEN_SCORED":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Decision requires a scored detailed screen — submission is at {submission.status!r}.",
        )
    existing = db.query(EvaluationDecision).filter(EvaluationDecision.submission_id == submission.id).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Decision already recorded for this submission.",
        )

    db.add(
        EvaluationDecision(
            submission_id=submission.id,
            outcome=payload.outcome,
            rationale=payload.rationale,
            decided_by=user.id,
        )
    )
    db.commit()

    to_status = "DECISION_ADVANCE" if payload.outcome == "ADVANCE" else "DECISION_DECLINE"
    updated = record_transition(
        db,
        submission_id=submission.id,
        to_status=to_status,
        event_type="DECISION_RECORDED",
        actor_id=user.id,
        event_metadata={"outcome": payload.outcome},
    )

    return DecisionResponse(submission_id=str(submission.id), outcome=payload.outcome, status=updated.status)
