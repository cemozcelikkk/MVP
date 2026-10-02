"""
`field_freshness.evaluate_field` saf-fonksiyon testleri (DB yok). Kurallar
`app/services/field_freshness.py` docstring'inde; burada her biri ayrı doğrulanır.
"""
from datetime import UTC, datetime, timedelta

from app.models.enums import LiveReportType
from app.models.field_verification import VerifiableField, VerificationAnswer
from app.services.field_freshness import (
    FIELD_CONFIG,
    CurrentAnswer,
    duration_tr,
    evaluate_field,
    relative_tr,
)
from app.services.live_status import REPORT_CONFIG, TypeAggregate, _trust_level

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
W = VerifiableField.FRESH_WATER


def ans(user: str, answer: VerificationAnswer, days_ago: float) -> CurrentAnswer:
    return CurrentAnswer(user, answer, NOW - timedelta(days=days_ago))


def live(report_type: LiveReportType, reporters: int = 1) -> TypeAggregate:
    """Aktif bir canlı bildirim birleşimi (DB'siz)."""
    return TypeAggregate(
        report_type=report_type,
        severity=REPORT_CONFIG[report_type].severity,
        reporter_count=reporters,
        on_site_count=0,
        moderator_confirmed=False,
        trust_level=_trust_level(reporters, 0, False),
        latest_reported_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=5),
        notes=(),
    )


def ev(field, answers, live_aggregates=None):
    return evaluate_field(field, answers, now=NOW, live_aggregates=live_aggregates)


def test_no_answers_is_unverified_with_spec_text():
    r = ev(VerifiableField.OVERNIGHT, [])
    assert r.status == "unverified"
    assert r.tone == "neutral"
    assert r.participant_count == 0 and r.last_verified_at is None
    assert r.status_text == "Geceleme durumuna ilişkin güncel doğrulama yok"


def test_single_fresh_confirmation_is_recently_confirmed_but_low_confidence():
    r = ev(W, [ans("a", VerificationAnswer.WORKING, 3)])
    assert r.status == "recently_confirmed"
    assert r.tone == "positive"
    assert r.status_text == "Su çalışıyor · 3 gün önce doğrulandı"
    assert r.participant_count == 1 and r.confidence == "low"  # tek doğrulama "kesin güvenilir" değil


def test_confidence_scales_with_independent_fresh_supporters():
    two = ev(W, [ans("a", VerificationAnswer.WORKING, 1), ans("b", VerificationAnswer.WORKING, 2)])
    three = ev(W, [ans(u, VerificationAnswer.WORKING, 1) for u in "abc"])
    assert two.confidence == "medium"
    assert three.confidence == "high"
    assert three.participant_count == 3


def test_old_verification_becomes_stale_but_is_not_dropped():
    r = ev(VerifiableField.ELECTRICITY, [ans("a", VerificationAnswer.WORKING, 7 * 30)])
    assert r.status == "stale"
    assert r.tone == "neutral"
    assert r.status_text == "Elektrik bilgisi 7 aydır doğrulanmadı"
    assert r.participant_count == 1  # kayıt silinmedi, sadece güncel kararda ağırlığı düştü


def test_freshness_threshold_is_field_specific():
    age = 40  # su (14g) için eski, yol (60g) için hâlâ taze
    water = ev(W, [ans("a", VerificationAnswer.WORKING, age)])
    road = ev(VerifiableField.ROAD_ACCESS, [ans("a", VerificationAnswer.PASSABLE, age)])
    assert water.status == "stale"
    assert road.status == "recently_confirmed"
    assert FIELD_CONFIG[W].fresh_days < FIELD_CONFIG[VerifiableField.ROAD_ACCESS].fresh_days


def test_negative_answer_is_service_issue_not_green():
    r = ev(W, [ans("a", VerificationAnswer.NOT_WORKING, 1)])
    assert r.status == "service_issue_reported"
    assert r.tone == "negative"
    assert r.status_text.startswith("Su çalışmıyor")


def test_road_impassable_is_access_issue():
    r = ev(VerifiableField.ROAD_ACCESS, [ans("a", VerificationAnswer.IMPASSABLE, 2)])
    assert r.status == "service_issue_reported"
    assert r.status_text.startswith("Yol geçilemiyor")


def test_two_independent_fresh_users_with_opposite_answers_conflict():
    r = ev(W, [ans("a", VerificationAnswer.WORKING, 1), ans("b", VerificationAnswer.NOT_WORKING, 2)])
    assert r.status == "conflicting_reports"
    assert r.consensus_answer is None  # son yazan otomatik "gerçek" sayılmaz
    assert set(r.conflicting_answers) == {VerificationAnswer.WORKING, VerificationAnswer.NOT_WORKING}
    assert r.tone == "caution"


def test_two_independent_users_same_answer_agree():
    r = ev(W, [ans("a", VerificationAnswer.WORKING, 1), ans("b", VerificationAnswer.WORKING, 5)])
    assert r.status == "recently_confirmed"
    assert r.supporting_count == 2


def test_much_older_dissent_does_not_create_conflict():
    """Taze bir cevaba karşı çok eski bir cevap ağırlığını kaybetmiştir - çelişki DEĞİL."""
    r = ev(W, [ans("a", VerificationAnswer.WORKING, 1), ans("b", VerificationAnswer.NOT_WORKING, 100)])
    assert r.status == "recently_confirmed"
    assert r.consensus_answer is VerificationAnswer.WORKING


def test_fresh_answer_overrides_old_majority_by_weight():
    r = ev(
        W,
        [
            ans("a", VerificationAnswer.WORKING, 120),
            ans("b", VerificationAnswer.WORKING, 130),
            ans("c", VerificationAnswer.NOT_WORKING, 1),
        ],
    )
    assert r.consensus_answer is VerificationAnswer.NOT_WORKING
    assert r.status == "service_issue_reported"


def test_lone_dissent_among_many_is_not_a_conflict():
    answers = [ans(u, VerificationAnswer.WORKING, 1) for u in "abcde"] + [
        ans("z", VerificationAnswer.NOT_WORKING, 1)
    ]
    r = ev(W, answers)
    assert r.status == "recently_confirmed"  # 1/6 < %30


def test_live_overnight_restriction_conflicts_with_old_allowed_verification_and_is_not_green():
    r = ev(
        VerifiableField.OVERNIGHT,
        [ans("a", VerificationAnswer.ALLOWED, 2)],
        [live(LiveReportType.OVERNIGHT_RESTRICTION)],
    )
    assert r.status == "recently_confirmed"  # doğrulamanın kendi durumu değişmez
    assert r.live_signal is not None and r.live_overrides is True
    assert r.live_signal.conflicts_with_verification is True
    assert r.live_signal.severity == "blocking"
    assert r.live_signal.code == "LIVE_OVERNIGHT_RESTRICTION"
    assert r.tone == "negative"  # yeşil güven işareti bastırıldı


def test_live_warning_level_signal_downgrades_green_to_caution():
    r = ev(
        VerifiableField.OVERNIGHT,
        [ans("a", VerificationAnswer.ALLOWED, 2)],
        [live(LiveReportType.OFFICIAL_WARNING)],
    )
    assert r.live_signal.severity == "warning" and r.tone == "caution"


def test_live_signal_does_not_conflict_with_negative_verification():
    r = ev(
        VerifiableField.OVERNIGHT,
        [ans("a", VerificationAnswer.NOT_ALLOWED, 2)],
        [live(LiveReportType.OVERNIGHT_RESTRICTION)],
    )
    assert r.live_signal is not None and r.live_signal.conflicts_with_verification is False
    assert r.live_overrides is False and r.tone == "negative"


def test_live_signal_shown_even_when_unverified():
    unverified = ev(VerifiableField.OVERNIGHT, [], [live(LiveReportType.OFFICIAL_WARNING)])
    assert unverified.status == "unverified"
    assert unverified.live_signal is not None and unverified.live_signal.severity == "warning"


def test_road_closed_attaches_to_road_row_with_old_passable_not_green():
    road = ev(
        VerifiableField.ROAD_ACCESS,
        [ans("a", VerificationAnswer.PASSABLE, 12)],
        [live(LiveReportType.ROAD_CLOSED)],
    )
    assert road.status == "recently_confirmed" and road.consensus_answer is VerificationAnswer.PASSABLE
    assert road.live_overrides is True and road.tone == "negative"
    assert road.live_signal.code == "LIVE_ROAD_CLOSED" and road.live_signal.severity == "blocking"
    # Aynı canlı bildirim başka satırlara SIZMAZ.
    for other in (VerifiableField.FRESH_WATER, VerifiableField.ELECTRICITY, VerifiableField.OVERNIGHT):
        assert ev(other, [ans("a", VerificationAnswer.WORKING if other is not VerifiableField.OVERNIGHT else VerificationAnswer.ALLOWED, 1)],
                  [live(LiveReportType.ROAD_CLOSED)]).live_signal is None


def test_access_difficult_and_mud_risk_are_warnings_on_road_row_and_sorted_by_severity():
    r = ev(
        VerifiableField.ROAD_ACCESS,
        [ans("a", VerificationAnswer.PASSABLE, 3)],
        [live(LiveReportType.ROAD_CLOSED), live(LiveReportType.MUD_RISK)],
    )
    assert [s.report_type for s in r.live_signals] == [LiveReportType.ROAD_CLOSED, LiveReportType.MUD_RISK]
    mud = ev(VerifiableField.ROAD_ACCESS, [], [live(LiveReportType.MUD_RISK)])
    assert mud.live_signal.severity == "warning"
    diff = ev(VerifiableField.ROAD_ACCESS, [], [live(LiveReportType.ACCESS_DIFFICULT)])
    assert diff.live_signal.severity == "warning"


def test_service_outages_map_to_their_own_rows():
    cases = {
        LiveReportType.FRESH_WATER_UNAVAILABLE: VerifiableField.FRESH_WATER,
        LiveReportType.ELECTRICITY_UNAVAILABLE: VerifiableField.ELECTRICITY,
        LiveReportType.GREY_WATER_UNAVAILABLE: VerifiableField.GREY_WATER,
        LiveReportType.BLACK_WATER_UNAVAILABLE: VerifiableField.BLACK_WATER,
    }
    for report_type, field in cases.items():
        assert ev(field, [ans("a", VerificationAnswer.WORKING, 1)], [live(report_type)]).live_overrides is True
        for other in cases.values():
            if other is not field:
                assert ev(other, [], [live(report_type)]).live_signal is None


def test_full_report_does_not_attach_to_any_freshness_row():
    for field in VerifiableField:
        assert ev(field, [], [live(LiveReportType.FULL)]).live_signal is None


def test_no_live_aggregates_means_no_live_signal():
    r = ev(VerifiableField.OVERNIGHT, [ans("a", VerificationAnswer.ALLOWED, 1)], [])
    assert r.live_signal is None and r.tone == "positive" and r.live_overrides is False


def test_evaluation_is_deterministic():
    answers = [ans("a", VerificationAnswer.WORKING, 1), ans("b", VerificationAnswer.NOT_WORKING, 1)]
    assert ev(W, answers) == ev(W, list(reversed(answers)))


def test_relative_and_duration_text():
    assert relative_tr(0) == "bugün" and relative_tr(1) == "dün"
    assert relative_tr(3) == "3 gün önce" and relative_tr(14) == "2 hafta önce"
    assert relative_tr(200) == "6 ay önce" and relative_tr(400) == "1 yıl önce"
    assert duration_tr(210) == "7 aydır" and duration_tr(15) == "2 haftadır"
