import pathlib
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth import (
    create_access_token,
    generate_reset_token,
    get_current_user,
    hash_password,
    require_role,
    verify_password,
    verify_reset_token,
)
from app.business_days import add_business_days
from app.config import settings
from app.database import SessionLocal, get_db
from app.evaluation_routes import router as evaluation_router
from app.models import (
    AuditEvent,
    DetailedScoreSheet,
    EvaluationDecision,
    ScreenAssessment,
    SLAClock,
    StageAttachment,
    Submission,
    SubmissionDetail,
    User,
)
from app.notifications import notify_sales_contact, send_acknowledgement_email, send_password_reset_email
from app.reference_number import next_reference_number
from app.schemas import (
    BrandRequest,
    BrandResponse,
    ConfirmAttachmentsRequest,
    ConfirmAttachmentsResponse,
    ConfirmedAttachment,
    DesignerStage1Request,
    DesignerStage1Response,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    ManufacturerRequest,
    ManufacturerResponse,
    PresignUploadRequest,
    PublicPresignRequest,
    ResetPasswordRequest,
    SubmissionStatusResponse,
)
from app.status_projection import build_status_projection, format_date
from app.transitions import record_transition
from app.uploads import TRACK_STAGE, head_object, presign_upload

app = FastAPI(title="Bidso Labs — Internal Review Platform")


@app.on_event("startup")
def _sync_bootstrap_admin() -> None:
    # Re-checked on every boot, not just once at migration time, so setting
    # (or rotating) ADMIN_BOOTSTRAP_EMAIL/ADMIN_BOOTSTRAP_PASSWORD in Render
    # and restarting the service is enough to seed or reset that login — no
    # dependency on migration-history timing. No-op when either is unset.
    if not (settings.admin_bootstrap_email and settings.admin_bootstrap_password):
        return
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == settings.admin_bootstrap_email).first()
        password_hash = hash_password(settings.admin_bootstrap_password)
        if user is None:
            db.add(User(email=settings.admin_bootstrap_email, password_hash=password_hash, role="ADMIN"))
        else:
            user.password_hash = password_hash
        db.commit()
    finally:
        db.close()

# The public intake site is a separate deployable on a different Render
# domain — browsers block cross-origin calls by default, so it has to be
# explicitly allowed here. Scoped to known origins, not a wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://bidso-labs-public.onrender.com",
        "https://labs.bidso.com",
        "http://localhost:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(evaluation_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(user.id, user.role)
    return LoginResponse(access_token=token)


@app.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return {"id": str(user.id), "email": user.email, "role": user.role}


@app.post("/auth/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if user is not None:
        raw_token, token_hash, expires_at = generate_reset_token()
        user.reset_token_hash = token_hash
        user.reset_token_expires_at = expires_at
        db.commit()
        reset_url = f"{settings.app_public_url}/admin/reset-password?token={raw_token}"
        send_password_reset_email(to=user.email, reset_url=reset_url)
    # Same response whether or not the email is registered — don't let this
    # endpoint be used to discover which emails have an account.
    return {"message": "If that email has an account, a reset link has been sent."}


@app.post("/auth/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    invalid = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset link")
    candidates = db.query(User).filter(User.reset_token_hash.isnot(None)).all()
    user = next((u for u in candidates if verify_reset_token(payload.token, u.reset_token_hash)), None)
    if user is None:
        raise invalid
    if user.reset_token_expires_at is None or user.reset_token_expires_at < datetime.now(timezone.utc):
        raise invalid
    user.password_hash = hash_password(payload.new_password)
    user.reset_token_hash = None
    user.reset_token_expires_at = None
    db.commit()
    return {"message": "Password updated."}


@app.post("/uploads/presign")
def presign(payload: PresignUploadRequest, _user: User = Depends(get_current_user)):
    # Staff-side upload path — not wired to any UI yet (Stage 4). Kept for when
    # a reviewer needs to attach something directly to a submission.
    return presign_upload(
        track=payload.track,
        submission_id=payload.reference_number,
        stage=payload.stage,
        filename=payload.filename,
    )


# --- Public intake -----------------------------------------------------------
# Unauthenticated by design (external submitters have no account) — this is the
# narrow, public-only API surface tech-architecture.md describes. It can only
# ever create a submission or read the public status projection, never touch
# internal review state.


@app.post("/public/submissions/designer-stage1", response_model=DesignerStage1Response)
def submit_designer_stage1(payload: DesignerStage1Request, db: Session = Depends(get_db)):
    # The one hard stop on this form (tech-architecture.md: "a flat No... enforced
    # ... no email collected on a hard stop") — the frontend already blocks
    # submission client-side, this is the server-side backstop for a direct call.
    if payload.can_get_release_letter == "No":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Without a release letter from your employer, we can't accept this submission.",
        )

    now = datetime.now(timezone.utc)
    reference_number = next_reference_number(db)

    submission = Submission(
        reference_number=reference_number,
        track="DESIGNER",
        status="STAGE1_SUBMITTED",
    )
    db.add(submission)
    db.flush()

    db.add(SubmissionDetail(submission_id=submission.id, stage="DESIGNER_STAGE_1", data=payload.model_dump()))

    screen_due = add_business_days(now, 10)
    db.add(
        SLAClock(
            submission_id=submission.id,
            clock_type="ACK_48H",
            started_at=now,
            due_at=now + timedelta(hours=48),
            status="MET",
        )
    )
    db.add(
        SLAClock(
            submission_id=submission.id,
            clock_type="SCREEN_10BD",
            started_at=now,
            due_at=screen_due,
            status="ACTIVE",
        )
    )
    db.commit()

    screen_decision_by = format_date(screen_due)
    record_transition(
        db,
        submission_id=submission.id,
        to_status="STAGE1_ACKNOWLEDGED",
        event_type="ACKNOWLEDGEMENT_SENT",
        event_metadata={"email": payload.email},
    )

    send_acknowledgement_email(to=payload.email, reference_number=reference_number, screen_decision_by=screen_decision_by)

    return DesignerStage1Response(
        submission_id=str(submission.id),
        reference_number=reference_number,
        submitted_date=format_date(now),
        screen_decision_by=screen_decision_by,
        email=payload.email,
    )


@app.post("/public/submissions/manufacturer", response_model=ManufacturerResponse)
def submit_manufacturer(payload: ManufacturerRequest, db: Session = Depends(get_db)):
    # No confidentiality, no 24-month clause, no SLA clocks, and — per
    # tech-architecture.md — reference numbers are Designer-track only: "no
    # internal review pipeline was specified for this track (v1 default is a
    # simple internal list with one outcome field)".
    now = datetime.now(timezone.utc)

    submission = Submission(reference_number=None, track="MANUFACTURER", status="REGISTERED")
    db.add(submission)
    db.flush()

    db.add(
        SubmissionDetail(submission_id=submission.id, stage="MANUFACTURER_REGISTRATION", data=payload.model_dump())
    )
    db.commit()

    return ManufacturerResponse(
        submission_id=str(submission.id), reference_number=None, submitted_date=format_date(now), email=payload.email
    )


@app.post("/public/submissions/brand", response_model=BrandResponse)
def submit_brand(payload: BrandRequest, db: Session = Depends(get_db)):
    # "Lead capture only... confirmed explicitly out of the review pipeline."
    now = datetime.now(timezone.utc)

    submission = Submission(reference_number=None, track="BRAND", status="LEAD_CREATED")
    db.add(submission)
    db.flush()

    db.add(SubmissionDetail(submission_id=submission.id, stage="BRAND_ENQUIRY", data=payload.model_dump()))
    db.commit()

    notify_sales_contact(
        company=payload.company,
        contact_name=payload.contact_name,
        email=payload.email,
        looking_for=payload.looking_for,
    )

    return BrandResponse(submitted_date=format_date(now), email=payload.email)


@app.post("/public/uploads/presign")
def public_presign(payload: PublicPresignRequest, db: Session = Depends(get_db)):
    # Unauthenticated by design, same as the rest of /public — a submitter has
    # no account. Track and stage are derived from the submission's own row,
    # never taken from the caller, so a request can't presign into an
    # arbitrary track/stage it doesn't belong to.
    submission = db.get(Submission, payload.submission_id)
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    stage = TRACK_STAGE.get(submission.track)
    if stage is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This track doesn't accept file uploads.")

    return presign_upload(
        track=submission.track,
        submission_id=str(submission.id),
        stage=stage,
        filename=payload.filename,
    )


@app.post("/public/submissions/{submission_id}/attachments/confirm", response_model=ConfirmAttachmentsResponse)
def confirm_attachments(submission_id: str, payload: ConfirmAttachmentsRequest, db: Session = Depends(get_db)):
    # Called after the browser has finished uploading straight to R2 with the
    # presigned POSTs above. Re-checks each key actually landed in the bucket
    # (head_object) before writing a row — a key that was presigned but never
    # uploaded (dropped connection, abandoned form) is silently skipped, not
    # recorded as a phantom attachment.
    if submission_id != payload.submission_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="submission_id mismatch")
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    stage = TRACK_STAGE.get(submission.track)
    if stage is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This track doesn't accept file uploads.")

    expected_prefix = f"{submission.track}/{submission_id}/{stage}/"
    confirmed: list[ConfirmedAttachment] = []
    skipped: list[str] = []

    for key in payload.keys:
        if not key.startswith(expected_prefix):
            skipped.append(key)
            continue
        meta = head_object(key)
        if meta is None:
            skipped.append(key)
            continue
        original_filename = key.rsplit("/", 1)[-1].split("-", 1)[-1]
        db.add(
            StageAttachment(
                submission_id=submission.id,
                stage=stage,
                uploaded_by=None,
                file_key=key,
                original_filename=original_filename,
                content_type=meta["content_type"],
                size_bytes=meta["size_bytes"],
            )
        )
        confirmed.append(
            ConfirmedAttachment(
                file_key=key,
                original_filename=original_filename,
                size_bytes=meta["size_bytes"],
                content_type=meta["content_type"],
            )
        )

    if confirmed:
        db.add(
            AuditEvent(
                submission_id=submission.id,
                event_type="ATTACHMENTS_UPLOADED",
                to_status=submission.status,
                event_metadata={"count": len(confirmed), "keys": [c.file_key for c in confirmed]},
            )
        )
    db.commit()

    return ConfirmAttachmentsResponse(confirmed=confirmed, skipped_keys=skipped)


@app.get("/public/submissions/{reference_number}/status", response_model=SubmissionStatusResponse)
def get_submission_status(reference_number: str, db: Session = Depends(get_db)):
    submission = db.query(Submission).filter(Submission.reference_number == reference_number).first()
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    return build_status_projection(db, submission)


# --- Internal review — list/detail (Stage 2 item 7, minimal v1) --------------
# Server-rendered, not a separate React app yet — the full checklist review
# UI is Stage 4's job. This is enough to see what came in and open one.

_STAFF_ROLES = ("ADMIN", "DESIGN_REVIEWER", "COMMERCIAL_REVIEWER")


@app.get("/admin/submissions")
def list_submissions(db: Session = Depends(get_db), _user: User = Depends(require_role(*_STAFF_ROLES))):
    rows = db.query(Submission).order_by(Submission.created_at.desc()).all()
    out = []
    for s in rows:
        detail = db.query(SubmissionDetail).filter(SubmissionDetail.submission_id == s.id).first()
        summary = None
        if detail:
            d = detail.data
            summary = d.get("full_name") or d.get("legal_entity_name") or d.get("company")
        out.append({
            "id": str(s.id),
            "reference_number": s.reference_number,
            "track": s.track,
            "status": s.status,
            "created_at": s.created_at.isoformat(),
            "summary": summary,
        })
    return out


@app.get("/admin/submissions/{submission_id}")
def get_submission_detail(
    submission_id: str, db: Session = Depends(get_db), _user: User = Depends(require_role(*_STAFF_ROLES))
):
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    details = db.query(SubmissionDetail).filter(SubmissionDetail.submission_id == submission.id).all()
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.submission_id == submission.id)
        .order_by(AuditEvent.created_at)
        .all()
    )
    clocks = db.query(SLAClock).filter(SLAClock.submission_id == submission.id).all()
    attachments = (
        db.query(StageAttachment)
        .filter(StageAttachment.submission_id == submission.id)
        .order_by(StageAttachment.uploaded_at)
        .all()
    )
    screen = db.query(ScreenAssessment).filter(ScreenAssessment.submission_id == submission.id).first()
    score_sheet = db.query(DetailedScoreSheet).filter(DetailedScoreSheet.submission_id == submission.id).first()
    decision = db.query(EvaluationDecision).filter(EvaluationDecision.submission_id == submission.id).first()
    return {
        "id": str(submission.id),
        "reference_number": submission.reference_number,
        "track": submission.track,
        "status": submission.status,
        "created_at": submission.created_at.isoformat(),
        "detail": {d.stage: d.data for d in details},
        "first_screen": (
            {
                "knockouts": screen.knockouts,
                "gates": screen.gates,
                "reads": screen.reads,
                "rule_result": screen.rule_result,
                "created_at": screen.created_at.isoformat(),
            }
            if screen
            else None
        ),
        "detailed_screen": (
            {
                "bom_cost": score_sheet.bom_cost,
                "target_price": score_sheet.target_price,
                "markup_pct": score_sheet.markup_pct,
                "markup_band": score_sheet.markup_band,
                "scores": score_sheet.scores,
                "composite": score_sheet.composite,
                "zone": score_sheet.zone,
                "rationale": score_sheet.rationale,
                "created_at": score_sheet.created_at.isoformat(),
            }
            if score_sheet
            else None
        ),
        "decision": (
            {
                "outcome": decision.outcome,
                "rationale": decision.rationale,
                "decided_at": decision.decided_at.isoformat(),
            }
            if decision
            else None
        ),
        "attachments": [
            {
                "file_key": a.file_key,
                "original_filename": a.original_filename,
                "content_type": a.content_type,
                "size_bytes": a.size_bytes,
                "uploaded_at": a.uploaded_at.isoformat(),
            }
            for a in attachments
        ],
        "audit_events": [
            {
                "event_type": e.event_type,
                "from_status": e.from_status,
                "to_status": e.to_status,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
        "sla_clocks": [
            {"clock_type": c.clock_type, "status": c.status, "due_at": c.due_at.isoformat()} for c in clocks
        ],
    }


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return _render_admin_html()


@app.get("/admin/reset-password", response_class=HTMLResponse)
def admin_reset_password_page():
    return _RESET_PASSWORD_HTML


_ADMIN_HTML_PATH = pathlib.Path(__file__).parent / "admin_ui.html"


def _render_admin_html() -> str:
    # Pre-MVP-only stopgap: if a bootstrap credential is configured (see
    # config.py), prefill and SHOW it in plain text on the login form so
    # there's a working login before forgot-password exists. Once
    # forgot-password is in real use, unset both env vars in Render and
    # this reverts to a normal blank, masked login form automatically.
    bootstrap_active = bool(settings.admin_bootstrap_email and settings.admin_bootstrap_password)
    email_value = settings.admin_bootstrap_email if bootstrap_active else ""
    password_value = settings.admin_bootstrap_password if bootstrap_active else ""
    password_type = "text" if bootstrap_active else "password"
    html = _ADMIN_HTML_PATH.read_text()
    html = html.replace("@@EMAIL_VALUE@@", email_value)
    html = html.replace("@@PASSWORD_VALUE@@", password_value)
    html = html.replace("@@PASSWORD_TYPE@@", password_type)
    return html


_RESET_PASSWORD_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Reset password — Bidso Labs</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 420px; margin: 80px auto; padding: 0 20px; color: #1a1a1a; }
  h1 { font-size: 18px; }
  input { display: block; width: 100%; box-sizing: border-box; padding: 10px; margin: 8px 0; border: 1px solid #ccc; border-radius: 4px; }
  button { padding: 10px 20px; border: none; background: #1a1a1a; color: white; border-radius: 4px; cursor: pointer; }
  #msg { font-size: 13px; margin-top: 12px; }
</style>
</head>
<body>
  <h1>Set a new password</h1>
  <input id="newPassword" type="password" placeholder="New password (min 8 characters)">
  <button onclick="submitReset()">Reset password</button>
  <div id="msg"></div>

<script>
const params = new URLSearchParams(window.location.search);
const token = params.get("token");

async function submitReset() {
  const newPassword = document.getElementById("newPassword").value;
  const msg = document.getElementById("msg");
  if (!token) { msg.textContent = "Missing reset token — use the link from your email."; msg.style.color = "red"; return; }
  const res = await fetch(window.location.origin + "/auth/reset-password", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({token, new_password: newPassword})
  });
  const data = await res.json();
  if (!res.ok) { msg.textContent = data.detail || "Reset failed."; msg.style.color = "red"; return; }
  msg.textContent = "Password updated — you can log in now.";
  msg.style.color = "green";
}
</script>
</body>
</html>"""
