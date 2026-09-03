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


# Brand colors, matching bidso-labs-public/src/styles/global.css exactly —
# email clients strip <style> blocks and CSS variables unreliably, so
# everything below is inline and hardcoded rather than referencing that file.
_AMBER = "#f46a1f"
_AMBER_SOFT = "#fff1e8"
_INK = "#131316"
_MIST = "#6f6f78"
_SANS = "'Inter',-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"


def _wrap_email(*, preheader: str, body_html: str) -> str:
    """Table-based layout, all-inline styles — the only markup pattern that
    renders consistently across Gmail/Outlook/Apple Mail without a build step.
    """
    return f"""\
<!doctype html>
<html>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:{_SANS};">
  <div style="display:none;max-height:0;overflow:hidden;">{preheader}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #eee;">
        <tr>
          <td style="background:#ffffff;padding:24px 32px;border-bottom:1px solid #f0f0f0;">
            <img src="https://labs.bidso.com/bidso-logo.png" alt="Bidso" height="28" style="height:28px;width:auto;display:block;">
          </td>
        </tr>
        <tr>
          <td style="padding:32px;color:{_INK};font-size:15px;line-height:1.6;">
            {body_html}
          </td>
        </tr>
        <tr>
          <td style="padding:20px 32px;background:#fafafa;border-top:1px solid #eee;color:{_MIST};font-size:12px;line-height:1.5;">
            Bidso Labs — external product &amp; supply submissions.<br>
            This is an automated message, please don't reply directly to this email.
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_acknowledgement_email(*, to: str, reference_number: str, screen_decision_by: str) -> None:
    body = f"""\
        <p style="margin:0 0 16px;">Thanks for submitting to Bidso Labs — we've received it and it's now in our queue for review.</p>
        <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;background:{_AMBER_SOFT};border-radius:8px;margin:0 0 20px;">
          <tr><td style="padding:16px 20px;">
            <div style="color:{_MIST};font-size:12px;text-transform:uppercase;letter-spacing:0.5px;margin:0 0 4px;">Reference number</div>
            <div style="color:{_AMBER};font-size:22px;font-weight:700;">{reference_number}</div>
          </td></tr>
        </table>
        <p style="margin:0 0 8px;">You'll have a first decision by <strong>{screen_decision_by}</strong>.</p>
        <p style="margin:0;color:{_MIST};font-size:13px;">Keep this reference number handy — you can use it to check your submission's status anytime.</p>"""
    _send(
        to=to,
        subject=f"We've received your submission — {reference_number}",
        html=_wrap_email(preheader=f"Your reference number is {reference_number}", body_html=body),
    )


def notify_sales_contact(*, company: str, contact_name: str, email: str, looking_for: str | None) -> None:
    body = f"""\
        <p style="margin:0 0 16px;">New brand enquiry submitted through Bidso Labs.</p>
        <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;">
          <tr><td style="padding:4px 0;color:{_MIST};font-size:13px;width:120px;">Company</td><td style="padding:4px 0;font-weight:600;">{company}</td></tr>
          <tr><td style="padding:4px 0;color:{_MIST};font-size:13px;">Contact</td><td style="padding:4px 0;">{contact_name} ({email})</td></tr>
          <tr><td style="padding:4px 0;color:{_MIST};font-size:13px;vertical-align:top;">Looking for</td><td style="padding:4px 0;">{looking_for or 'No detail provided.'}</td></tr>
        </table>"""
    _send(
        to=settings.sales_contact_email,
        subject=f"New brand enquiry — {company}",
        html=_wrap_email(preheader=f"New brand enquiry from {company}", body_html=body),
    )
