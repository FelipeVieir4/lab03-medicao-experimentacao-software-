"""RQ 07: análise de sensibilidade da classificação DORA à definição operacional.

Uso: python -m analysis.sensibilidade [--input CSV] [--output PASTA]

Lê apenas data/processed/repositories_metrics.csv (não usa a API). Classifica cada
repositório em Elite/High/Medium/Low em três combinações de definições operacionais:

  C1 (referência)  release estável       lead time (a)  CFR (a)
  C2               release + pré-release lead time (b)  CFR (b)
  C3               tag                   lead time (b)  CFR (a)

O tempo de recuperação é o mesmo nas três. Na C3, só a unidade da frequência de deploy
muda para tags; o lead time por tag não foi coletado, então ela usa o lead time (b)
das releases estáveis. Para cada par de combinações calcula a % de repositórios que
mudam de categoria e o kappa de Cohen com ponderação linear (como
sklearn.metrics.cohen_kappa_score(..., weights='linear')), na classificação geral e
em cada métrica. Gera em reports/resultados/rq07/:
  - pares.csv        % de mudança e kappa ponderado por par e por métrica
  - distribuicao.csv contagem de Elite/High/Medium/Low em cada combinação
  - transicoes.csv   matriz de transição da classificação geral (C1 × C2, C1 × C3, C2 × C3)
  - classes.csv      classificação de cada repositório nas três combinações
  - distribuicao.png barras empilhadas da classificação geral (requer matplotlib)
  - rq07.md          tabelas formatadas para o artigo
"""
from __future__ import annotations

import argparse
from itertools import combinations
from pathlib import Path

from analysis.descritivas import _fmt, load_rows, to_float
from pipeline.dataset import write_csv
from pipeline.metrics import classify_metric, classify_repository

DEFAULT_INPUT = Path("data/processed/repositories_metrics.csv")
DEFAULT_OUTPUT = Path("reports/resultados/rq07")

# combinação -> (descrição, coluna de cada métrica)
COMBINATIONS = {
    "C1": ("release, lead time (a), CFR (a)", {
        "deployment_frequency": "deployment_frequency",
        "lead_time_days": "lead_time_release_days",
        "change_failure_rate": "cfr_ci",
        "recovery_hours": "recovery_hours",
    }),
    "C2": ("release + pré-release, lead time (b), CFR (b)", {
        "deployment_frequency": "deployment_frequency_with_pre",
        "lead_time_days": "lead_time_commit_days_with_pre",
        "change_failure_rate": "cfr_delivery",
        "recovery_hours": "recovery_hours",
    }),
    "C3": ("tag, lead time (b), CFR (a)", {
        "deployment_frequency": "deployment_frequency_tags",
        "lead_time_days": "lead_time_commit_days",
        "change_failure_rate": "cfr_ci",
        "recovery_hours": "recovery_hours",
    }),
}
METRIC_LABELS = {
    "overall": "Geral",
    "deployment_frequency": "Deployment frequency",
    "lead_time_days": "Lead time",
    "change_failure_rate": "CFR",
    "recovery_hours": "Tempo de recuperação",
}
# Ordem crescente de desempenho: a distância entre categorias vizinhas é 1
CATEGORIES = ["Low", "Medium", "High", "Elite"]
SERIES = {"Elite": "#1f5fae", "High": "#5b9bd5", "Medium": "#f0a35e", "Low": "#c9483b"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def classify(row: dict, combo: str) -> dict[str, str | None]:
    """Categoria de cada métrica e a geral do repositório numa combinação."""
    values = {metric: to_float(row.get(column)) for metric, column in COMBINATIONS[combo][1].items()}
    result = {metric: classify_metric(metric, v) if v is not None else None for metric, v in values.items()}
    result["overall"] = classify_repository(values) if all(v is not None for v in values.values()) else None
    return result


def weighted_kappa(a: list[str], b: list[str], labels: list[str] = CATEGORIES) -> float | None:
    """Kappa de Cohen com pesos lineares |i − j| sobre as categorias ordenadas.

    Igual a cohen_kappa_score(a, b, weights='linear', labels=CATEGORIES). Atenção: sem o
    parâmetro labels, o sklearn ordena os rótulos em ordem alfabética (Elite, High, Low,
    Medium) e a ponderação linear passa a usar distâncias erradas (Low ficaria entre
    High e Medium). Na C1 × C2, por exemplo, o kappa geral sairia 0,558 em vez de 0,564,
    e o do lead time, 0,457 em vez de 0,554.
    """
    k, n = len(labels), len(a)
    if n == 0:
        return None
    index = {label: i for i, label in enumerate(labels)}
    observed = [[0] * k for _ in range(k)]
    for x, y in zip(a, b):
        observed[index[x]][index[y]] += 1
    rows = [sum(line) for line in observed]
    cols = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    disagreement = sum(abs(i - j) * observed[i][j] for i in range(k) for j in range(k))
    expected = sum(abs(i - j) * rows[i] * cols[j] / n for i in range(k) for j in range(k))
    return 1 - disagreement / expected if expected else None


def classes(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        out = {"repo": row["repo"]}
        for combo in COMBINATIONS:
            for metric, category in classify(row, combo).items():
                out[f"{combo}_{metric}"] = category
        result.append(out)
    return result


def compare(table: list[dict]) -> list[dict]:
    result = []
    for x, y in combinations(COMBINATIONS, 2):
        for metric in METRIC_LABELS:
            pairs = [(r[f"{x}_{metric}"], r[f"{y}_{metric}"]) for r in table]
            pairs = [(a, b) for a, b in pairs if a and b]
            n = len(pairs)
            changed = sum(a != b for a, b in pairs)
            better = sum(CATEGORIES.index(b) > CATEGORIES.index(a) for a, b in pairs)
            distance = [abs(CATEGORIES.index(b) - CATEGORIES.index(a)) for a, b in pairs]
            result.append({
                "pair": f"{x} × {y}", "metric": metric, "label": METRIC_LABELS[metric], "n": n,
                "changed": changed, "changed_pct": 100 * changed / n if n else None,
                "better_in_second": better, "worse_in_second": changed - better,
                "two_or_more_levels": sum(d >= 2 for d in distance),
                "kappa_linear": weighted_kappa([a for a, _ in pairs], [b for _, b in pairs]),
            })
    return result


def distribution(table: list[dict]) -> list[dict]:
    result = []
    for combo, (description, _) in COMBINATIONS.items():
        for metric in METRIC_LABELS:
            values = [r[f"{combo}_{metric}"] for r in table if r[f"{combo}_{metric}"]]
            row = {"combination": combo, "description": description, "metric": metric, "n": len(values)}
            for c in reversed(CATEGORIES):
                row[c.lower()] = values.count(c)
                row[f"{c.lower()}_pct"] = 100 * values.count(c) / len(values) if values else None
            result.append(row)
    return result


def transitions(table: list[dict]) -> list[dict]:
    result = []
    for x, y in combinations(COMBINATIONS, 2):
        for a in reversed(CATEGORIES):
            row = {"pair": f"{x} × {y}", "from": a}
            for b in reversed(CATEGORIES):
                row[b] = sum(1 for r in table if r[f"{x}_overall"] == a and r[f"{y}_overall"] == b)
            result.append(row)
    return result


def plot(dist: list[dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    overall = [d for d in dist if d["metric"] == "overall"]
    fig, ax = plt.subplots(figsize=(8.4, 2.9))
    for i, d in enumerate(overall):
        left = 0.0
        for c in reversed(CATEGORIES):
            width = d[f"{c.lower()}_pct"] or 0
            ax.barh(i, width, left=left, color=SERIES[c], edgecolor="white", linewidth=1,
                    label=c if i == 0 else None)
            if width >= 5:
                ax.text(left + width / 2, i, f"{_fmt(width, 0)}%", ha="center", va="center", color="white", fontsize=9)
            left += width
    ax.set_yticks(range(len(overall)), [f"{d['combination']}: {d['description']}" for d in overall], color=MUTED)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("% dos repositórios classificados", color=MUTED)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED)
    ax.legend(ncol=4, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=9)
    ax.set_title("RQ 07: classificação DORA geral em cada combinação", color=INK, fontsize=11, loc="left", pad=24)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _landis(kappa: float | None) -> str:
    if kappa is None:
        return "–"
    # Landis & Koch (1977)
    if kappa < 0:
        return "pobre"
    for limit, label in ((0.20, "leve"), (0.40, "razoável"), (0.60, "moderada"), (0.80, "substancial")):
        if kappa <= limit:
            return label
    return "quase perfeita"


def to_markdown(pairs: list[dict], dist: list[dict], trans: list[dict], n_repos: int) -> str:
    lines = [
        "# Resultados: RQ 07",
        "",
        f"Gerado por `python -m analysis.sensibilidade` a partir de `repositories_metrics.csv` ({n_repos} repositórios).",
        "",
        "## Classificação geral em cada combinação",
        "",
        "| Combinação | Definições | n | Elite | High | Medium | Low |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for d in dist:
        if d["metric"] != "overall":
            continue
        cells = " | ".join(f"{d[c]} ({_fmt(d[c + '_pct'], 1)}%)" for c in ("elite", "high", "medium", "low"))
        lines.append(f"| {d['combination']} | {d['description']} | {d['n']} | {cells} |")
    lines += [
        "",
        "## Concordância entre combinações",
        "",
        "| Par | Métrica | n | Mudaram de categoria | Melhoram / pioram na 2ª | Kappa linear | Concordância |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for p in pairs:
        lines.append(
            f"| {p['pair']} | {p['label']} | {p['n']} | {p['changed']} ({_fmt(p['changed_pct'], 1)}%) | "
            f"{p['better_in_second']} / {p['worse_in_second']} | {_fmt(p['kappa_linear'], 3)} | {_landis(p['kappa_linear'])} |"
        )
    lines += ["", "## Matrizes de transição (classificação geral)", ""]
    for pair in dict.fromkeys(t["pair"] for t in trans):
        x, y = pair.split(" × ")
        lines += [f"**{pair}** (linhas: {x}; colunas: {y})", "", "| | Elite | High | Medium | Low |", "|---|---:|---:|---:|---:|"]
        for t in trans:
            if t["pair"] == pair:
                lines.append(f"| {t['from']} | {t['Elite']} | {t['High']} | {t['Medium']} | {t['Low']} |")
        lines.append("")
    lines += ["![Distribuição](distribuicao.png)"]
    return "\n".join(lines) + "\n"


def run(input_path: Path, output_dir: Path, with_plot: bool = True) -> dict:
    rows = load_rows(input_path)
    table = classes(rows)
    pairs, dist, trans = compare(table), distribution(table), transitions(table)
    write_csv(output_dir / "classes.csv", table)
    write_csv(output_dir / "pares.csv", pairs)
    write_csv(output_dir / "distribuicao.csv", dist)
    write_csv(output_dir / "transicoes.csv", trans)
    if with_plot:
        plot(dist, output_dir / "distribuicao.png")
    (output_dir / "rq07.md").write_text(to_markdown(pairs, dist, trans, len(rows)), encoding="utf-8")
    return {"repositories": len(rows), "pairs": pairs, "distribution": dist, "transitions": trans}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="RQ 07: análise de sensibilidade")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = run(args.input, args.output)
    print(f"{result['repositories']} repositórios -> {args.output}")


if __name__ == "__main__":
    main()
