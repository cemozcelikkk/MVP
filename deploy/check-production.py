"""Validate deployment values without displaying secret contents."""

import argparse
import json
import shlex
from pathlib import Path
from urllib.parse import urlparse

parser = argparse.ArgumentParser()
parser.add_argument(
    "--env-file", type=Path, default=Path(__file__).parent / ".env.production"
)
args = parser.parse_args()
values = {}
for line in args.env_file.read_text(encoding="utf-8").splitlines():
    if not line.strip() or line.lstrip().startswith("#"):
        continue
    key, raw = line.split("=", 1)
    parsed = shlex.split(raw, comments=True)
    values[key.strip()] = parsed[0] if parsed else ""
errors = []
for key in (
    "SITE_ADDRESS",
    "ACME_EMAIL",
    "POSTGRES_PASSWORD",
    "SECRET_KEY",
    "FRONTEND_URL",
    "CORS_ORIGINS",
    "SMTP_HOST",
    "SMTP_FROM",
):
    if not values.get(key) or "REPLACE_WITH" in values[key]:
        errors.append(f"{key} must be configured")
if len(values.get("SECRET_KEY", "")) < 48:
    errors.append("SECRET_KEY must contain at least 48 random characters")
if len(values.get("POSTGRES_PASSWORD", "")) < 32:
    errors.append("POSTGRES_PASSWORD must contain at least 32 random characters")
site = values.get("SITE_ADDRESS", "")
if site in {"camp.example.com", "localhost"} or "/" in site or ":" in site:
    errors.append("SITE_ADDRESS must be your public hostname")
origin = values.get("FRONTEND_URL", "")
if origin != "https://" + site:
    errors.append("FRONTEND_URL must match the HTTPS site origin")
try:
    origins = json.loads(values.get("CORS_ORIGINS", "[]"))
    if origins != [origin]:
        errors.append(
            "This single-domain stack expects CORS_ORIGINS to contain only FRONTEND_URL"
        )
except json.JSONDecodeError:
    errors.append("CORS_ORIGINS must be a JSON array")
for key in ("SMTP_USERNAME", "SMTP_PASSWORD"):
    if "REPLACE_WITH" in values.get(key, ""):
        errors.append(
            f"Configure {key}, or explicitly leave it empty for a trusted relay"
        )
if (
    values.get("MAIL_BACKEND") != "smtp"
    or values.get("SMTP_STARTTLS", "").lower() != "true"
):
    errors.append("SMTP with STARTTLS is required")
if values.get("SMTP_USERNAME") and not values.get("SMTP_PASSWORD"):
    errors.append("SMTP_PASSWORD is required when SMTP_USERNAME is set")
if values.get("SMTP_HOST") == "smtp.gmail.com":
    if not values.get("SMTP_USERNAME") or values.get("SMTP_FROM") != values.get(
        "SMTP_USERNAME"
    ):
        errors.append(
            "Gmail pilot expects SMTP_FROM and SMTP_USERNAME to be the same Gmail address"
        )
    if len(values.get("SMTP_PASSWORD", "").replace(" ", "")) != 16:
        errors.append("Gmail requires its 16-character app password")
for key in ("GEOCODER_URL", "ROUTING_URL"):
    parsed = urlparse(values.get(key, ""))
    if parsed.scheme != "https" or not parsed.hostname:
        errors.append(f"{key} must be an HTTPS endpoint")
if errors:
    raise SystemExit("Configuration incomplete:\n- " + "\n- ".join(errors))
print(
    "Production environment preflight passed. DNS, TLS and SMTP delivery still require live verification."
)
