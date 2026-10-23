import csv

import pytest

from analysis.fatores import (
    chi2_sf,
    cliffs_delta,
    delta_magnitude,
    epsilon_squared,
    holm,
    kruskal,
    language_groups,
    mannwhitney,
    quartile_groups,
    run,
)


@pytest.mark.parametrize("x, df, expected", [(5.99, 2, 0.05003662708658629), (0.5, 3, 0.9188914116546758),
                                             (40, 10, 1.694474393006737e-05)])
def test_chi2_sf_matches_scipy(x, df, expected):
    assert chi2_sf(x, df) == pytest.approx(expected, rel=1e-9)


def test_kruskal_matches_scipy():
    # exemplo da documentação do scipy.stats.kruskal
    h, p = kruskal([[2.9, 3.0, 2.5, 2.6, 3.2], [3.8, 2.7, 4.0, 2.4], [2.8, 3.4, 3.7, 2.2, 2.0]])
    assert h == pytest.approx(0.7714285714285722)
    assert p == pytest.approx(0.6799647735788936)


def test_mannwhitney_matches_scipy_with_ties():
    # o 3 aparece nos dois grupos (empate)
    u1, p = mannwhitney([1, 2, 3, 4, 5], [3, 6, 7, 8, 9, 10])
    assert u1 == 2.5
    assert p == pytest.approx(0.02810006355731762)


def test_mannwhitney_identical_values_gives_p_one():
    assert mannwhitney([1, 1, 1], [1, 1]) == (3.0, 1.0)


def test_holm_matches_statsmodels():
    assert holm([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.03, 0.06, 0.06, 0.02])


def test_effect_sizes():
    assert epsilon_squared(10, 101) == pytest.approx(0.1)
    # x todo acima de y: U1 = n1·n2 e δ = 1; todo abaixo: δ = −1
    assert cliffs_delta(mannwhitney([5, 6, 7], [1, 2])[0], 3, 2) == 1
    assert cliffs_delta(mannwhitney([1, 2], [5, 6, 7])[0], 2, 3) == -1
    assert delta_magnitude(0.1) == "desprezível"
    assert delta_magnitude(-0.4) == "médio"
    assert delta_magnitude(0.5) == "grande"


def test_quartile_and_language_groups():
    rows = [{"repo": str(i), "stars": str(i), "language": "Go" if i < 3 else f"L{i}"} for i in range(1, 9)]
    groups = quartile_groups(rows, "stars")
    assert [groups[str(i)] for i in range(1, 9)] == ["Q1", "Q1", "Q2", "Q2", "Q3", "Q3", "Q4", "Q4"]
    langs = language_groups(rows, minimum=2)
    assert langs["1"] == "Go" and langs["5"] == "Outras"


def test_run_writes_outputs(tmp_path):
    src = tmp_path / "metrics.csv"
    rows = []
    for i in range(70):  # 35 por linguagem (mínimo de 30 para não virar "Outras")
        rows.append({
            "repo": f"o/{i}", "language": "A" if i % 2 else "B", "stars": str(i), "contributors": str(70 - i),
            "age_years": str(i % 7), "deployment_frequency": str(i / 10), "lead_time_release_days": str(70 - i),
            "cfr_ci": str((i % 5) / 10), "recovery_hours": "" if i == 0 else str(i % 3),
        })
    with src.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = run(src, tmp_path / "out", consensus_path=None, with_plot=False)
    # 4 fatores × 4 métricas; linguagem tem 2 grupos -> Mann-Whitney
    assert len(result["tests"]) == 16
    language = [t for t in result["tests"] if t["factor"] == "linguagem"]
    assert {t["test"] for t in language} == {"Mann-Whitney"}
    stars_df = next(t for t in result["tests"] if t["factor"] == "estrelas" and t["metric"] == "deployment_frequency")
    assert stars_df["significant"] and stars_df["delta_q4_q1"] == 1
    recovery = next(t for t in result["tests"] if t["factor"] == "estrelas" and t["metric"] == "recovery_hours")
    assert recovery["n"] == 69  # repositório sem tempo de recuperação fica de fora
    for name in ("testes.csv", "posthoc.csv", "medianas.csv", "rq06.md"):
        assert (tmp_path / "out" / name).exists()
