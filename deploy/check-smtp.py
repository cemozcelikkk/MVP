"""Run inside the API container: authenticate first; send only when requested."""

import argparse
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings

parser = argparse.ArgumentParser()
parser.add_argument("--send-to", help="Explicit recipient for one diagnostic email")
args = parser.parse_args()
try:
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as client:
        client.starttls(context=ssl.create_default_context())
        client.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        if args.send_to:
            message = EmailMessage()
            message["From"] = settings.SMTP_FROM
            message["To"] = args.send_to
            message["Subject"] = "KaravanTR pilot — SMTP testi"
            message.set_content(
                "Pilot ortamından Gmail SMTP test iletisi başarıyla gönderildi."
            )
            client.send_message(message)
except (smtplib.SMTPException, OSError) as error:
    raise SystemExit(
        f"SMTP check failed: {type(error).__name__}, code={getattr(error, 'smtp_code', 'n/a')}"
    ) from None
print(
    "SMTP TLS/authentication passed."
    + (
        " Diagnostic message submitted; verify inbox delivery."
        if args.send_to
        else " No message sent."
    )
)
