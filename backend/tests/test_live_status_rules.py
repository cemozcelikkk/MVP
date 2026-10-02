"""
`live_status` saf-kural testleri (DB yok): güven düzeyi, bağımsız sayım, sıralama, aktiflik,
erişim kararı, eski sütunlarla köprü, kullanıcı metinleri. Kurallar `app/services/live_status.py`
docstring'inde.
"""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.enums import (
    CrowdLevel,
    LiveReportType,
    PoliceInterventionStatus,
    ReportModerationState,
)
from app.schemas.live_report import LiveReportCreate
from app.services.live_status import (
    ALLOWED_DURATION_HOURS,
    REPORT_CONFIG,
    ReportRow,
    aggregate_active,
    aggregates_from_statuses,
    compute_access,
    derive_report_type,
    effective_expiry,
    evidence_text,
    legacy_columns_for,
    remaining_text,
    summarize,
    trust_text,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
P = ReportModerationState.PENDING
C = ReportModerationState.CONFIRMED


def row(
    report_type=LiveReportType.ROAD_CLOSED,
    user="u1",
    *,
    state=P,
    on_site=False,
    started_hours_ago=1.0,
    hours_left=5.0,
    note=None,
    rid=None,
) -> ReportRow:
    return ReportRow(
        id=rid or f"{report_type.value}-{user}-{started_hours_ago}",
        report_type=report_type,
        state=state,
        reporter_key=user,
        on_site=on_site,
        reported_at=NOW - timedelta(hours=started_hours_ago),
        expires_at=NOW + timedelta(hours=hours_left),
        note=note,
    )


def only(rows):
    (agg,) = aggregate_active(rows, now=NOW)
    return agg


# --- Yapılandırma -------------------------------------------------------------------------------


def test_every_type_has_config_and_default_duration_is_allowed():
    assert set(REPORT_CONFIG) == set(LiveReportType)
    assert ALLOWED_DURATION_HOURS == (6, 12, 24, 48)


def test_spec_type_codes_are_stable():
    assert {t.value for t in LiveReportType} == {
        "overnight_restriction", "official_warning", "fine_reported", "road_closed", "access_difficult",
        "full", "fresh_water_unavailable", "electricity_unavailable", "grey_water_unavailable",
        "black_water_unavailable", "mud_risk", "fire_or_flood_access_issue",
    }


def test_default_durations_follow_the_product_spec():
    d = {t: cfg.default_hours for t, cfg in REPORT_CONFIG.items()}
    assert d[LiveReportType.FULL] == 6
    for t in (
        LiveReportType.FRESH_WATER_UNAVAILABLE, LiveReportType.ELECTRICITY_UNAVAILABLE,
        LiveReportType.GREY_WATER_UNAVAILABLE, LiveReportType.BLACK_WATER_UNAVAILABLE,
        LiveReportType.ACCESS_DIFFICULT, LiveReportType.MUD_RISK,
    ):
        assert d[t] == 12
    for t in (
        LiveReportType.ROAD_CLOSED, LiveReportType.OVERNIGHT_RESTRICTION, LiveReportType.OFFICIAL_WARNING,
        LiveReportType.FINE_REPORTED, LiveReportType.FIRE_OR_FLOOD_ACCESS_ISSUE,
    ):
        assert d[t] == 24


def test_user_labels_are_reports_not_official_decisions():
    assert REPORT_CONFIG[LiveReportType.OVERNIGHT_RESTRICTION].label == "Geceleme kısıtlaması bildirildi"
    assert REPORT_CONFIG[LiveReportType.FINE_REPORTED].label == "Ceza bildirildi"
    for cfg in REPORT_CONFIG.values():
        assert "yasak" not in cfg.label.lower()  # "Geceleme yasak" gibi iddialı karar dili yok
        assert "bildirildi" in cfg.label


@pytest.mark.parametrize("hours", [6, 12, 24, 48])
def test_allowed_durations_validate(hours):
    assert LiveReportCreate(report_type="road_closed", duration_hours=hours).duration_hours == hours


@pytest.mark.parametrize("hours", [0, 1, 7, 13, 72, -6])
def test_other_durations_are_rejected(hours):
    with pytest.raises(ValueError):
        LiveReportCreate(report_type="road_closed", duration_hours=hours)


def test_note_is_limited_and_control_characters_are_stripped():
    assert LiveReportCreate(report_type="full", duration_hours=6, note="  çok\x00   boşluk\x07lu  ").note == "çok boşluklu"
    assert LiveReportCreate(report_type="full", duration_hours=6, note="   ").note is None
    with pytest.raises(ValueError):
        LiveReportCreate(report_type="full", duration_hours=6, note="x" * 281)


# --- Aktiflik -----------------------------------------------------------------------------------


def test_expired_and_closed_reports_drop_out_of_active_results():
    rows = [
        row(LiveReportType.ROAD_CLOSED, "a", hours_left=-0.01),  # süresi doldu
        row(LiveReportType.MUD_RISK, "b", state=ReportModerationState.WITHDRAWN),
        row(LiveReportType.FULL, "c", state=ReportModerationState.REJECTED),
        row(LiveReportType.FRESH_WATER_UNAVAILABLE, "d"),
    ]
    assert [a.report_type for a in aggregate_active(rows, now=NOW)] == [LiveReportType.FRESH_WATER_UNAVAILABLE]


def test_report_is_active_until_exact_expiry_instant():
    just_before = row(hours_left=0.001)
    exactly_at = row(hours_left=0)
    assert len(aggregate_active([just_before], now=NOW)) == 1
    assert aggregate_active([exactly_at], now=NOW) == []


def test_legacy_open_ended_report_gets_a_24h_cap():
    reported = NOW - timedelta(hours=30)
    assert effective_expiry(reported, None) == reported + timedelta(hours=24)
    assert effective_expiry(reported, NOW) == NOW


# --- Bağımsız sayım / güven ---------------------------------------------------------------------


def test_same_user_repeats_count_as_one_reporter():
    agg = only([row(user="a", started_hours_ago=3), row(user="a", started_hours_ago=1), row(user="a", started_hours_ago=0.5)])
    assert agg.reporter_count == 1 and agg.trust_level == "single_report"


def test_distinct_users_increase_reporter_count():
    assert only([row(user="a"), row(user="b")]).reporter_count == 2
    assert only([row(user="a"), row(user="b"), row(user="c")]).reporter_count == 3


def test_deleted_reporters_count_as_a_single_person():
    rows = [row(user=None, rid="1"), row(user=None, rid="2"), row(user=None, rid="3")]
    assert only(rows).reporter_count == 1


def test_one_reporter_and_three_reporters_are_never_the_same_trust_level():
    single = only([row(user="a")])
    three = only([row(user="a"), row(user="b"), row(user="c")])
    assert single.trust_level == "single_report"
    assert three.trust_level == "well_supported"
    assert single.trust_level != three.trust_level
    assert trust_text(single.trust_level) != trust_text(three.trust_level)


def test_trust_ladder():
    assert only([row(user="a")]).trust_level == "single_report"
    assert only([row(user="a"), row(user="b")]).trust_level == "supported"
    assert only([row(user="a", on_site=True)]).trust_level == "supported"  # tek ama yerinde
    assert only([row(user="a", on_site=True), row(user="b")]).trust_level == "well_supported"
    assert only([row(user="a"), row(user="b"), row(user="c")]).trust_level == "well_supported"


def test_on_site_count_counts_independent_people_once():
    agg = only([row(user="a", on_site=True), row(user="a", on_site=True, started_hours_ago=2), row(user="b")])
    assert agg.on_site_count == 1 and agg.reporter_count == 2


def test_moderator_confirmation_is_explicit_and_wins():
    agg = only([row(user="a", state=C)])
    assert agg.moderator_confirmed and agg.trust_level == "moderator_confirmed"
    assert trust_text("moderator_confirmed") == "Moderatör onayladı"
    assert only([row(user="a"), row(user="b"), row(user="c"), row(user="d", state=C)]).trust_level == "moderator_confirmed"


def test_evidence_text_mentions_on_site_users_without_personal_data():
    text = evidence_text(only([row(user="a", on_site=True), row(user="b")]))
    assert text == "2 bağımsız kişi bildirdi · 1 kişi son 72 saatte noktada check-in yapmıştı"
    assert evidence_text(only([row(user="a")])) == "1 kişi bildirdi"


def test_notes_are_capped_newest_first_and_blank_ones_skipped():
    rows = [row(user=str(i), note=f"not {i}", started_hours_ago=10 - i) for i in range(5)] + [row(user="x", note="  ")]
    assert only(rows).notes == ("not 4", "not 3", "not 2")


# --- Sıralama / erişim kararı ------------------------------------------------------------------


def test_most_severe_active_status_comes_first_then_reporter_count():
    rows = [
        row(LiveReportType.FRESH_WATER_UNAVAILABLE, "a"),
        row(LiveReportType.FRESH_WATER_UNAVAILABLE, "b"),
        row(LiveReportType.FRESH_WATER_UNAVAILABLE, "c"),
        row(LiveReportType.MUD_RISK, "a"),
        row(LiveReportType.ROAD_CLOSED, "a"),
        row(LiveReportType.FINE_REPORTED, "a"),
    ]
    order = [a.report_type for a in aggregate_active(rows, now=NOW)]
    assert order == [
        LiveReportType.ROAD_CLOSED,  # critical
        LiveReportType.FINE_REPORTED,  # serious
        LiveReportType.FRESH_WATER_UNAVAILABLE,  # caution, 3 kişi -> mud_risk'ten önce
        LiveReportType.MUD_RISK,
    ]


def test_ordering_is_deterministic_regardless_of_input_order():
    rows = [row(LiveReportType.FULL, "a"), row(LiveReportType.MUD_RISK, "b"), row(LiveReportType.ACCESS_DIFFICULT, "c")]
    assert aggregate_active(rows, now=NOW) == aggregate_active(list(reversed(rows)), now=NOW)


@pytest.mark.parametrize(
    ("types", "expected"),
    [
        ([], "ok"),
        ([LiveReportType.ROAD_CLOSED], "not_recommended"),
        ([LiveReportType.FIRE_OR_FLOOD_ACCESS_ISSUE], "not_recommended"),
        ([LiveReportType.ACCESS_DIFFICULT], "caution"),
        ([LiveReportType.MUD_RISK], "caution"),
        ([LiveReportType.MUD_RISK, LiveReportType.ROAD_CLOSED], "not_recommended"),
        ([LiveReportType.FRESH_WATER_UNAVAILABLE, LiveReportType.FULL, LiveReportType.FINE_REPORTED], "ok"),
    ],
)
def test_access_verdict(types, expected):
    assert compute_access(aggregate_active([row(t, "a") for t in types], now=NOW)) == expected


def test_summary_is_small_and_describes_the_top_status():
    rows = [row(LiveReportType.MUD_RISK, "a"), row(LiveReportType.ROAD_CLOSED, "a", hours_left=3)]
    summary = summarize(aggregate_active(rows, now=NOW))
    assert summary.access == "not_recommended" and summary.severity == "critical"
    assert summary.top_type is LiveReportType.ROAD_CLOSED and summary.active_count == 2
    assert summary.expires_at == NOW + timedelta(hours=3)
    empty = summarize([])
    assert empty.access == "ok" and empty.severity == "none" and empty.top_type is None and empty.types == ()


def test_pin_badge_only_for_serious_or_critical_or_official_warning():
    def badge(*types):
        return summarize(aggregate_active([row(t, 'a') for t in types], now=NOW)).badge

    assert badge(LiveReportType.ROAD_CLOSED) and badge(LiveReportType.FINE_REPORTED)
    assert badge(LiveReportType.OVERNIGHT_RESTRICTION) and badge(LiveReportType.OFFICIAL_WARNING)
    assert not badge(LiveReportType.MUD_RISK, LiveReportType.FULL, LiveReportType.FRESH_WATER_UNAVAILABLE)
    assert not summarize([]).badge


def test_remaining_text():
    assert remaining_text(0) == "Süresi doldu"
    assert remaining_text(45) == "45 dk kaldı"
    assert remaining_text(120) == "2 saat kaldı"
    assert remaining_text(200) == "3 sa 20 dk kaldı"


# --- Eski sütunlarla köprü ---------------------------------------------------------------------


def orm(police=PoliceInterventionStatus.NONE, crowd=None, report_type=None, state=P, reported_by="legacy-user"):
    return SimpleNamespace(
        id=f"{police}-{crowd}-{report_type}",
        report_type=report_type,
        police_intervention=police,
        crowd_level=crowd,
        moderation_state=state,
        reported_by=reported_by,
        reporter_on_site=False,
        reported_at=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(hours=5),
        note=None,
    )


@pytest.mark.parametrize(
    ("police", "crowd", "expected"),
    [
        (PoliceInterventionStatus.WARNING, None, LiveReportType.OFFICIAL_WARNING),
        (PoliceInterventionStatus.FINE, None, LiveReportType.FINE_REPORTED),
        (PoliceInterventionStatus.BANNED, None, LiveReportType.OVERNIGHT_RESTRICTION),
        (PoliceInterventionStatus.FINE, CrowdLevel.FULL, LiveReportType.FINE_REPORTED),  # zabıta öncelikli
        (PoliceInterventionStatus.NONE, CrowdLevel.FULL, LiveReportType.FULL),
        (PoliceInterventionStatus.NONE, CrowdLevel.HIGH, None),
        (PoliceInterventionStatus.UNKNOWN, None, None),
    ],
)
def test_legacy_columns_map_to_types(police, crowd, expected):
    assert derive_report_type(police, crowd) is expected


def test_new_types_write_the_closest_legacy_columns():
    assert legacy_columns_for(LiveReportType.FINE_REPORTED) == (PoliceInterventionStatus.FINE, None)
    assert legacy_columns_for(LiveReportType.FULL) == (PoliceInterventionStatus.NONE, CrowdLevel.FULL)
    assert legacy_columns_for(LiveReportType.ROAD_CLOSED) == (PoliceInterventionStatus.NONE, None)


def test_untyped_rows_from_old_writers_still_count_and_plain_info_rows_do_not():
    statuses = [
        orm(police=PoliceInterventionStatus.WARNING),  # seed/eski yazıcı: report_type NULL
        orm(crowd=CrowdLevel.MEDIUM),  # salt bilgi
        orm(report_type=LiveReportType.ROAD_CLOSED, reported_by="other"),
    ]
    aggs = aggregates_from_statuses(statuses, now=NOW)
    assert {a.report_type for a in aggs} == {LiveReportType.OFFICIAL_WARNING, LiveReportType.ROAD_CLOSED}
