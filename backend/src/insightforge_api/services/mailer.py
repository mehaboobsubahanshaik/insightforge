"""Notification transport. SMTP (STARTTLS) when SMTP_HOST is set; otherwise a
verifiable dev outbox: every message is recorded in email_outbox AND written
to MAIL_OUTBOX_DIR as an .eml file so delivery is provable locally."""

import os
import pathlib
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import EmailOutbox

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def outbox_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("MAIL_OUTBOX_DIR", "outbox"))


async def send(
    session: AsyncSession, *, tenant_id: uuid.UUID, to_email: str, subject: str,
    body: str, kind: str = "generic", attachment: tuple[str, bytes] | None = None,
) -> EmailOutbox:
    if not _EMAIL_RE.match(to_email or ""):
        raise ValueError(f"Invalid recipient address: {to_email!r}")
    record = EmailOutbox(
        tenant_id=tenant_id, to_email=to_email, subject=subject[:500], body=body,
        kind=kind, attachment_name=attachment[0] if attachment else None,
    )
    session.add(record)
    await session.flush()
    try:
        if os.environ.get("SMTP_HOST"):
            _send_smtp(to_email, subject, body, attachment)
        else:
            _write_eml(record.id, to_email, subject, body, attachment)
        record.status = "sent"
    except Exception:  # noqa: BLE001 - delivery failure must not fail the request
        record.status = "failed"
    return record


def _send_smtp(to_email, subject, body, attachment):
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM", "insightforge@localhost")
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment:
        msg.add_attachment(attachment[1], maintype="application", subtype="pdf",
                           filename=attachment[0])
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", 587))) as s:
        s.starttls()
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)


def _write_eml(record_id, to_email, subject, body, attachment):
    d = outbox_dir()
    d.mkdir(exist_ok=True)
    note = f"\n\n[attachment: {attachment[0]} ({len(attachment[1])} bytes)]" if attachment else ""
    (d / f"{record_id}.eml").write_text(f"To: {to_email}\nSubject: {subject}\n\n{body}{note}")
    if attachment:
        (d / f"{record_id}_{attachment[0]}").write_bytes(attachment[1])
