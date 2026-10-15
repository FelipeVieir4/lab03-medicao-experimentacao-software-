"""Seção 6: concordância entre avaliadores (kappa de Fleiss) e rótulo de consenso.

Uso: python -m analysis.concordancia [--gold PASTA] [--output PASTA]

Lê data/gold/rotulos_<avaliador>.csv (um arquivo por avaliador, ao menos dois) e gera:
  - reports/resultados/validacao/kappa.csv         kappa de Fleiss por dimensão
  - reports/resultados/validacao/concordancia.md   tabela formatada para o artigo
  - data/gold/divergencias.csv  casos sem maioria, com a coluna `decisao` para a reunião
  - data/gold/consenso.csv      rótulo de consenso de cada release (entrada da #10)

As decisões já escritas em divergencias.csv são preservadas a cada execução.
Protocolo completo em docs/protocolo-rotulagem.md.
"""
from __future__ import annotations

import argparse
import csv
import unicodedata
from collections import Counter
from pathlib import Path

from analysis.descritivas import _fmt
from pipeline.dataset import write_csv

DEFAULT_GOLD = Path("data/gold")
DEFAULT_OUTPUT = Path("reports/resultados/validacao")

# Valores aceitos em cada dimensão (após minúsculas e remoção de acentos) -> rótulo canônico
VALUES = {
    "tipo_projeto": {
        "biblioteca": "biblioteca", "biblioteca/framework": "biblioteca", "framework": "biblioteca",
        "lib": "biblioteca",
        "aplicacao": "aplicacao", "aplicacao/servico": "aplicacao", "servico": "aplicacao", "app": "aplicacao",
        "cli": "cli", "ferramenta cli": "cli", "ferramenta": "cli",
        "outro": "outro",
    },
    "entrega_real": {"sim": "sim", "s": "sim", "nao": "nao", "n": "nao", "incerto": "incerto"},
    "release_corretiva": {"sim": "sim", "s": "sim", "nao": "nao", "n": "nao"},
}
CATEGORIES = {
    "tipo_projeto": ["biblioteca", "aplicacao", "cli", "outro"],
    "entrega_real": ["sim", "nao", "incerto"],
    "release_corretiva": ["sim", "nao"],
}
# Dimensões rotuladas uma vez por repositório (repetidas nas 5 linhas) e por release
REPO_DIMENSIONS = ("tipo_projeto", "entrega_real")
RELEASE_DIMENSIONS = ("release_corretiva",)
LABELS = {
    "tipo_projeto": "Tipo do projeto",
    "entrega_real": "Releases são entregas reais",
    "release_corretiva": "Release corretiva",
}


def normalize(dimension: str, value: str | None) -> str | None:
    """Rótulo canônico, None se vazio; ValueError se o valor não for aceito."""
    text = (value or "").strip().lower()
    if not text:
        return None
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    text = " ".join(text.replace(" / ", "/").split())
    if text not in VALUES[dimension]:
        raise ValueError(f"{dimension}: valor '{value}' não aceito (use {', '.join(CATEGORIES[dimension])})")
    return VALUES[dimension][text]


def load_rater(path: Path) -> tuple[list[dict], dict]:
    """Linhas do arquivo e rótulos {(dimensão, repo, tag): rótulo} de um avaliador.

    Dimensões de repositório usam tag = "" e aceitam o valor em qualquer uma das linhas
    do repositório; valores diferentes no mesmo repositório são erro.
    """
    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    labels: dict[tuple[str, str, str], str] = {}
    for line, row in enumerate(rows, start=2):
        repo, tag = row["repo"], row["tag_name"]
        try:
            for dim in REPO_DIMENSIONS:
                value = normalize(dim, row.get(dim))
                if value is None:
                    continue
                key = (dim, repo, "")
                if labels.get(key, value) != value:
                    raise ValueError(f"{dim}: valores diferentes para o mesmo repositório ({labels[key]} e {value})")
                labels[key] = value
            for dim in RELEASE_DIMENSIONS:
                value = normalize(dim, row.get(dim))
                if value is not None:
                    labels[(dim, repo, tag)] = value
        except ValueError as error:
            raise ValueError(f"{path.name}, linha {line} ({repo} {tag}): {error}") from None
    return rows, labels


def load_raters(gold_dir: Path) -> tuple[list[dict], dict[str, dict]]:
    files = sorted(gold_dir.glob("rotulos_*.csv"))
    if len(files) < 2:
        raise SystemExit(f"são necessários ao menos dois arquivos rotulos_<avaliador>.csv em {gold_dir}")
    raters, base_rows = {}, None
    for path in files:
        rows, labels = load_rater(path)
        raters[path.stem.removeprefix("rotulos_")] = labels
        keys = [(r["repo"], r["tag_name"]) for r in rows]
        if base_rows is None:
            base_rows, base_keys = rows, keys
        elif keys != base_keys:
            raise SystemExit(f"{path.name} não tem as mesmas linhas (repo, tag_name) dos demais arquivos")
    return base_rows, raters


def items(rows: list[dict], dimension: str) -> list[tuple[str, str]]:
    """Itens (repo, tag) avaliados numa dimensão, na ordem da planilha."""
    if dimension in REPO_DIMENSIONS:
        return list(dict.fromkeys((r["repo"], "") for r in rows))
    return [(r["repo"], r["tag_name"]) for r in rows]


def aggregate_raters(ratings: list[list[str]], categories: list[str]) -> list[list[int]]:
    """Tabela itens × categorias com o nº de avaliadores em cada uma (como no statsmodels)."""
    return [[labels.count(c) for c in categories] for labels in ratings]


def fleiss_kappa(table: list[list[int]]) -> float | None:
    """Kappa de Fleiss (1971) para uma tabela itens × categorias com nº fixo de avaliadores."""
    n_items = len(table)
    if n_items == 0:
        return None
    n = sum(table[0])
    if n < 2 or any(sum(row) != n for row in table):
        raise ValueError("todos os itens precisam do mesmo número (≥ 2) de avaliações")
    p_j = [sum(row[j] for row in table) / (n_items * n) for j in range(len(table[0]))]
    p_i = [(sum(x * x for x in row) - n) / (n * (n - 1)) for row in table]
    p_bar, p_e = sum(p_i) / n_items, sum(p * p for p in p_j)
    if p_e == 1:
        return None  # todos usaram uma única categoria: kappa indefinido
    return (p_bar - p_e) / (1 - p_e)


def landis_koch(kappa: float | None) -> str:
    """Escala de Landis & Koch (1977)."""
    if kappa is None:
        return "indefinido"
    if kappa < 0:
        return "pobre"
    for limit, label in ((0.20, "leve"), (0.40, "razoável"), (0.60, "moderada"), (0.80, "substancial")):
        if kappa <= limit:
            return label
    return "quase perfeita"


def agreement(rows: list[dict], raters: dict[str, dict]) -> list[dict]:
    """Kappa de Fleiss e % de concordância total em cada dimensão (itens rotulados por todos)."""
    names = list(raters)
    result = []
    for dim in (*REPO_DIMENSIONS, *RELEASE_DIMENSIONS):
        all_items = items(rows, dim)
        ratings = [[raters[r].get((dim, *item)) for r in names] for item in all_items]
        complete = [labels for labels in ratings if None not in labels]
        kappa = fleiss_kappa(aggregate_raters(complete, CATEGORIES[dim])) if complete else None
        unanimous = sum(len(set(labels)) == 1 for labels in complete)
        result.append(
            {
                "dimension": dim,
                "label": LABELS[dim],
                "raters": len(names),
                "items": len(all_items),
                "items_complete": len(complete),
                "unanimous": unanimous,
                "agreement_pct": 100 * unanimous / len(complete) if complete else None,
                "fleiss_kappa": kappa,
                "landis_koch": landis_koch(kappa),
            }
        )
    return result


def load_decisions(path: Path) -> dict[tuple[str, str, str], dict]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as file:
        return {(r["dimensao"], r["repo"], r["tag_name"]): r for r in csv.DictReader(file)}


def consensus(rows: list[dict], raters: dict[str, dict], decisions: dict) -> tuple[list[dict], list[dict]]:
    """Rótulo de consenso por maioria simples; sem maioria, vale a decisão da reunião.

    Retorna (linhas de consenso por release, linhas de divergências para a reunião).
    """
    names = list(raters)
    resolved: dict[tuple[str, str, str], tuple[str | None, str]] = {}
    divergences = []
    for dim in (*REPO_DIMENSIONS, *RELEASE_DIMENSIONS):
        for repo, tag in items(rows, dim):
            key = (dim, repo, tag)
            labels = [raters[r].get(key) for r in names]
            if None in labels:
                resolved[key] = (None, "incompleto")
                continue
            top, count = Counter(labels).most_common(1)[0]
            if count == len(labels):
                resolved[key] = (top, "unanime")
                continue
            if count > len(labels) / 2:
                resolved[key] = (top, "maioria")
                continue
            previous = decisions.get(key, {})
            decision = normalize(dim, previous.get("decisao"))
            resolved[key] = (decision, "reuniao") if decision else (None, "pendente")
            divergences.append(
                {
                    "dimensao": dim,
                    "repo": repo,
                    "tag_name": tag,
                    **{f"rotulo_{r}": label for r, label in zip(names, labels)},
                    "decisao": previous.get("decisao", ""),
                    "justificativa": previous.get("justificativa", ""),
                }
            )
    result = []
    for row in rows:
        out = {"repo": row["repo"], "tag_name": row["tag_name"], "release_url": row.get("release_url", "")}
        for dim in (*REPO_DIMENSIONS, *RELEASE_DIMENSIONS):
            key = (dim, row["repo"], "" if dim in REPO_DIMENSIONS else row["tag_name"])
            out[dim], out[f"origem_{dim}"] = resolved[key]
        result.append(out)
    return result, divergences


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{_fmt(value, 1)}%"


def to_markdown(stats: list[dict], names: list[str], consensus_rows: list[dict], divergences: list[dict]) -> str:
    lines = [
        "# Validação manual: concordância entre avaliadores",
        "",
        f"Gerado por `python -m analysis.concordancia`. Avaliadores: {', '.join(names)}.",
        "",
        "## Tabela: kappa de Fleiss por dimensão",
        "",
        "| Dimensão | Itens | Rotulados por todos | Concordância total | κ de Fleiss | Landis & Koch |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for s in stats:
        lines.append(
            f"| {s['label']} | {s['items']} | {s['items_complete']} | {_pct(s['agreement_pct'])} | "
            f"{_fmt(s['fleiss_kappa'], 3)} | {s['landis_koch']} |"
        )
    pending = sum(not d["decisao"] for d in divergences)
    origins = Counter(r["origem_release_corretiva"] for r in consensus_rows)
    lines += [
        "",
        "## Consenso",
        "",
        f"- Casos sem maioria (enviados à reunião): {len(divergences)}, dos quais {pending} ainda sem decisão.",
        "- Origem do rótulo de consenso da release corretiva: "
        + ", ".join(f"{k} = {v}" for k, v in sorted(origins.items())) + ".",
    ]
    return "\n".join(lines) + "\n"


def run(gold_dir: Path, output_dir: Path) -> dict:
    rows, raters = load_raters(gold_dir)
    stats = agreement(rows, raters)
    divergence_path = gold_dir / "divergencias.csv"
    consensus_rows, divergences = consensus(rows, raters, load_decisions(divergence_path))
    write_csv(output_dir / "kappa.csv", stats)
    write_csv(gold_dir / "consenso.csv", consensus_rows)
    if divergences:
        write_csv(divergence_path, divergences)
    elif divergence_path.exists():
        divergence_path.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "concordancia.md").write_text(
        to_markdown(stats, list(raters), consensus_rows, divergences), encoding="utf-8"
    )
    return {"raters": list(raters), "agreement": stats, "consensus": consensus_rows, "divergences": divergences}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Kappa de Fleiss e consenso da amostra-ouro")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        result = run(args.gold, args.output)
    except ValueError as error:
        raise SystemExit(f"Rótulo inválido: {error}")
    print((args.output / "concordancia.md").read_text(encoding="utf-8"))
    pending = sum(not d["decisao"] for d in result["divergences"])
    if pending:
        print(f"{pending} divergência(s) sem decisão: preencha a coluna `decisao` em "
              f"{args.gold / 'divergencias.csv'} e rode de novo.")


if __name__ == "__main__":
    main()
