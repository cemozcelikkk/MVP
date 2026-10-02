"""
Süreli canlı saha bildirimlerinin uçtan uca (HTTP -> servis -> gerçek Postgres) testleri.
Saf kurallar `tests/test_live_status_rules.py`'de; burası DB'ye bağlı güvenceleri doğrular:
süre/aktiflik, tekrar engeli (DB dahil), bağımsız sayım, geri çekme, moderasyon ve yetki,
saha güncelliği/uyumluluk entegrasyonu, gizlilik ve bbox sorgu sayısı.
"""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.database import engine
from app.models.dynamic_status import DynamicStatus
from app.models.enums import (
    CrowdLevel,
    LiveReportType,
    PoliceInterventionStatus,
    ReportModerationState,
    UserRole,
    VehicleType,
)
from app.models.live_report_event import LiveReportEvent
from app.schemas.vehicle_profile import VehicleProfileCreate
from app.services.vehicle_profile_service import create_vehicle_profile
from tests.conftest import auth_headers


def live_url(spot_id, suffix: str = "") -> str:
    return f"/api/v1/spots/{spot_id}/live-reports{suffix}"


async def report(client, user, spot_id, report_type: str, hours: int = 12, note: str | None = None):
    body = {"report_type": report_type, "duration_hours": hours}
    if note is not None:
        body["note"] = note
    return await client.post(live_url(spot_id), json=body, headers=auth_headers(user))


async def active(client, spot_id, user=None) -> dict:
    headers = auth_headers(user) if user is not None else {}
    resp = await client.get(live_url(spot_id), headers=headers)
    assert resp.status_code == 200
    return resp.json()


def group_of(body: dict, report_type: str) -> dict | None:
    return next((g for g in body["groups"] if g["report_type"] == report_type), None)


async def freshness_of(client, spot_id, field: str) -> dict:
    body = (await client.get(f"/api/v1/spots/{spot_id}/field-freshness")).json()
    return next(f for f in body["primary"] + body["secondary"] if f["field"] == field)


async def row_count(db_session, spot_id, **filters) -> int:
    await db_session.rollback()  # taze okuma
    stmt = select(func.count()).select_from(DynamicStatus).where(DynamicStatus.spot_id == spot_id)
    for key, value in filters.items():
        stmt = stmt.where(getattr(DynamicStatus, key) == value)
    return (await db_session.execute(stmt)).scalar_one()


async def expire_now(db_session, spot_id) -> None:
    """Bildirimleri 'süresi doldu' durumuna getirir (satırlar silinmez)."""
    await db_session.execute(
        text("UPDATE dynamic_status SET valid_until = now() - interval '1 minute' WHERE spot_id = :s"),
        {"s": spot_id},
    )
    await db_session.commit()


async def promote(db_session, user, role=UserRole.MODERATOR):
    user.role = role
    await db_session.commit()
    await db_session.refresh(user)
    return user


# --- Süre (6/12/24/48) ve aktiflik -------------------------------------------------------------


@pytest.mark.parametrize("hours", [6, 12, 24, 48])
async def test_report_validity_is_computed_by_backend_in_utc(api_client, make_user, make_spot, hours):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    before = datetime.now(UTC)
    resp = await report(api_client, user, spot_id, "road_closed", hours)
    assert resp.status_code == 201
    r = resp.json()["report"]
    starts, ends = datetime.fromisoformat(r["starts_at"]), datetime.fromisoformat(r["expires_at"])
    assert starts.utcoffset() == timedelta(0) and ends.utcoffset() == timedelta(0)  # UTC
    assert ends - starts == timedelta(hours=hours)
    assert before - timedelta(seconds=2) <= starts <= datetime.now(UTC) + timedelta(seconds=2)
    assert r["duration_hours"] == hours and r["outcome"] == "active"


@pytest.mark.parametrize("hours", [0, 5, 7, 13, 72])
async def test_unsupported_durations_are_rejected(api_client, make_user, make_spot, hours):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    assert (await report(api_client, user, spot_id, "road_closed", hours)).status_code == 422


async def test_note_length_is_limited_and_stored_as_plain_text(api_client, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    assert (await report(api_client, user, spot_id, "full", 6, note="x" * 281)).status_code == 422
    resp = await report(api_client, user, spot_id, "full", 6, note="<script>alert(1)</script> köprü kapalı")
    assert resp.status_code == 201
    # Sunucu HTML üretmez/temizlemez; metin olduğu gibi (istemci text olarak render eder) döner.
    assert group_of(await active(api_client, spot_id), "full")["notes"] == ["<script>alert(1)</script> köprü kapalı"]


async def test_expired_report_drops_from_active_but_is_never_deleted(
    api_client, db_session, make_user, make_spot
):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await report(api_client, user, spot_id, "road_closed", 6)
    assert group_of(await active(api_client, spot_id), "road_closed") is not None

    await expire_now(db_session, spot_id)

    body = await active(api_client, spot_id)
    assert body["groups"] == [] and body["summary"]["access"] == "ok" and body["headline"] is None
    assert await row_count(db_session, spot_id) == 1  # fiziksel olarak silinmedi
    history = (await api_client.get(live_url(spot_id, "/history"))).json()
    assert history["total"] == 1 and history["items"][0]["outcome"] == "expired"


async def test_expiry_clears_temporary_effects_everywhere(api_client, db_session, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await report(api_client, user, spot_id, "road_closed", 6)

    detail = (await api_client.get(f"/api/v1/spots/{spot_id}")).json()["properties"]
    assert detail["live_status"]["access"] == "not_recommended"
    assert (await freshness_of(api_client, spot_id, "road_access"))["live_signal"] is not None

    await expire_now(db_session, spot_id)

    detail = (await api_client.get(f"/api/v1/spots/{spot_id}")).json()["properties"]
    assert detail["live_status"]["access"] == "ok" and detail["live_status"]["active_count"] == 0
    assert detail["latest_status"] is None  # eski alan da aktif sonuçlardan düşer
    assert (await freshness_of(api_client, spot_id, "road_access"))["live_signal"] is None


# --- Tekrar engeli ve bağımsız destek ----------------------------------------------------------


async def test_same_user_repeating_same_type_is_rejected_and_does_not_add_support(
    api_client, db_session, make_user, make_spot
):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    assert (await report(api_client, user, spot_id, "fresh_water_unavailable")).status_code == 201
    for _ in range(3):
        assert (await report(api_client, user, spot_id, "fresh_water_unavailable")).status_code == 409

    group = group_of(await active(api_client, spot_id), "fresh_water_unavailable")
    assert group["reporter_count"] == 1 and group["trust_level"] == "single_report"
    assert await row_count(db_session, spot_id) == 1
    # Farklı tür aynı kullanıcı için serbest.
    assert (await report(api_client, user, spot_id, "electricity_unavailable")).status_code == 201


async def test_distinct_users_increase_support_and_trust(api_client, make_user, make_spot):
    users = [await make_user() for _ in range(3)]
    spot_id = await make_spot(created_by=users[0].id)
    levels = []
    for i, user in enumerate(users, start=1):
        await report(api_client, user, spot_id, "road_closed")
        group = group_of(await active(api_client, spot_id), "road_closed")
        assert group["reporter_count"] == i
        levels.append(group["trust_level"])
    assert levels == ["single_report", "supported", "well_supported"]


async def test_report_can_be_resubmitted_after_withdrawal_but_counts_once(
    api_client, db_session, make_user, make_spot
):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    first = (await report(api_client, user, spot_id, "mud_risk")).json()["report"]["id"]
    assert (await api_client.post(f"/api/v1/live-reports/{first}/withdraw", headers=auth_headers(user))).status_code == 200
    assert (await report(api_client, user, spot_id, "mud_risk")).status_code == 201
    assert group_of(await active(api_client, spot_id), "mud_risk")["reporter_count"] == 1
    assert await row_count(db_session, spot_id) == 2  # geçmiş korunur


async def test_concurrent_identical_reports_create_only_one_active_row(
    api_client, db_session, make_user, make_spot
):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    responses = await asyncio.gather(*(report(api_client, user, spot_id, "full", 6) for _ in range(6)))
    codes = sorted(r.status_code for r in responses)
    assert codes == [201] + [409] * 5
    assert await row_count(db_session, spot_id, report_type=LiveReportType.FULL) == 1


async def test_database_constraint_blocks_overlapping_active_reports_without_the_service(
    db_session, make_user, make_spot
):
    """Servis atlansa bile DB aynı kullanıcı+nokta+tür için çakışan aktif pencereyi reddeder."""
    user = await make_user()
    user_id = user.id  # rollback nesneleri expire eder; kimliği önceden al
    spot_id = await make_spot(created_by=user_id)
    now = datetime.now(UTC)

    def new_row(**kw):
        return DynamicStatus(
            spot_id=spot_id,
            reported_by=user_id,
            report_type=LiveReportType.ROAD_CLOSED,
            reported_at=now,
            valid_until=now + timedelta(hours=6),
            **kw,
        )

    db_session.add(new_row())
    await db_session.commit()
    db_session.add(new_row())
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()

    # Pencereler çakışmıyorsa (önceki süresi bitmiş) serbest; eski (legacy) satırlar kapsam dışı.
    later = DynamicStatus(
        spot_id=spot_id,
        reported_by=user_id,
        report_type=LiveReportType.ROAD_CLOSED,
        reported_at=now + timedelta(hours=7),
        valid_until=now + timedelta(hours=13),
    )
    legacy_dup = new_row(is_legacy=True)
    db_session.add_all([later, legacy_dup])
    await db_session.commit()


async def test_row_inserted_already_expired_does_not_break_the_constraint(db_session, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    db_session.add(
        DynamicStatus(
            spot_id=spot_id,
            reported_by=user.id,
            report_type=LiveReportType.ROAD_CLOSED,
            valid_until=datetime.now(UTC) - timedelta(hours=1),  # reported_at (şimdi) < valid_until DEĞİL
        )
    )
    await db_session.commit()  # eskiden DataError: range lower bound must be <= upper bound


# --- Güvenilirlik (yerinde bulunma) -----------------------------------------------------------


async def test_recent_check_in_marks_reporter_on_site_and_raises_trust(
    api_client, make_user, make_spot, make_check_in
):
    on_site, remote = await make_user(), await make_user()
    spot_id = await make_spot(created_by=on_site.id)
    await make_check_in(on_site, spot_id, hours_ago=5)
    await make_check_in(remote, spot_id, hours_ago=100)  # 72 saatten eski -> yerinde SAYILMAZ

    await report(api_client, remote, spot_id, "road_closed")
    solo = group_of(await active(api_client, spot_id), "road_closed")
    assert solo["on_site_count"] == 0 and solo["trust_level"] == "single_report"
    assert "doğrulanmadı" in solo["trust_text"]

    await report(api_client, on_site, spot_id, "road_closed")
    pair = group_of(await active(api_client, spot_id), "road_closed")
    assert pair["reporter_count"] == 2 and pair["on_site_count"] == 1
    assert pair["trust_level"] == "well_supported"


async def test_check_in_is_not_required_to_report(api_client, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    resp = await report(api_client, user, spot_id, "access_difficult")
    assert resp.status_code == 201 and resp.json()["report"]["reporter_on_site"] is False


# --- Geri çekme --------------------------------------------------------------------------------


async def test_user_can_withdraw_own_report_without_physical_deletion(
    api_client, db_session, make_user, make_spot
):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    rid = (await report(api_client, user, spot_id, "electricity_unavailable")).json()["report"]["id"]
    assert group_of(await active(api_client, spot_id, user), "electricity_unavailable")["my_report_id"] == rid

    resp = await api_client.post(f"/api/v1/live-reports/{rid}/withdraw", headers=auth_headers(user))
    assert resp.status_code == 200
    assert resp.json()["report"]["outcome"] == "withdrawn"
    assert resp.json()["live"]["groups"] == []  # yanıt sidebar'ı doğrudan güncelleyebilsin

    assert await row_count(db_session, spot_id, moderation_state=ReportModerationState.WITHDRAWN) == 1
    history = (await api_client.get(live_url(spot_id, "/history"), headers=auth_headers(user))).json()
    assert history["items"][0]["outcome"] == "withdrawn" and history["items"][0]["is_mine"] is True
    events = (await db_session.execute(select(LiveReportEvent))).scalars().all()
    mine = [e for e in events if str(e.report_id) == rid]
    assert len(mine) == 1 and mine[0].actor_id == user.id and mine[0].actor_role is UserRole.USER


async def test_user_cannot_withdraw_someone_elses_report(api_client, make_user, make_spot):
    owner, other = await make_user(), await make_user()
    spot_id = await make_spot(created_by=owner.id)
    rid = (await report(api_client, owner, spot_id, "road_closed")).json()["report"]["id"]

    resp = await api_client.post(f"/api/v1/live-reports/{rid}/withdraw", headers=auth_headers(other))
    assert resp.status_code == 403
    assert group_of(await active(api_client, spot_id), "road_closed") is not None  # hâlâ aktif


async def test_withdrawing_twice_or_an_expired_report_is_a_conflict(
    api_client, db_session, make_user, make_spot
):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    rid = (await report(api_client, user, spot_id, "road_closed")).json()["report"]["id"]
    url = f"/api/v1/live-reports/{rid}/withdraw"
    assert (await api_client.post(url, headers=auth_headers(user))).status_code == 200
    assert (await api_client.post(url, headers=auth_headers(user))).status_code == 409

    rid2 = (await report(api_client, user, spot_id, "mud_risk")).json()["report"]["id"]
    await expire_now(db_session, spot_id)
    assert (await api_client.post(f"/api/v1/live-reports/{rid2}/withdraw", headers=auth_headers(user))).status_code == 409
    assert (await api_client.post(f"/api/v1/live-reports/{uuid_zero()}/withdraw", headers=auth_headers(user))).status_code == 404


def uuid_zero() -> str:
    return "00000000-0000-0000-0000-000000000000"


# --- Moderasyon --------------------------------------------------------------------------------


async def test_moderation_endpoints_are_restricted_to_moderators_and_admins(
    api_client, db_session, make_user, make_spot
):
    user, mod, admin = await make_user(), await make_user(), await make_user()
    await promote(db_session, mod, UserRole.MODERATOR)
    await promote(db_session, admin, UserRole.ADMIN)
    spot_id = await make_spot(created_by=user.id)
    rid = (await report(api_client, user, spot_id, "road_closed")).json()["report"]["id"]
    list_url = f"/api/v1/moderation/live-reports?view=pending&spot_id={spot_id}"
    action_url = f"/api/v1/moderation/live-reports/{rid}/action"
    events_url = f"/api/v1/moderation/live-reports/{rid}/events"

    # Anonim -> 401, sıradan kullanıcı (bildirimin sahibi bile) -> 403
    for method, url in (("get", list_url), ("post", action_url), ("get", events_url)):
        kwargs = {"json": {"action": "confirm"}} if method == "post" else {}
        assert (await getattr(api_client, method)(url, **kwargs)).status_code == 401
        assert (await getattr(api_client, method)(url, headers=auth_headers(user), **kwargs)).status_code == 403

    for staff in (mod, admin):
        assert (await api_client.get(list_url, headers=auth_headers(staff))).status_code == 200
    # Moderatör olmayan biri onay/red yapamaz; durum değişmez.
    assert group_of(await active(api_client, spot_id), "road_closed")["moderation_state"] == "pending"


async def test_moderator_confirm_reject_withdraw_flow_and_audit_trail(
    api_client, db_session, make_user, make_spot
):
    reporter, mod = await make_user(), await make_user("Moderatör Ayşe")
    await promote(db_session, mod)
    spot_id = await make_spot(created_by=reporter.id)
    rid = (await report(api_client, reporter, spot_id, "fire_or_flood_access_issue", 24)).json()["report"]["id"]
    headers = auth_headers(mod)
    action = f"/api/v1/moderation/live-reports/{rid}/action"

    pending = (await api_client.get(f"/api/v1/moderation/live-reports?view=pending&spot_id={spot_id}", headers=headers)).json()
    assert pending["total"] == 1 and pending["items"][0]["reporter_id"] == str(reporter.id)  # moderatör kimliği görür

    confirmed = await api_client.post(action, json={"action": "confirm", "note": "Haber kaynağıyla uyumlu"}, headers=headers)
    assert confirmed.status_code == 200 and confirmed.json()["moderation_state"] == "confirmed"
    assert confirmed.json()["last_event"]["actor_name"] == "Moderatör Ayşe"
    group = group_of(await active(api_client, spot_id), "fire_or_flood_access_issue")
    assert group["moderator_confirmed"] is True and group["trust_level"] == "moderator_confirmed"
    assert group["moderation_state"] == "confirmed"
    assert (await api_client.get(f"/api/v1/moderation/live-reports?view=pending&spot_id={spot_id}", headers=headers)).json()["total"] == 0
    assert (await api_client.get(f"/api/v1/moderation/live-reports?view=active&spot_id={spot_id}", headers=headers)).json()["total"] == 1

    # Onaylı bildirimi tekrar onaylamak geçersiz geçiş.
    assert (await api_client.post(action, json={"action": "confirm"}, headers=headers)).status_code == 409

    rejected = await api_client.post(action, json={"action": "reject", "note": "Yanlış nokta"}, headers=headers)
    assert rejected.status_code == 200 and rejected.json()["moderation_state"] == "rejected"
    assert rejected.json()["outcome"] == "rejected"
    assert (await active(api_client, spot_id))["groups"] == []  # reddedilen aktif sonuçlardan düştü
    closed = (await api_client.get(f"/api/v1/moderation/live-reports?view=closed&spot_id={spot_id}", headers=headers)).json()
    assert closed["total"] == 1
    # Reddedilmiş (terminal) bildirim üzerinde başka işlem yok.
    assert (await api_client.post(action, json={"action": "withdraw"}, headers=headers)).status_code == 409

    events = (await api_client.get(f"/api/v1/moderation/live-reports/{rid}/events", headers=headers)).json()
    assert [(e["from_state"], e["to_state"], e["note"]) for e in events] == [
        ("pending", "confirmed", "Haber kaynağıyla uyumlu"),
        ("confirmed", "rejected", "Yanlış nokta"),
    ]
    assert all(e["actor_id"] == str(mod.id) and e["actor_role"] == "moderator" and e["created_at"] for e in events)
    assert await row_count(db_session, spot_id) == 1  # satır silinmedi


async def test_moderator_can_withdraw_any_report_and_user_actions_appear_in_history(
    api_client, db_session, make_user, make_spot
):
    reporter, mod = await make_user(), await make_user()
    await promote(db_session, mod)
    spot_id = await make_spot(created_by=reporter.id)
    rid = (await report(api_client, reporter, spot_id, "full", 6)).json()["report"]["id"]

    resp = await api_client.post(f"/api/v1/live-reports/{rid}/withdraw", headers=auth_headers(mod))
    assert resp.status_code == 200 and resp.json()["report"]["moderation_state"] == "withdrawn"
    events = (await api_client.get(f"/api/v1/moderation/live-reports/{rid}/events", headers=auth_headers(mod))).json()
    assert events[0]["actor_role"] == "moderator" and events[0]["to_state"] == "withdrawn"


async def test_expired_view_lists_reports_whose_time_ran_out(api_client, db_session, make_user, make_spot):
    reporter, mod = await make_user(), await make_user()
    await promote(db_session, mod)
    spot_id = await make_spot(created_by=reporter.id)
    await report(api_client, reporter, spot_id, "full", 6)
    await expire_now(db_session, spot_id)
    url = "/api/v1/moderation/live-reports?view={}&spot_id=" + str(spot_id)
    assert (await api_client.get(url.format("expired"), headers=auth_headers(mod))).json()["total"] == 1
    assert (await api_client.get(url.format("active"), headers=auth_headers(mod))).json()["total"] == 0
    assert (await api_client.get(url.format("pending"), headers=auth_headers(mod))).json()["total"] == 0


async def test_verifications_audit_stays_moderator_only(api_client, db_session, make_user, make_spot):
    user, mod = await make_user(), await make_user()
    await promote(db_session, mod)
    spot_id = await make_spot(created_by=user.id)
    url = f"/api/v1/spots/{spot_id}/verifications/audit"
    assert (await api_client.get(url)).status_code == 401
    assert (await api_client.get(url, headers=auth_headers(user))).status_code == 403
    assert (await api_client.get(url, headers=auth_headers(mod))).status_code == 200


async def test_creating_a_report_requires_authentication(api_client, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    resp = await api_client.post(live_url(spot_id), json={"report_type": "full", "duration_hours": 6})
    assert resp.status_code == 401
    assert (await report(api_client, user, uuid_zero(), "full", 6)).status_code == 404


# --- Saha güncelliği entegrasyonu --------------------------------------------------------------


async def test_road_closed_attaches_to_road_row_and_old_passable_verification_is_not_green(
    api_client, make_user, make_spot, make_check_in
):
    verifier, reporter = await make_user(), await make_user()
    spot_id = await make_spot(created_by=verifier.id)
    await make_check_in(verifier, spot_id)
    await api_client.post(
        f"/api/v1/spots/{spot_id}/verifications", json={"answers": {"road_access": "passable"}}, headers=auth_headers(verifier)
    )
    assert (await freshness_of(api_client, spot_id, "road_access"))["tone"] == "positive"

    rid = (await report(api_client, reporter, spot_id, "road_closed", 24)).json()["report"]["id"]

    road = await freshness_of(api_client, spot_id, "road_access")
    assert road["status"] == "recently_confirmed"  # doğrulamanın kendi durumu değişmedi
    assert road["live_overrides"] is True and road["tone"] == "negative"  # ama yeşil/baskın DEĞİL
    assert road["live_signal"]["code"] == "LIVE_ROAD_CLOSED" and road["live_signal"]["severity"] == "blocking"
    assert road["live_signal"]["conflicts_with_verification"] is True
    assert road["live_signal"]["report_type"] == "road_closed" and road["live_signal"]["reporter_count"] == 1
    for other in ("overnight", "fresh_water", "electricity", "grey_water", "black_water"):
        assert (await freshness_of(api_client, spot_id, other))["live_signal"] is None

    await api_client.post(f"/api/v1/live-reports/{rid}/withdraw", headers=auth_headers(reporter))
    road = await freshness_of(api_client, spot_id, "road_access")
    assert road["live_signal"] is None and road["tone"] == "positive"  # geçici etki kalktı


@pytest.mark.parametrize(
    ("report_type", "field"),
    [
        ("fresh_water_unavailable", "fresh_water"),
        ("electricity_unavailable", "electricity"),
        ("grey_water_unavailable", "grey_water"),
        ("black_water_unavailable", "black_water"),
        ("overnight_restriction", "overnight"),
        ("official_warning", "overnight"),
        ("fine_reported", "overnight"),
        ("access_difficult", "road_access"),
        ("mud_risk", "road_access"),
        ("fire_or_flood_access_issue", "road_access"),
    ],
)
async def test_each_report_type_lands_on_its_own_freshness_row(api_client, make_user, make_spot, report_type, field):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await report(api_client, user, spot_id, report_type)
    body = (await api_client.get(f"/api/v1/spots/{spot_id}/field-freshness")).json()
    rows = {f["field"]: f for f in body["primary"] + body["secondary"]}
    assert rows[field]["live_signal"]["report_type"] == report_type
    assert [f for f, r in rows.items() if r["live_signal"] is not None] == [field]


async def test_permanent_spot_data_is_never_modified_by_live_reports(api_client, db_session, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    before = (await api_client.get(f"/api/v1/spots/{spot_id}")).json()["properties"]
    for report_type in ("road_closed", "fresh_water_unavailable", "electricity_unavailable", "grey_water_unavailable"):
        await report(api_client, user, spot_id, report_type)
    after = (await api_client.get(f"/api/v1/spots/{spot_id}")).json()["properties"]
    assert after["amenities"] == before["amenities"] and after["passability"] == before["passability"]


# --- Uyumluluk ile kullanılabilirlik ayrımı ----------------------------------------------------


async def test_compatibility_stays_physical_while_live_access_reflects_the_closure(
    api_client, db_session, make_user, make_spot
):
    user, reporter = await make_user(), await make_user()
    await create_vehicle_profile(
        db_session,
        user_id=user.id,
        data=VehicleProfileCreate(name="Ducato", vehicle_type=VehicleType.CAMPERVAN, length_m=6.0, is_active=True),
    )
    spot_id = await make_spot(created_by=user.id)
    url = f"/api/v1/spots/{spot_id}/compatibility"

    calm = (await api_client.get(url, headers=auth_headers(user))).json()
    assert calm["live_access"]["status"] == "ok" and calm["live_access"]["headline"] is None
    physical_status = calm["status"]

    await report(api_client, reporter, spot_id, "road_closed", 24)
    closed = (await api_client.get(url, headers=auth_headers(user))).json()
    assert closed["status"] == physical_status and closed["reasons"] == calm["reasons"]  # fiziksel karar DEĞİŞMEDİ
    live = closed["live_access"]
    assert live["status"] == "not_recommended" and live["headline"] == "Şu anda erişim önerilmiyor"
    assert live["live_text"] == "Ancak yolun şu anda kapalı olduğu bildirildi"
    assert live["physical_text"].startswith("Aracınız")
    assert live["reasons"][0]["report_type"] == "road_closed"

    await expire_now(db_session, spot_id)
    reopened = (await api_client.get(url, headers=auth_headers(user))).json()
    assert reopened["live_access"]["status"] == "ok" and reopened["live_access"]["live_text"] is None
    assert reopened["status"] == physical_status


async def test_difficult_access_and_mud_risk_mean_careful_access(api_client, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await report(api_client, user, spot_id, "mud_risk")
    body = await active(api_client, spot_id)
    assert body["summary"]["access"] == "caution" and body["headline"] == "Dikkatli erişim"
    other = await make_user()
    await report(api_client, other, spot_id, "road_closed")
    assert (await active(api_client, spot_id))["summary"]["access"] == "not_recommended"


async def test_active_list_is_ordered_most_severe_first(api_client, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    for report_type in ("fresh_water_unavailable", "mud_risk", "road_closed", "fine_reported"):
        await report(api_client, user, spot_id, report_type)
    order = [g["report_type"] for g in (await active(api_client, spot_id))["groups"]]
    assert order[:2] == ["road_closed", "fine_reported"]
    assert (await active(api_client, spot_id))["summary"]["top_type"] == "road_closed"


# --- Gizlilik ----------------------------------------------------------------------------------


async def test_public_responses_never_contain_reporter_identity(api_client, db_session, make_user, make_spot, make_check_in):
    user, owner = await make_user("Gizli Kişi"), await make_user()
    spot_id = await make_spot(created_by=owner.id)  # spot sahibi (created_by zaten açık alan) bildirenden FARKLI
    await make_check_in(user, spot_id)
    await report(api_client, user, spot_id, "road_closed", note="kısa not")
    rid = (await report(api_client, user, spot_id, "full", 6)).json()["report"]["id"]
    await api_client.post(f"/api/v1/live-reports/{rid}/withdraw", headers=auth_headers(user))

    bodies = [
        (await api_client.get(live_url(spot_id))).text,
        (await api_client.get(live_url(spot_id, "/history"))).text,
        (await api_client.get(f"/api/v1/spots/{spot_id}")).text,
        (await api_client.get(f"/api/v1/spots/bbox?min_lon=32.99&min_lat=38.99&max_lon=33.01&max_lat=39.01")).text,
    ]
    for body in bodies:
        assert str(user.id) not in body and "Gizli Kişi" not in body
        assert "reporter_id" not in body and "checked_in_at" not in body
    detail = (await api_client.get(f"/api/v1/spots/{spot_id}")).json()["properties"]
    assert detail["latest_status"] is None or detail["latest_status"]["reported_by"] is None


async def test_status_read_never_exposes_reported_by_even_on_the_legacy_endpoint(api_client, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    resp = await api_client.post(
        f"/api/v1/spots/{spot_id}/status",
        json={"police_intervention": "warning", "expires_in_hours": 6},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201 and resp.json()["reported_by"] is None


# --- Geçmiş (sayfalı) --------------------------------------------------------------------------


async def test_history_is_paginated_newest_first_and_excludes_active(api_client, db_session, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    now = datetime.now(UTC)
    for i in range(5):  # kimliksiz (NULL) satırlar constraint'e takılmaz
        db_session.add(
            DynamicStatus(
                spot_id=spot_id,
                report_type=LiveReportType.ROAD_CLOSED,
                reported_at=now - timedelta(hours=10 + i),
                valid_until=now - timedelta(hours=1 + i),
            )
        )
    await db_session.commit()
    await report(api_client, user, spot_id, "full", 6)  # aktif: geçmişte görünmez

    page1 = (await api_client.get(live_url(spot_id, "/history?limit=2&offset=0"))).json()
    page3 = (await api_client.get(live_url(spot_id, "/history?limit=2&offset=4"))).json()
    assert page1["total"] == 5 and len(page1["items"]) == 2 and len(page3["items"]) == 1
    starts = [i["starts_at"] for i in page1["items"]]
    assert starts == sorted(starts, reverse=True)
    assert {i["outcome"] for i in page1["items"] + page3["items"]} == {"expired"}
    assert (await api_client.get(live_url(spot_id, "/history?limit=0"))).status_code == 422


# --- Eski uç uyumluluğu ------------------------------------------------------------------------


async def test_legacy_status_endpoint_still_works_and_feeds_the_new_model(api_client, db_session, make_user, make_spot):
    user, other = await make_user(), await make_user()
    spot_id = await make_spot(created_by=user.id)
    url = f"/api/v1/spots/{spot_id}/status"
    resp = await api_client.post(url, json={"police_intervention": "fine", "crowd_level": "full", "expires_in_hours": 6}, headers=auth_headers(user))
    assert resp.status_code == 201
    body = resp.json()
    assert body["police_intervention"] == "fine" and body["crowd_level"] == "full" and body["report_type"] == "fine_reported"

    groups = {g["report_type"]: g for g in (await active(api_client, spot_id))["groups"]}
    assert set(groups) == {"fine_reported", "full"}  # zabıta + doluluk iki ayrı tür
    assert await row_count(db_session, spot_id) == 2

    # Aynı kullanıcı aynı türü tekrar gönderemez; başkası destek olur.
    assert (await api_client.post(url, json={"police_intervention": "fine"}, headers=auth_headers(user))).status_code == 409
    assert (await api_client.post(url, json={"police_intervention": "fine"}, headers=auth_headers(other))).status_code == 201
    assert group_of(await active(api_client, spot_id), "fine_reported")["reporter_count"] == 2

    detail = (await api_client.get(f"/api/v1/spots/{spot_id}")).json()["properties"]
    assert detail["latest_status"]["police_intervention"] in {"fine", "none"}  # eski alan çalışıyor


async def test_legacy_status_without_a_known_type_is_kept_as_plain_info(api_client, db_session, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    resp = await api_client.post(
        f"/api/v1/spots/{spot_id}/status", json={"crowd_level": "medium"}, headers=auth_headers(user)
    )
    assert resp.status_code == 201 and resp.json()["report_type"] is None
    assert (await active(api_client, spot_id))["groups"] == []  # uyarı üretmez
    # Tür atanmamış bilgi satırı tekrar gönderilebilir (tekilleştirme kapsamı dışı).
    assert (await api_client.post(f"/api/v1/spots/{spot_id}/status", json={"crowd_level": "low"}, headers=auth_headers(user))).status_code == 201


async def test_legacy_status_rejects_an_expiry_in_the_past(api_client, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    resp = await api_client.post(
        f"/api/v1/spots/{spot_id}/status", json={"police_intervention": "warning", "valid_until": past}, headers=auth_headers(user)
    )
    assert resp.status_code == 422


async def test_untyped_rows_from_old_writers_are_still_understood(api_client, db_session, make_user, make_spot):
    """Seed/eski kod `report_type` doldurmadan yazsa da (police=banned) canlı durum tanınır."""
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    db_session.add(
        DynamicStatus(
            spot_id=spot_id,
            police_intervention=PoliceInterventionStatus.BANNED,
            crowd_level=CrowdLevel.HIGH,
            valid_until=datetime.now(UTC) + timedelta(hours=6),
        )
    )
    await db_session.commit()
    assert group_of(await active(api_client, spot_id), "overnight_restriction") is not None


# --- bbox: N+1 yok, hafif özet -----------------------------------------------------------------


class QueryCounter:
    def __init__(self):
        self.statements: list[str] = []

    def __enter__(self):
        event.listen(engine.sync_engine, "before_cursor_execute", self._on)
        return self

    def __exit__(self, *exc):
        event.remove(engine.sync_engine, "before_cursor_execute", self._on)

    def _on(self, conn, cursor, statement, params, context, executemany):
        self.statements.append(statement)


BBOX = "/api/v1/spots/bbox?min_lon=32.99&min_lat=38.99&max_lon=33.01&max_lat=39.01&limit=500"


async def test_bbox_query_count_is_constant_and_returns_only_a_small_live_summary(api_client, make_user, make_spot):
    user = await make_user()
    others = [await make_user() for _ in range(2)]
    first = await make_spot(created_by=user.id)
    for who in (user, *others):
        await report(api_client, who, first, "road_closed")
    await report(api_client, user, first, "mud_risk")

    with QueryCounter() as few:
        small = await api_client.get(BBOX)
    assert small.status_code == 200

    more_spots = [await make_spot(created_by=user.id) for _ in range(8)]
    for spot_id in more_spots:
        for report_type in ("road_closed", "fresh_water_unavailable", "electricity_unavailable"):
            await report(api_client, user, spot_id, report_type)

    with QueryCounter() as many:
        big = await api_client.get(BBOX)
    assert big.status_code == 200

    assert len(many.statements) == len(few.statements)  # spot sayısı arttı, sorgu sayısı DEĞİŞMEDİ
    features = {f["properties"]["id"]: f["properties"] for f in big.json()["features"]}
    assert len(features) >= 9
    summary = features[str(first)]["live_status"]
    assert summary == {
        "access": "not_recommended",
        "severity": "critical",
        "active_count": 2,
        "top_type": "road_closed",
        "types": ["road_closed", "mud_risk"],
        "expires_at": summary["expires_at"],
        "badge": True,
    }
    # Yanıtta ham bildirim listesi/geçmiş YOK; yalnızca özet.
    assert "groups" not in features[str(first)] and "history" not in features[str(first)]


async def test_bbox_summary_reflects_expiry_without_any_job(api_client, db_session, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await report(api_client, user, spot_id, "road_closed")
    feats = {f["properties"]["id"]: f["properties"] for f in (await api_client.get(BBOX)).json()["features"]}
    assert feats[str(spot_id)]["live_status"]["severity"] == "critical"
    await expire_now(db_session, spot_id)
    feats = {f["properties"]["id"]: f["properties"] for f in (await api_client.get(BBOX)).json()["features"]}
    assert feats[str(spot_id)]["live_status"]["severity"] == "none"
