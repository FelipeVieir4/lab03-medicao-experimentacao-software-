import csv

from analysis.concordancia import load_rater
from analysis.rotular import Session, label

FIELDS = ["repo", "repo_url", "tag_name", "published_at", "release_url", "compare_url",
          "tipo_projeto", "entrega_real", "release_corretiva"]


def _sheet(path, rows):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for repo, tag in rows:
            writer.writerow({"repo": repo, "repo_url": f"https://github.com/{repo}", "tag_name": tag,
                             "published_at": "", "release_url": f"https://r/{repo}/{tag}",
                             "compare_url": f"https://c/{repo}/{tag}", "tipo_projeto": "",
                             "entrega_real": "", "release_corretiva": ""})


def _run(path, answers, **kw):
    replies, opened, said = iter(answers), [], []
    status = label(Session(path), ask=lambda _: next(replies), say=said.append, open_url=opened.append, **kw)
    return status, opened, said


def test_full_labeling_writes_valid_sheet(tmp_path):
    path = tmp_path / "rotulos_ana.csv"
    _sheet(path, [("o/a", "v1"), ("o/a", "v2"), ("o/b", "v1")])
    status, opened, _ = _run(path, ["b", "s", "s", "n", "c", "i", "N"])
    assert status == "concluido"
    assert opened[:3] == ["https://github.com/o/a", "https://r/o/a/v1", "https://c/o/a/v1"]
    _, labels = load_rater(path)  # a planilha resultante é aceita pela análise de concordância
    assert labels[("tipo_projeto", "o/a", "")] == "biblioteca"
    assert labels[("entrega_real", "o/b", "")] == "incerto"
    assert [labels[("release_corretiva", "o/a", t)] for t in ("v1", "v2")] == ["sim", "nao"]
    with path.open(encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert [r["tipo_projeto"] for r in rows] == ["biblioteca", "biblioteca", "cli"]  # repete nas linhas do repo
    assert "\r" not in path.read_text(encoding="utf-8")


def test_quit_and_resume_where_it_stopped(tmp_path):
    path = tmp_path / "rotulos_ana.csv"
    _sheet(path, [("o/a", "v1"), ("o/a", "v2")])
    assert _run(path, ["a", "s", "q"])[0] == "interrompido"
    session = Session(path)
    assert session.progress() == (2, 4)
    status, opened, _ = _run(path, ["s", "n"])
    assert status == "concluido" and opened[0] == "https://r/o/a/v1"  # recomeça na 1ª release


def test_undo_invalid_skip_and_reopen(tmp_path):
    path = tmp_path / "rotulos_ana.csv"
    _sheet(path, [("o/a", "v1")])
    # inválida, depois 'b'; volta e troca para 'o'; reabre links; pula a corretiva
    status, opened, said = _run(path, ["x", "b", "v", "o", "s", "r", "p"], with_compare=False)
    assert status == "concluido"
    assert any("inválida" in s for s in said) and any("puladas" in s for s in said)
    assert opened.count("https://r/o/a/v1") == 2 and "https://c/o/a/v1" not in opened
    session = Session(path)
    assert session.value("tipo_projeto", "o/a", "") == "outro"
    assert session.value("release_corretiva", "o/a", "v1") == ""
