"""Transactional email, the small way.

Sends via stdlib smtplib when SMTP_HOST is configured; otherwise logs the
message so magic links are usable in dev without any provider account.

# ponytail: no templating, no retries, no queue — one synchronous send. Swap
# the body of send_email() for a provider SDK if/when deliverability matters.
"""

import os
import smtplib
from email.message import EmailMessage

from flask import current_app


def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True if actually handed to an SMTP server."""
    host = os.getenv('SMTP_HOST')
    if not host:
        current_app.logger.info(f"[mailer:dev] To: {to}\nSubject: {subject}\n\n{body}")
        return False

    msg = EmailMessage()
    msg['From'] = os.getenv('SMTP_FROM', 'no-reply@pacemind.app')
    msg['To'] = to
    msg['Subject'] = subject
    msg.set_content(body)

    port = int(os.getenv('SMTP_PORT', '587'))
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        if os.getenv('SMTP_STARTTLS', '1') == '1':
            smtp.starttls()
        user, password = os.getenv('SMTP_USER'), os.getenv('SMTP_PASSWORD')
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)
    return True
