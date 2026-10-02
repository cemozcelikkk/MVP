"""
Yerinde doğrulama akışının uçtan uca (HTTP -> servis -> gerçek Postgres) testleri.
`tests/test_field_freshness.py` kural mantığını, burası şu güvenceleri doğrular:
check-in şartı, tek-kullanıcı şişirmesinin engellenmesi, bağımsız kullanıcıların
sayımı, çelişki, yetki ve gizlilik.
"""
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models.dynamic_status import DynamicStatus
from app.models.enums import PoliceInterventionStatus
from app.models.field_verification import (
    SpotFieldVerification,
    VerifiableField,
    VerificationAnswer,
)
from tests.conftest import auth_headers


def fresh_url(spot_id) -> str:
    return f"/api/v1/spots/{spot_id}/field-freshness"


def verify_url(spot_id) -> str:
    return f"/api/v1/spots/{spot_id}/verifications"


async def freshness_of(client, spot_id, field: str) -> dict:
    body = (await client.get(fresh_url(spot_id))).json()
    return next(f for f in body["primary"] + body["secondary"] if f["field"] == field)


async def post(client, user, spot_id, answers: dict):
    return await client.post(verify_url(spot_id), json={"answers": answers}, headers=auth_headers(user))


async def count_rows(db_session, spot_id, user=None) -> int:
    stmt = select(func.count()).select_from(SpotFieldVerification).where(
        SpotFieldVerification.spot_id == spot_id
    )
    if user is not None:
        stmt = stmt.where(SpotFieldVerification.user_id == user.id)
    return (await db_session.execute(stmt)).scalar_one()


# --- Check-in şartı ---------------------------------------------------------


async def test_verification_rejected_without_check_in(api_client, db_session, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)

    resp = await post(api_client, user, spot_id, {"fresh_water": "working"})

    assert resp.status_code == 403
    assert await count_rows(db_session, spot_id) == 0
    assert (await freshness_of(api_client, spot_id, "fresh_water"))["status"] == "unverified"


async def test_verification_rejected_when_check_in_too_old(api_client, make_user, make_spot, make_check_in):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await make_check_in(user, spot_id, hours_ago=24 * 10)

    resp = await post(api_client, user, spot_id, {"fresh_water": "working"})
    assert resp.status_code == 403
    me = (await api_client.get(f"{verify_url(spot_id)}/me", headers=auth_headers(user))).json()
    assert me["eligible"] is False and me["eligibility_code"] == "NO_RECENT_CHECKIN"


async def test_eligible_user_can_verify_and_permanent_data_is_untouched(
    api_client, make_user, make_spot, make_check_in
):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await make_check_in(user, spot_id)

    resp = await post(api_client, user, spot_id, {"fresh_water": "working", "overnight": "unknown"})
    assert resp.status_code == 201
    actions = {r["field"]: r["action"] for r in resp.json()["results"]}
    assert actions == {"fresh_water": "created", "overnight": "skipped"}

    water = await freshness_of(api_client, spot_id, "fresh_water")
    assert water["status"] == "recently_confirmed"
    assert water["participant_count"] == 1 and water["confidence"] == "low"
    assert water["status_text"] == "Su çalışıyor · bugün doğrulandı"
    # "Bilmiyorum" hiçbir şeyi doğrulamaz.
    assert (await freshness_of(api_client, spot_id, "overnight"))["status"] == "unverified"
    # Noktanın KALICI bilgisi tek kullanıcının cevabıyla değişmez (amenities.fresh_water_thread hâlâ False).
    detail = (await api_client.get(f"/api/v1/spots/{spot_id}")).json()
    assert detail["properties"]["amenities"]["fresh_water_thread"] is False
    assert water["reported_text"] == "Yok olarak bildirilmiş"


async def test_invalid_answer_for_field_is_rejected(api_client, make_user, make_spot, make_check_in):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await make_check_in(user, spot_id)
    assert (await post(api_client, user, spot_id, {"fresh_water": "passable"})).status_code == 422
    assert (await post(api_client, user, spot_id, {})).status_code == 422


# --- Şişirme engeli / bağımsız katılımcılar ---------------------------------


async def test_same_user_repeating_does_not_inflate_participant_count(
    api_client, db_session, make_user, make_spot, make_check_in
):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await make_check_in(user, spot_id)

    for _ in range(5):
        resp = await post(api_client, user, spot_id, {"electricity": "working"})
        assert resp.status_code == 201

    assert (await freshness_of(api_client, spot_id, "electricity"))["participant_count"] == 1
    assert await count_rows(db_session, spot_id, user) == 1  # aynı ziyaret+aynı cevap: no-op
    last = (await post(api_client, user, spot_id, {"electricity": "working"})).json()["results"][0]
    assert last["action"] == "unchanged"


async def test_concurrent_submissions_from_same_user_keep_a_single_current_row(
    api_client, db_session, make_user, make_spot, make_check_in
):
    """Yarışan eşzamanlı gönderimler (advisory lock + kısmi unique index) çift 'güncel' satır üretmez."""
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await make_check_in(user, spot_id)

    answers = ["working", "not_working"] * 3
    responses = await asyncio.gather(
        *(post(api_client, user, spot_id, {"fresh_water": a}) for a in answers)
    )
    assert all(r.status_code == 201 for r in responses)

    user_id = user.id  # rollback nesneyi expire eder; kimliği önceden al
    await db_session.rollback()  # taze okuma
    current = (
        await db_session.execute(
            select(func.count()).select_from(SpotFieldVerification).where(
                SpotFieldVerification.spot_id == spot_id,
                SpotFieldVerification.user_id == user_id,
                SpotFieldVerification.is_current.is_(True),
            )
        )
    ).scalar_one()
    assert current == 1
    assert (await freshness_of(api_client, spot_id, "fresh_water"))["participant_count"] == 1


async def test_changed_answer_replaces_current_and_preserves_history(
    api_client, db_session, make_user, make_spot, make_check_in
):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await make_check_in(user, spot_id)

    await post(api_client, user, spot_id, {"fresh_water": "working"})
    resp = await post(api_client, user, spot_id, {"fresh_water": "not_working"})
    assert resp.json()["results"][0]["action"] == "updated"

    water = await freshness_of(api_client, spot_id, "fresh_water")
    assert water["participant_count"] == 1  # eski cevap ikinci bir oy DEĞİL
    assert water["consensus_answer"] == "not_working"
    assert await count_rows(db_session, spot_id, user) == 2  # geçmiş korundu
    me = (await api_client.get(f"{verify_url(spot_id)}/me", headers=auth_headers(user))).json()
    assert [h["is_current"] for h in me["history"]].count(True) == 1
    assert me["current_answers"] == {"fresh_water": "not_working"}


async def test_reconfirming_on_a_later_visit_is_still_a_single_vote(
    api_client, db_session, make_user, make_spot, make_check_in
):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await make_check_in(user, spot_id, hours_ago=60)
    await post(api_client, user, spot_id, {"fresh_water": "working"})
    await make_check_in(user, spot_id)  # sonraki ziyaret
    resp = await post(api_client, user, spot_id, {"fresh_water": "working"})
    assert resp.json()["results"][0]["action"] == "updated"  # taze zaman damgası

    assert (await freshness_of(api_client, spot_id, "fresh_water"))["participant_count"] == 1
    current = await db_session.scalar(
        select(func.count()).select_from(SpotFieldVerification).where(
            SpotFieldVerification.spot_id == spot_id, SpotFieldVerification.is_current.is_(True)
        )
    )
    assert current == 1


async def test_separate_users_same_answer_count_independently(api_client, make_user, make_spot, make_check_in):
    a, b = await make_user("A"), await make_user("B")
    spot_id = await make_spot(created_by=a.id)
    for user in (a, b):
        await make_check_in(user, spot_id)
        await post(api_client, user, spot_id, {"fresh_water": "working"})

    water = await freshness_of(api_client, spot_id, "fresh_water")
    assert water["participant_count"] == 2 and water["supporting_count"] == 2
    assert water["confidence"] == "medium" and water["status"] == "recently_confirmed"


async def test_separate_users_conflicting_answers_report_conflict(api_client, make_user, make_spot, make_check_in):
    a, b = await make_user("A"), await make_user("B")
    spot_id = await make_spot(created_by=a.id)
    for user, answer in ((a, "working"), (b, "not_working")):
        await make_check_in(user, spot_id)
        await post(api_client, user, spot_id, {"fresh_water": answer})

    water = await freshness_of(api_client, spot_id, "fresh_water")
    assert water["status"] == "conflicting_reports"
    assert water["consensus_answer"] is None
    assert set(water["conflicting_answers"]) == {"working", "not_working"}
    assert water["tone"] == "caution"


# --- Zaman etkisi / çalışmayan hizmet / canlı durum çelişkisi -------------------


async def test_old_verification_reads_as_stale_without_being_deleted(
    api_client, db_session, make_user, make_spot
):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    db_session.add(
        SpotFieldVerification(
            spot_id=spot_id,
            user_id=user.id,
            field=VerifiableField.ELECTRICITY,
            answer=VerificationAnswer.WORKING,
            created_at=datetime.now(UTC) - timedelta(days=210),
        )
    )
    await db_session.commit()

    power = await freshness_of(api_client, spot_id, "electricity")
    assert power["status"] == "stale"
    assert power["status_text"] == "Elektrik bilgisi 7 aydır doğrulanmadı"
    assert power["participant_count"] == 1
    assert power["last_verified_on"] is not None and "T" not in power["last_verified_on"]  # sadece gün


async def test_not_working_service_is_reported_as_service_issue(api_client, make_user, make_spot, make_check_in):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await make_check_in(user, spot_id)
    await post(api_client, user, spot_id, {"grey_water": "not_working"})

    grey = await freshness_of(api_client, spot_id, "grey_water")
    assert grey["status"] == "service_issue_reported" and grey["tone"] == "negative"


async def test_active_live_ban_conflicts_with_allowed_verification(
    api_client, db_session, make_user, make_spot, make_check_in
):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await make_check_in(user, spot_id)
    await post(api_client, user, spot_id, {"overnight": "allowed"})
    db_session.add(
        DynamicStatus(
            spot_id=spot_id,
            reported_by=user.id,
            police_intervention=PoliceInterventionStatus.BANNED,
            valid_until=datetime.now(UTC) + timedelta(hours=6),
        )
    )
    await db_session.commit()

    night = await freshness_of(api_client, spot_id, "overnight")
    assert night["live_signal"]["conflicts_with_verification"] is True
    assert night["live_signal"]["severity"] == "blocking"
    assert night["live_overrides"] is True
    assert night["tone"] == "negative"  # eski "geceleme mümkün" doğrulaması yeşil güven işareti DEĞİL


async def test_expired_live_status_is_ignored(api_client, db_session, make_user, make_spot, make_check_in):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await make_check_in(user, spot_id)
    await post(api_client, user, spot_id, {"overnight": "allowed"})
    db_session.add(
        DynamicStatus(
            spot_id=spot_id,
            police_intervention=PoliceInterventionStatus.BANNED,
            valid_until=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    await db_session.commit()
    night = await freshness_of(api_client, spot_id, "overnight")
    assert night["live_signal"] is None and night["tone"] == "positive"


# --- Yetki ve gizlilik ----------------------------------------------------------


async def test_unauthenticated_access_is_rejected(api_client, make_user, make_spot):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    assert (await api_client.post(verify_url(spot_id), json={"answers": {"fresh_water": "working"}})).status_code == 401
    assert (await api_client.get(f"{verify_url(spot_id)}/me")).status_code == 401
    assert (await api_client.get(f"{verify_url(spot_id)}/audit")).status_code == 401
    assert (await api_client.get(fresh_url(spot_id))).status_code == 200  # özet herkese açık


async def test_audit_is_moderator_only_and_owner_cannot_see_others_history(
    api_client, db_session, make_user, make_spot, make_check_in
):
    voter, other, mod = await make_user("Oy"), await make_user("Diğer"), await make_user("Mod")
    from app.models.enums import UserRole

    mod.role = UserRole.MODERATOR
    await db_session.commit()
    spot_id = await make_spot(created_by=voter.id)
    await make_check_in(voter, spot_id)
    await post(api_client, voter, spot_id, {"fresh_water": "working"})

    audit = f"{verify_url(spot_id)}/audit"
    assert (await api_client.get(audit, headers=auth_headers(other))).status_code == 403
    ok = await api_client.get(audit, headers=auth_headers(mod))
    assert ok.status_code == 200 and ok.json()[0]["user_id"] == str(voter.id)
    # Başkasının gönderisi kendi geçmişinde görünmez.
    me_other = (await api_client.get(f"{verify_url(spot_id)}/me", headers=auth_headers(other))).json()
    assert me_other["history"] == []


async def test_public_freshness_exposes_no_user_identifiers_or_full_timestamps(
    api_client, make_user, make_spot, make_check_in
):
    user = await make_user()
    spot_id = await make_spot(created_by=user.id)
    await make_check_in(user, spot_id)
    await post(api_client, user, spot_id, {"fresh_water": "working"})

    raw = (await api_client.get(fresh_url(spot_id))).text
    assert str(user.id) not in raw
    assert "user_id" not in raw and "latitude" not in raw and "check_in" not in raw
