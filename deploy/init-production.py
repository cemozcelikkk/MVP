"""Generate an ignored env file without printing credentials or overwriting it."""

import argparse
import json
import os
import re
import secrets
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--domain", required=True)
parser.add_argument("--email", required=True)
parser.add_argument(
    "--smoke", action="store_true", help="Generate local smoke-test settings"
)
args = parser.parse_args()
if (
    not re.fullmatch(
        r"(?=.{1,253}$)[a-zA-Z0-9]+(?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", args.domain
    )
    or "." not in args.domain
):
    parser.error("Use a hostname without protocol, port or path")
if not re.fullmatch(r"[^\s@'\"\n]+@[^\s@'\"\n]+\.[^\s@'\"\n]+", args.email):
    parser.error("Use a valid contact email")
target = Path(__file__).parent / (
    ".env.production-smoke" if args.smoke else ".env.production"
)
origin = "https://" + args.domain
values = {
    "SITE_ADDRESS": args.domain,
    "ACME_EMAIL": args.email,
    "POSTGRES_PASSWORD": secrets.token_urlsafe(36),
    "SECRET_KEY": secrets.token_urlsafe(64),
    "FRONTEND_URL": origin,
    "CORS_ORIGINS": json.dumps([origin]),
    "MAIL_BACKEND": "smtp",
    "SMTP_HOST": "smtp.pilot.test" if args.smoke else "smtp.gmail.com",
    "SMTP_PORT": "587",
    "SMTP_USERNAME": "" if args.smoke else args.email,
    "SMTP_PASSWORD": "" if args.smoke else "REPLACE_WITH_SMTP_PASSWORD",
    "SMTP_FROM": args.email,
    "SMTP_STARTTLS": "true",
    "GEOCODER_URL": "https://nominatim.openstreetmap.org/search",
    "GEOCODER_USER_AGENT": f"KaravanTR-Pilot (contact: {args.email})",
    "ROUTING_URL": "https://router.project-osrm.org/route/v1/driving",
}
if args.smoke:
    values["APP_ENV_FILE"] = target.name
descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
    stream.write("# Generated secrets: do not commit, share or print this file.\n")
    for key, value in values.items():
        stream.write(f"{key}='{value}'\n")
print(f"Created {target.name}. Existing files are never overwritten.")
if not args.smoke:
    print("Set the SMTP fields before deployment. Protect file access on the host.")
