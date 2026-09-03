from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, require_role, verify_password
from app.business_days import add_business_days
from app.database import get_db
from app.models import AuditEvent, SLAClock, Submission, SubmissionDetail, User
from app.notifications import notify_sales_contact, send_acknowledgement_email
from app.reference_number import next_reference_number
from app.schemas import (
    BrandRequest,
    BrandResponse,
    DesignerStage1Request,
    DesignerStage1Response,
    LoginRequest,
    LoginResponse,
    ManufacturerRequest,
    ManufacturerResponse,
    PresignUploadRequest,
    SubmissionStatusResponse,
)
from app.status_projection import build_status_projection, format_date
from app.transitions import record_transition
from app.uploads import presign_upload

app = FastAPI(title="Bidso Labs — Internal Review Platform")

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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/admin/config-check")
def config_check(_user: User = Depends(require_role(*("ADMIN",)))):
    # Diagnostic only — reports presence/length, never the actual secret
    # values. Remove once email delivery is confirmed working.
    from app.config import settings
    return {
        "resend_api_key_set": bool(settings.resend_api_key),
        "resend_api_key_length": len(settings.resend_api_key),
        "resend_from_address": settings.resend_from_address,
    }


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


@app.post("/uploads/presign")
def presign(payload: PresignUploadRequest, _user: User = Depends(get_current_user)):
    return presign_upload(
        track=payload.track,
        reference_number=payload.reference_number,
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

    return ManufacturerResponse(reference_number=None, submitted_date=format_date(now), email=payload.email)


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
    return {
        "id": str(submission.id),
        "reference_number": submission.reference_number,
        "track": submission.track,
        "status": submission.status,
        "created_at": submission.created_at.isoformat(),
        "detail": {d.stage: d.data for d in details},
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
    return _ADMIN_HTML


_ADMIN_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Bidso Labs — Internal Review</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; }
  h1 { font-size: 20px; }
  #login { display: flex; gap: 8px; margin-bottom: 24px; }
  input { padding: 8px; border: 1px solid #ccc; border-radius: 4px; }
  button { padding: 8px 16px; border: none; background: #1a1a1a; color: white; border-radius: 4px; cursor: pointer; }
  table { width: 100%; border-collapse: collapse; margin-top: 16px; }
  th, td { text-align: left; padding: 8px; border-bottom: 1px solid #eee; font-size: 14px; }
  tr:hover { background: #f7f7f7; cursor: pointer; }
  .status { font-family: monospace; font-size: 12px; background: #f0f0f0; padding: 2px 6px; border-radius: 3px; }
  #detail { display: none; margin-top: 24px; padding: 16px; background: #fafafa; border-radius: 8px; }
  pre { white-space: pre-wrap; font-size: 12px; background: white; padding: 12px; border-radius: 4px; }
  .back { cursor: pointer; color: #555; margin-bottom: 12px; display: inline-block; }
</style>
</head>
<body>
  <h1>Bidso Labs — Internal Review</h1>
  <div id="login">
    <input id="email" placeholder="email" value="aditya@bidso.com">
    <input id="password" type="password" placeholder="password">
    <button onclick="login()">Log in</button>
    <span id="loginError" style="color:red"></span>
  </div>
  <table id="list" style="display:none">
    <thead><tr><th>Ref #</th><th>Track</th><th>Who</th><th>Status</th><th>Submitted</th></tr></thead>
    <tbody id="listBody"></tbody>
  </table>
  <div id="detail"></div>

<script>
const API = window.location.origin;
let token = localStorage.getItem("bidso_labs_token") || "";

async function login() {
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;
  const res = await fetch(API + "/auth/login", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({email, password})
  });
  if (!res.ok) { document.getElementById("loginError").textContent = "Login failed"; return; }
  const data = await res.json();
  token = data.access_token;
  localStorage.setItem("bidso_labs_token", token);
  document.getElementById("login").style.display = "none";
  loadList();
}

async function loadList() {
  const res = await fetch(API + "/admin/submissions", { headers: { Authorization: "Bearer " + token } });
  if (!res.ok) { document.getElementById("login").style.display = "flex"; return; }
  const rows = await res.json();
  document.getElementById("list").style.display = "table";
  const body = document.getElementById("listBody");
  body.innerHTML = rows.map(r => `<tr onclick="loadDetail('${r.id}')">
    <td>${r.reference_number || "—"}</td><td>${r.track}</td><td>${r.summary || "—"}</td>
    <td><span class="status">${r.status}</span></td><td>${new Date(r.created_at).toLocaleString()}</td>
  </tr>`).join("");
}

async function loadDetail(id) {
  const res = await fetch(API + "/admin/submissions/" + id, { headers: { Authorization: "Bearer " + token } });
  const d = await res.json();
  document.getElementById("list").style.display = "none";
  const el = document.getElementById("detail");
  el.style.display = "block";
  el.innerHTML = `<div class="back" onclick="backToList()">&larr; Back to list</div>
    <h2>${d.reference_number || d.track + " submission"}</h2>
    <p><span class="status">${d.status}</span> — submitted ${new Date(d.created_at).toLocaleString()}</p>
    <h3>Submitted data</h3><pre>${JSON.stringify(d.detail, null, 2)}</pre>
    <h3>Audit trail</h3><pre>${JSON.stringify(d.audit_events, null, 2)}</pre>
    <h3>SLA clocks</h3><pre>${JSON.stringify(d.sla_clocks, null, 2)}</pre>`;
}

function backToList() {
  document.getElementById("detail").style.display = "none";
  document.getElementById("list").style.display = "table";
}

if (token) { document.getElementById("login").style.display = "none"; loadList(); }
</script>
</body>
</html>"""
