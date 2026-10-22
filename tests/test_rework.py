import csv

import pytest

from analysis.rework import compare, describe, run


def _rows():
    # rework sempre ≥ CFR (b); um repositório sem CFR (b) (todas as releases censuradas)
    pairs = [("0.5", "0.25"), ("0.2", "0.2"), ("0.8", "0.0"), ("0.0", "0.0"), ("0.6", "")]
    return [{"repo": f"o/{i}", "rework_rate": r, "cfr_delivery": c} for i, (r, c) in enumerate(pairs)]


def test_describe_median_iqr_and_zeros():
    rework, cfr = describe(_rows())
    assert (rework["n"], rework["median"], rework["q1"], rework["q3"]) == (5, 0.5, 0.2, 0.6)
    assert rework["zero_pct"] == 20
    assert (cfr["n"], cfr["median"], cfr["zero_pct"]) == (4, 0.1, 50)


def test_compare_pairs_only_repos_with_both_metrics():
    comp = compare(_rows())
    assert comp["n"] == 4
    assert (comp["rework_greater_pct"], comp["equal_pct"]) == (50, 50)
    assert comp["median_difference"] == pytest.approx(0.125)
    assert -1 <= comp["rho"] <= 1


def test_run_writes_outputs(tmp_path):
    pytest.importorskip("matplotlib")
    src = tmp_path / "metrics.csv"
    rows = _rows()
    with src.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    out = tmp_path / "out"
    result = run(src, out)
    assert result["repositories"] == 5
    for name in ("rework.csv", "rework.png", "rq08.md"):
        assert (out / name).exists()
