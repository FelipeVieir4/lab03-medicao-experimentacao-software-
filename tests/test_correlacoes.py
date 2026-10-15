import csv
import math

import pytest

from analysis.correlacoes import betainc, ranks, run, spearmanr, strength


def test_ranks_average_ties():
    assert ranks([10, 20, 20, 5]) == [2, 3.5, 3.5, 1]


@pytest.mark.parametrize("t", [0.5, 1, 3, 10])
def test_betainc_matches_t_closed_forms(t):
    # p bilateral do teste t: 1 g.l. (Cauchy) e 2 g.l. têm forma fechada
    assert betainc(0.5, 0.5, 1 / (1 + t * t)) == pytest.approx(1 - 2 / math.pi * math.atan(t), abs=1e-12)
    assert betainc(1, 0.5, 2 / (2 + t * t)) == pytest.approx(1 - t / math.sqrt(2 + t * t), abs=1e-12)


def test_spearman_known_values():
    rho, p = spearmanr([1, 2, 3, 4, 5], [5, 6, 7, 8, 7])
    # valores de referência do scipy.stats.spearmanr
    assert rho == pytest.approx(0.8207826816681233)
    assert p == pytest.approx(0.08858700531354381)
    assert spearmanr([1, 2, 3], [3, 2, 1]) == (-1.0, 0.0)


def test_strength_labels():
    assert strength(0.05) == "desprezível"
    assert strength(0.2) == "fraca positiva"
    assert strength(-0.5) == "moderada negativa"
    assert strength(0.8) == "forte positiva"


def test_run_writes_outputs(tmp_path):
    pytest.importorskip("matplotlib")
    src = tmp_path / "metrics.csv"
    rows = [
        {"repo": f"o/{i}", "deployment_frequency": str(i + 1), "cfr_ci": str(i / 10), "cfr_delivery": "" if i == 0 else str(1 - i / 10)}
        for i in range(6)
    ]
    with src.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    out = tmp_path / "out"
    result = run(src, out)
    a, b = result["spearman"]
    assert (a["n"], a["rho"]) == (6, pytest.approx(1))
    assert (b["n"], b["rho"]) == (5, pytest.approx(-1))
    assert result["cfr_a_vs_b"]["rho"] == pytest.approx(-1)
    for name in ("spearman.csv", "dispersao.png", "rq05.md"):
        assert (out / name).exists()
