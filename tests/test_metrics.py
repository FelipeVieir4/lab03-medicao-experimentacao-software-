from datetime import datetime, timedelta, timezone

import pytest

from pipeline.metrics import (
    change_failure_rate,
    classify_metric,
    classify_repository,
    deployment_frequency,
    lead_time_by_commit,
    lead_time_by_release,
    recovery_time,
)


UTC = timezone.utc


def test_deployment_frequency_uses_releases_per_week():
    assert deployment_frequency([datetime.now(UTC)] * 7, weeks=1) == 7


def test_lead_time_variants_and_empty_release():
    release = datetime(2026, 1, 15, tzinfo=UTC)
    commits = [datetime(2026, 1, 2, tzinfo=UTC), datetime(2026, 1, 10, tzinfo=UTC)]
    data = [(release, commits), (release, [])]

    assert lead_time_by_release(data) == 13
    assert lead_time_by_commit(data) == 9
    assert lead_time_by_release([(release, [])]) is None


def test_change_failure_rate_ignores_cancelled_runs():
    assert change_failure_rate(["success", "failure", "cancelled", "skipped"]) == 0.5
    assert change_failure_rate(["cancelled"]) is None


def test_recovery_time_and_censored_episode():
    start = datetime(2026, 1, 1, 10, tzinfo=UTC)
    runs = [
        {"conclusion": "success", "run_started_at": start, "updated_at": start},
        {
            "conclusion": "failure",
            "run_started_at": start + timedelta(hours=1),
            "updated_at": start + timedelta(hours=1, minutes=10),
        },
        {
            "conclusion": "failure",
            "run_started_at": start + timedelta(hours=2),
            "updated_at": start + timedelta(hours=2, minutes=10),
        },
        {
            "conclusion": "success",
            "run_started_at": start + timedelta(hours=3),
            "updated_at": start + timedelta(hours=3, minutes=20),
        },
    ]

    assert recovery_time(runs) == (pytest.approx(2.333333), 0)

    runs[-1]["conclusion"] = "failure"
    assert recovery_time(runs) == (None, 1)


def test_dora_thresholds_and_repository_classification():
    assert classify_metric("deployment_frequency", 7) == "Elite"
    assert classify_metric("lead_time_days", 7) == "Medium"
    assert classify_metric("change_failure_rate", 0.30) == "High"
    assert classify_metric("recovery_hours", 24) == "Medium"
    assert classify_repository(
        {
            "deployment_frequency": 2,
            "lead_time_days": 2,
            "change_failure_rate": 0.2,
            "recovery_hours": 12,
        }
    ) == "High"
