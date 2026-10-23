import csv

import pytest

from analysis.sensibilidade import classify, compare, run, weighted_kappa


def test_weighted_kappa_matches_sklearn_with_ordered_labels():
    a = ["Low", "High", "Elite", "Medium", "High"]
    b = ["Low", "Medium", "Elite", "Medium", "Low"]
    # cohen_kappa_score(a, b, weights="linear", labels=["Low", "Medium", "High", "Elite"])
    assert weighted_kappa(a, b) == pytest.approx(0.5454545454545454)
    assert weighted_kappa(a, a) == 1
    assert weighted_kappa([], []) is None


def test_weighted_kappa_penalises_distant_changes_more():
    base = ["Elite", "High", "Medium", "Low"] * 5
    near = ["High", "High", "Medium", "Low"] * 5  # Elite -> High
    far = ["Low", "High", "Medium", "Low"] * 5  # Elite -> Low
    assert weighted_kappa(base, near) > weighted_kappa(base, far)


def _row(**values):
    row = {
        "repo": "o/r", "deployment_frequency": "2", "deployment_frequency_with_pre": "8",
        "deployment_frequency_tags": "0.1", "lead_time_release_days": "40", "lead_time_commit_days": "3",
        "lead_time_commit_days_with_pre": "3", "cfr_ci": "0.05", "cfr_delivery": "0.5", "recovery_hours": "2",
    }
    row.update(values)
    return row


def test_classify_each_combination():
    row = _row()
    # C1: DF High (3), LT (a) 40 d Low (1), CFR (a) Elite (4), recuperação High (3) -> (1,3,3,4) -> High
    assert classify(row, "C1")["overall"] == "High"
    # C2: DF Elite (4), LT (b) High (3), CFR (b) Low (1), recuperação High (3) -> High
    assert classify(row, "C2") == {"deployment_frequency": "Elite", "lead_time_days": "High",
                                   "change_failure_rate": "Low", "recovery_hours": "High", "overall": "High"}
    # C3: DF por tag Low (1), LT (b) High, CFR (a) Elite, recuperação High -> (1,3,3,4) -> High
    assert classify(row, "C3")["deployment_frequency"] == "Low"


def test_missing_metric_leaves_overall_empty():
    assert classify(_row(recovery_hours=""), "C1")["overall"] is None


def test_compare_counts_changes():
    table = [
        {f"{c}_{m}": v for c in ("C1", "C2", "C3") for m, v in
         (("overall", "High"), ("deployment_frequency", "High"), ("lead_time_days", "Low"),
          ("change_failure_rate", "Elite"), ("recovery_hours", "High"))},
    ]
    table[0]["C2_overall"] = "Medium"
    pairs = {(p["pair"], p["metric"]): p for p in compare(table)}
    assert pairs[("C1 × C2", "overall")]["changed"] == 1
    assert pairs[("C1 × C2", "overall")]["worse_in_second"] == 1
    assert pairs[("C1 × C3", "overall")]["changed"] == 0


def test_run_writes_outputs(tmp_path):
    src = tmp_path / "metrics.csv"
    rows = [_row(repo=f"o/{i}", recovery_hours=str(0.5 + i)) for i in range(5)]
    with src.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = run(src, tmp_path / "out", with_plot=False)
    assert result["repositories"] == 5
    for name in ("classes.csv", "pares.csv", "distribuicao.csv", "transicoes.csv", "rq07.md"):
        assert (tmp_path / "out" / name).exists()
