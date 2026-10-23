import csv

import pytest

from analysis.concordancia import aggregate_raters, fleiss_kappa, landis_koch, load_rater, normalize
from analysis.concordancia import run as run_concordancia
from analysis.heuristica import VERSIONS, precision_recall_f1
from analysis.heuristica import run as run_heuristica

FIELDS = ["repo", "repo_url", "tag_name", "published_at", "release_url", "compare_url",
          "tipo_projeto", "entrega_real", "release_corretiva"]


def _write(path, rows, fields=None):
    fields = fields or list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _sheet(labels):
    """labels: lista de (repo, tag, tipo, entrega, corretiva)."""
    return [{"repo": r, "repo_url": "", "tag_name": t, "published_at": "", "release_url": "", "compare_url": "",
             "tipo_projeto": tp, "entrega_real": e, "release_corretiva": c} for r, t, tp, e, c in labels]


def test_fleiss_kappa_matches_fleiss_1971_example():
    # exemplo clássico (10 itens, 14 avaliadores, 5 categorias): κ ≈ 0,210
    table = [
        [0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6], [0, 3, 9, 2, 0], [2, 2, 8, 1, 1],
        [7, 7, 0, 0, 0], [3, 2, 6, 3, 0], [2, 5, 3, 2, 2], [6, 5, 2, 1, 0], [0, 2, 2, 3, 7],
    ]
    assert fleiss_kappa(table) == pytest.approx(0.20993, abs=1e-5)


def test_fleiss_kappa_edge_cases():
    table = aggregate_raters([["sim", "sim"], ["nao", "nao"]], ["sim", "nao"])
    assert table == [[2, 0], [0, 2]] and fleiss_kappa(table) == pytest.approx(1)
    assert fleiss_kappa(aggregate_raters([["sim", "sim"]] * 3, ["sim", "nao"])) is None  # uma só categoria
    with pytest.raises(ValueError):
        fleiss_kappa([[2, 0], [1, 0]])


def test_landis_koch_scale():
    assert [landis_koch(k) for k in (-0.1, 0.0, 0.2, 0.35, 0.6, 0.75, 0.9, None)] == [
        "pobre", "leve", "leve", "razoável", "moderada", "substancial", "quase perfeita", "indefinido"]


def test_normalize_accepts_synonyms_and_rejects_typos():
    assert normalize("tipo_projeto", " Aplicação/Serviço ") == "aplicacao"
    assert normalize("tipo_projeto", "Ferramenta CLI") == "cli"
    assert normalize("release_corretiva", "Não") == "nao"
    assert normalize("entrega_real", "") is None
    with pytest.raises(ValueError):
        normalize("release_corretiva", "talvez")


def test_repo_level_label_in_any_row_and_inconsistency(tmp_path):
    ok = tmp_path / "rotulos_a.csv"
    _write(ok, _sheet([("o/r", "v1", "cli", "sim", "nao"), ("o/r", "v2", "", "", "sim")]), FIELDS)
    _, labels = load_rater(ok)
    assert labels[("tipo_projeto", "o/r", "")] == "cli" and labels[("release_corretiva", "o/r", "v2")] == "sim"
    bad = tmp_path / "rotulos_b.csv"
    _write(bad, _sheet([("o/r", "v1", "cli", "sim", "nao"), ("o/r", "v2", "outro", "", "sim")]), FIELDS)
    with pytest.raises(ValueError, match="linha 3"):
        load_rater(bad)


def _gold(tmp_path):
    gold = tmp_path / "gold"
    gold.mkdir()
    _write(gold / "rotulos_ana.csv", _sheet([
        ("o/a", "v1.0.1", "biblioteca", "sim", "sim"), ("o/a", "v1.1.0", "", "", "nao"),
        ("o/b", "v2.0.1", "cli", "sim", "sim"), ("o/b", "v2.1.0", "", "", "nao"),
    ]), FIELDS)
    _write(gold / "rotulos_bia.csv", _sheet([
        ("o/a", "v1.0.1", "biblioteca", "sim", "sim"), ("o/a", "v1.1.0", "", "", "sim"),
        ("o/b", "v2.0.1", "aplicacao", "sim", "sim"), ("o/b", "v2.1.0", "", "", "nao"),
    ]), FIELDS)
    return gold


def test_concordancia_consensus_and_meeting_decisions(tmp_path):
    gold, out = _gold(tmp_path), tmp_path / "out"
    result = run_concordancia(gold, out)
    stats = {s["dimension"]: s for s in result["agreement"]}
    assert stats["release_corretiva"]["items"] == 4 and stats["release_corretiva"]["unanimous"] == 3
    assert stats["entrega_real"]["landis_koch"] == "indefinido"  # todos disseram "sim"
    # duas divergências (tipo de o/b e corretiva de o/a v1.1.0) vão para a reunião
    assert {(d["dimensao"], d["repo"], d["tag_name"]) for d in result["divergences"]} == {
        ("tipo_projeto", "o/b", ""), ("release_corretiva", "o/a", "v1.1.0")}
    pending = {r["tag_name"]: r for r in result["consensus"]}
    assert pending["v1.1.0"]["origem_release_corretiva"] == "pendente"
    assert pending["v2.0.1"]["tipo_projeto"] is None

    # a reunião decide uma das divergências; a decisão é preservada na nova execução
    path = gold / "divergencias.csv"
    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    for row in rows:
        if row["dimensao"] == "release_corretiva":
            row["decisao"], row["justificativa"] = "Não", "release notes falam de nova feature"
    _write(path, rows)
    result = run_concordancia(gold, out)
    final = {r["tag_name"]: r for r in result["consensus"]}
    assert (final["v1.1.0"]["release_corretiva"], final["v1.1.0"]["origem_release_corretiva"]) == ("nao", "reuniao")
    assert final["v1.0.1"]["origem_release_corretiva"] == "unanime"
    kept = [d for d in result["divergences"] if d["dimensao"] == "release_corretiva"][0]
    assert kept["justificativa"] == "release notes falam de nova feature"
    assert (out / "kappa.csv").exists() and (out / "concordancia.md").exists()


def test_precision_recall_f1_guide_example():
    # enunciado: 40 marcadas, 30 corretas, 50 corretivas no consenso -> P 0,75, R 0,60, F1 ≈ 0,667
    truth = [True] * 30 + [False] * 10 + [True] * 20 + [False] * 40
    predicted = [True] * 40 + [False] * 60
    m = precision_recall_f1(truth, predicted)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (30, 10, 20, 40)
    assert (m["precision"], m["recall"]) == (0.75, 0.6) and m["f1"] == pytest.approx(2 / 3)
    assert precision_recall_f1([True], [False])["f1"] == 0
    assert precision_recall_f1([False], [False])["precision"] is None


def _f(patch=None, fix=False, line_patch=None, fix_terms=0, feature_terms=0):
    return {"patch": patch, "fix": fix, "line_patch": line_patch, "fix_terms": fix_terms,
            "feature_terms": feature_terms}


def test_versions_rules():
    v1 = VERSIONS["v1"][1]
    assert v1(_f(True, True)) and not v1(_f(True, False)) and not v1(_f(False, True)) and v1(_f(None, True))
    assert VERSIONS["v4"][1](_f(False, True)) and not VERSIONS["v3"][1](_f(None, True))
    # v5/v7: patch da própria linha, mesmo que a anterior por data seja de outra linha
    assert VERSIONS["v5"][1](_f(patch=False, line_patch=True))
    assert VERSIONS["v7"][1](_f(line_patch=True, fix=True)) and not VERSIONS["v7"][1](_f(line_patch=True))
    v6 = VERSIONS["v6"][1]
    assert v6(_f(line_patch=True, fix_terms=2, feature_terms=2))
    assert not v6(_f(line_patch=True, fix_terms=1, feature_terms=3))
    assert not v6(_f(line_patch=False, fix_terms=5))
    assert v6(_f(line_patch=None, fix_terms=2, feature_terms=1)) and not v6(_f(line_patch=None))
    assert v6(_f(fix_terms=None)) is None  # sem release notes: não avaliável


def test_v6_matches_pipeline_rule():
    from pipeline.dataset import is_corrective_v6, is_line_patch, notes_terms
    cases = [("v2.3.1", "## Bug fixes\n- fix crash"), ("v2.3.1", "## New features\n- add export"),
             ("8.19.9", ""), ("v2.4.0", "fix fix fix"), ("nightly", "fix crash"), ("nightly", "")]
    for tag, body in cases:
        fix_terms, feature_terms = notes_terms(body)
        features = _f(line_patch=is_line_patch(tag), fix_terms=fix_terms, feature_terms=feature_terms)
        assert VERSIONS["v6"][1](features) == is_corrective_v6(tag, body), (tag, body)


def test_heuristica_end_to_end(tmp_path):
    gold, out = _gold(tmp_path), tmp_path / "out"
    run_concordancia(gold, out)
    releases = tmp_path / "releases.csv"
    _write(releases, [
        {"repo": "o/a", "tag_name": "v1.0.1", "patch_bump": "True", "has_fix_commit": "True"},
        {"repo": "o/a", "tag_name": "v1.1.0", "patch_bump": "False", "has_fix_commit": "True"},
        {"repo": "o/b", "tag_name": "v2.0.1", "patch_bump": "True", "has_fix_commit": "False"},
        {"repo": "o/b", "tag_name": "v2.1.0", "patch_bump": "", "has_fix_commit": ""},  # primeira release
    ])
    result = run_heuristica(gold / "consenso.csv", releases, out)
    # v1.1.0 está pendente (sem consenso) e v2.1.0 não tem release anterior
    assert result["skipped"] == {"sem_consenso": 1, "sem_release_anterior": 1, "fora_do_dataset": 0}
    v1 = next(m for m in result["metrics"] if m["version"] == "v1")
    assert (v1["tp"], v1["fn"], v1["precision"], v1["recall"]) == (1, 1, 1.0, 0.5)
    report = (out / "heuristica.md").read_text(encoding="utf-8")
    # sem as colunas das release notes, a v6 não é avaliada e o relatório avisa
    assert report.count("| v") == 6 and "Não avaliadas (faltam as release notes): v6" in report
