import pytest
from datetime import datetime
from src.metrics import calculate_cfr_proxy_ci, calculate_recovery_time, get_dora_classification_cfr, get_dora_classification_recovery_time

@pytest.fixture
def workflow_runs_cfr_sample():
    return [
        {'conclusion': 'success'},
        {'conclusion': 'failure'},
        {'conclusion': 'success'},
        {'conclusion': 'timed_out'},
        {'conclusion': 'cancelled'},  # Should be ignored
        {'conclusion': 'startup_failure'},
    ]

@pytest.fixture
def workflow_runs_recovery_sample():
    return [
        {'workflow_id': 1, 'conclusion': 'success', 'created_at': '2024-01-01T09:00:00Z', 'run_started_at': '2024-01-01T09:00:00Z', 'updated_at': '2024-01-01T09:10:00Z'},
        # Episode starts here
        {'workflow_id': 1, 'conclusion': 'failure', 'created_at': '2024-01-01T10:00:00Z', 'run_started_at': '2024-01-01T10:00:00Z', 'updated_at': '2024-01-01T10:10:00Z'},
        {'workflow_id': 1, 'conclusion': 'failure', 'created_at': '2024-01-01T10:30:00Z', 'run_started_at': '2024-01-01T10:30:00Z', 'updated_at': '2024-01-01T10:40:00Z'},
        # Episode ends here
        {'workflow_id': 1, 'conclusion': 'success', 'created_at': '2024-01-01T11:15:00Z', 'run_started_at': '2024-01-01T11:15:00Z', 'updated_at': '2024-01-01T11:20:00Z'},
        # Episode that gets censored (no success after it)
        {'workflow_id': 1, 'conclusion': 'failure', 'created_at': '2024-01-01T12:00:00Z', 'run_started_at': '2024-01-01T12:00:00Z', 'updated_at': '2024-01-01T12:10:00Z'},
    ]

def test_calculate_cfr_proxy_ci(workflow_runs_cfr_sample):
    cfr = calculate_cfr_proxy_ci(workflow_runs_cfr_sample)
    # successes = 2, failures = 3 (failure, timed_out, startup_failure)
    assert cfr == 3 / 5

def test_calculate_cfr_empty():
    assert calculate_cfr_proxy_ci([]) is None

def test_calculate_recovery_time(workflow_runs_recovery_sample):
    metrics = calculate_recovery_time(workflow_runs_recovery_sample)
    
    # Episode 1: start = 10:00:00, success = 11:20:00 -> delta = 1 hour 20 minutes = 1.333... hours
    expected_recovery_time = (datetime(2024, 1, 1, 11, 20) - datetime(2024, 1, 1, 10, 0)).total_seconds() / 3600
    assert metrics['median_recovery_time_hours'] == pytest.approx(expected_recovery_time)
    
    # 2 episodes total, 1 is censored
    assert metrics['total_episodes'] == 2
    assert metrics['censored_ratio'] == 0.5

def test_dora_classification():
    assert get_dora_classification_cfr(0.10) == 'Elite'
    assert get_dora_classification_cfr(0.20) == 'High'
    assert get_dora_classification_cfr(0.40) == 'Medium'
    assert get_dora_classification_cfr(0.50) == 'Low'
    assert get_dora_classification_cfr(None) is None
    
    assert get_dora_classification_recovery_time(0.5) == 'Elite'
    assert get_dora_classification_recovery_time(12) == 'High'
    assert get_dora_classification_recovery_time(48) == 'Medium'
    assert get_dora_classification_recovery_time(200) == 'Low'
    assert get_dora_classification_recovery_time(None) is None
