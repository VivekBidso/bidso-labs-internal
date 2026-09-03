import json
import logging
import urllib.request

from app.config import settings

logger = logging.getLogger("bidso_labs.notifications")

RESEND_ENDPOINT = "https://api.resend.com/emails"


def _send(*, to: str, subject: str, html: str) -> None:
    """Best-effort send via Resend. No-ops (logs only) until RESEND_API_KEY is set —
    the acknowledgement flow must never fail a submission just because email isn't
    wired up yet. Real failures (bad key, Resend outage) are logged, not raised, for
    the same reason.
    """
    if not settings.resend_api_key:
        logger.info("Resend not configured — skipping email to %s: %s", to, subject)
        return

    body = json.dumps(
        {"from": settings.resend_from_address, "to": [to], "subject": subject, "html": html}
    ).encode()
    request = urllib.request.Request(
        RESEND_ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Content-Type": "application/json",
            # Python's default urllib User-Agent gets blocked by Resend's
            # Cloudflare-fronted API as an obvious bot signature (Cloudflare
            # error 1010) before the request ever reaches Resend itself.
            "User-Agent": "bidso-labs-internal/1.0",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=10)
    except Exception:
        logger.exception("Resend email to %s failed", to)


def send_acknowledgement_email(*, to: str, reference_number: str, screen_decision_by: str) -> None:
    _send(
        to=to,
        subject=f"We've received your submission — {reference_number}",
        html=(
            f"<p>Thanks for submitting to Bidso Labs. Your reference number is "
            f"<strong>{reference_number}</strong>.</p>"
            f"<p>You'll have a first decision by <strong>{screen_decision_by}</strong>.</p>"
        ),
    )


def notify_sales_contact(*, company: str, contact_name: str, email: str, looking_for: str | None) -> None:
    _send(
        to=settings.sales_contact_email,
        subject=f"New brand enquiry — {company}",
        html=(
            f"<p>{contact_name} ({email}) at {company} submitted a brand enquiry.</p>"
            f"<p>{looking_for or 'No detail provided.'}</p>"
        ),
    )
