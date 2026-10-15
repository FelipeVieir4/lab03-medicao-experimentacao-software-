import csv

from analysis.descritivas import censoring, classification, describe, run


def _row(**kw):
    base = {
        "repo": "o/r", "deployment_frequency": "1", "lead_time_release_days": "2", "lead_time_commit_days": "3",
        "cfr_ci": "0.1", "cfr_delivery": "0.2", "recovery_hours": "4",
        "n_recovery_episodes": "0", "n_recovery_censored": "0",
        "n_releases_cfr_evaluated": "0", "n_releases_cfr_censored": "0",
        "class_c1_deployment_frequency": "High", "class_c1_lead_time_days": "High",
        "class_c1_change_failure_rate": "Elite", "class_c1_recovery_hours": "High", "class_c1_overall": "High",
    }
    base.update(kw)
    return base


def test_describe_median_iqr_and_missing():
    rows = [_row(deployment_frequency=str(v)) for v in (1, 2, 3, 4, 5)] + [_row(deployment_frequency="")]
    df = next(d for d in describe(rows) if d["metric"] == "deployment_frequency")
    assert (df["n"], df["missing"], df["median"], df["q1"], df["q3"], df["iqr"]) == (5, 1, 3, 2, 4, 2)


def test_classification_percent_over_classified():
    rows = [_row(), _row(class_c1_overall="Elite"), _row(class_c1_overall="")]
    overall = next(c for c in classification(rows) if c["metric"] == "class_c1_overall")
    assert (overall["n"], overall["missing"], overall["elite"], overall["high"]) == (2, 1, 1, 1)
    assert overall["elite_pct"] == 50 and overall["low_pct"] == 0


def test_censoring_pooled_and_per_repo():
    rows = [
        _row(n_recovery_episodes="9", n_recovery_censored="1"),
        _row(n_recovery_episodes="10", n_recovery_censored="0"),
        _row(),  # sem episódios: fora da mediana por repositório
    ]
    rec = next(c for c in censoring(rows) if c["item"] == "recovery_episodes")
    assert (rec["total"], rec["censored"], rec["censored_pct"]) == (20, 1, 5)
    assert (rec["repos_with_items"], rec["repos_with_censored"], rec["median_repo_censored_pct"]) == (2, 1, 5)
    cfr = next(c for c in censoring(rows) if c["item"] == "releases_cfr_b")
    assert cfr["total"] == 0 and cfr["censored_pct"] is None


def test_run_writes_outputs(tmp_path):
    src = tmp_path / "metrics.csv"
    rows = [_row(), _row(repo="o/s", deployment_frequency="3")]
    with src.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    out = tmp_path / "out"
    result = run(src, out)
    assert result["repositories"] == 2
    for name in ("descritivas.csv", "classificacao_c1.csv", "censura.csv", "rq01_04.md"):
        assert (out / name).exists()
    assert "| RQ 01 | Deployment frequency | releases/semana | 2 | 2,00 |" in (out / "rq01_04.md").read_text(encoding="utf-8")
