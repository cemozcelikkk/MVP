"""Disposable HTTP workflow through the production proxy, including multipart upload.

Default target is the isolated local stack. Real deployments require explicit
--allow-remote because this script creates and deletes a synthetic account/spot.
"""

import argparse
import base64
import json
import secrets
import uuid
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:5180")
parser.add_argument("--allow-remote", action="store_true")
args = parser.parse_args()
base = args.base_url.rstrip("/")
if urlparse(base).hostname not in {"localhost", "127.0.0.1"} and not args.allow_remote:
    parser.error("Remote smoke tests require --allow-remote; use a pilot environment")
token = None
results = []


def request(
    path, method="GET", payload=None, data=None, content_type=None, expected=200
):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if payload is not None:
        data = json.dumps(payload).encode()
        content_type = "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    try:
        response = urlopen(
            Request(base + path, data=data, headers=headers, method=method), timeout=30
        )
    except HTTPError as error:
        response = error
    with response:
        body = response.read()
        if response.status != expected:
            raise RuntimeError(
                f"{method} {path}: expected {expected}, got {response.status}"
            )
        if path.startswith("/api/"):
            assert response.headers.get("X-Request-ID"), (
                "Missing request correlation header"
            )
        return (
            json.loads(body)
            if body and response.headers.get_content_type() == "application/json"
            else body
        )


assert b"<html" in request("/").lower()
assert request("/health/ready")["status"] == "ready"
results.append("proxy + static frontend + database readiness")
email = f"smoke-{uuid.uuid4().hex}@karavantr-qa.dev"
password = secrets.token_urlsafe(24)
request(
    "/api/v1/auth/register",
    "POST",
    {"email": email, "password": password, "username": "Pilot Smoke Test"},
    expected=201,
)
spot_id = None
try:
    token = request(
        "/api/v1/auth/login",
        "POST",
        data=urlencode({"username": email, "password": password}).encode(),
        content_type="application/x-www-form-urlencoded",
    )["access_token"]
    assert request("/api/v1/auth/me")["email"] == email
    results.append("register + login + authenticated profile")
    spot = request(
        "/api/v1/spots",
        "POST",
        {
            "title": "Pilot smoke " + uuid.uuid4().hex[:8],
            "category": "wild_camping",
            "coordinates": {"latitude": 38.5, "longitude": 34.5},
            "passability": {"road_type": "asphalt"},
            "amenities": {
                "has_toilet": True,
                "has_trash_bins": True,
                "rule_information_known": True,
                "is_free": False,
                "price_description": "Pilot test",
            },
            "entry_latitude": 38.501,
            "entry_longitude": 34.501,
            "overnight_status": "allowed",
        },
        expected=201,
    )
    spot_id = spot["properties"]["id"]
    updated = request(
        f"/api/v1/spots/{spot_id}",
        "PUT",
        {"approach_description": "Pilot yaklaşım testi"},
    )
    assert updated["properties"]["amenities"]["has_toilet"]
    assert updated["properties"]["approach_description"] == "Pilot yaklaşım testi"
    results.append("spot create + partial update + new amenities")
    boundary = "pilot-" + uuid.uuid4().hex
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII="
    )
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="photo_kind"\r\n\r\nentrance\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="pilot.png"\r\nContent-Type: image/png\r\n\r\n'
        ).encode()
        + png
        + f"\r\n--{boundary}--\r\n".encode()
    )
    photo = request(
        f"/api/v1/spots/{spot_id}/photos",
        "POST",
        data=body,
        content_type="multipart/form-data; boundary=" + boundary,
        expected=201,
    )
    assert photo["photo_kind"] == "entrance"
    assert request(photo["storage_url"])
    results.append("entrance photo upload + persistent media served through proxy")
finally:
    if token:
        if spot_id:
            request(f"/api/v1/spots/{spot_id}", "DELETE", expected=204)
        request(
            "/api/v1/users/me",
            "DELETE",
            {"password": password, "confirmation": "HESABIMI SİL"},
            expected=204,
        )
print(
    json.dumps(
        {"passed": results, "synthetic_account_removed": True},
        ensure_ascii=False,
        indent=2,
    )
)
