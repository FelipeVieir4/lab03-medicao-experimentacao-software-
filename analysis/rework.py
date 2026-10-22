"""RQ 08 (bônus): rework rate e comparação com o CFR (b).

Uso: python -m analysis.rework [--input CSV] [--output PASTA]

Rework rate = releases corretivas / releases estáveis na janela (coluna rework_rate,
mesma heurística de release corretiva do CFR b). Lê apenas
data/processed/repositories_metrics.csv e gera em reports/resultados/rq08/:
  - rework.csv   mediana e IQR do rework rate e do CFR (b), e Spearman entre os dois
  - rework.png   distribuições lado a lado e dispersão rework × CFR (b) (requer matplotlib)
  - rq08.md      tabela formatada para o artigo
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

from analysis.correlacoes import _p, paired, spearmanr, strength
from analysis.descritivas import _fmt, load_rows, to_float
from pipeline.dataset import median_or_none, quartiles, write_csv

DEFAULT_INPUT = Path("data/processed/repositories_metrics.csv")
DEFAULT_OUTPUT = Path("reports/resultados/rq08")

METRICS = [
    ("rework_rate", "Rework rate", "releases corretivas / releases"),
    ("cfr_delivery", "CFR (b)", "releases seguidas de corretiva em ≤ 7 dias / releases avaliadas"),
]
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
SERIES = ["#2a78d6", "#eb6834"]


def describe(rows: list[dict]) -> list[dict]:
    result = []
    for column, label, definition in METRICS:
        values = [v for v in (to_float(r.get(column)) for r in rows) if v is not None]
        q1, q3 = quartiles(values)
        result.append({"metric": column, "label": label, "definition": definition, "n": len(values),
                       "median": median_or_none(values), "q1": q1, "q3": q3,
                       "iqr": (q3 - q1) if q1 is not None else None,
                       "zero_pct": 100 * sum(v == 0 for v in values) / len(values) if values else None})
    return result


def compare(rows: list[dict]) -> dict:
    """Spearman entre rework e CFR (b) e quanto um supera o outro, por repositório."""
    xs, ys = paired(rows, "rework_rate", "cfr_delivery")
    rho, p = spearmanr(xs, ys)
    diffs = [x - y for x, y in zip(xs, ys)]
    return {"n": len(xs), "rho": rho, "p_value": p,
            "rework_greater_pct": 100 * sum(d > 0 for d in diffs) / len(diffs),
            "equal_pct": 100 * sum(d == 0 for d in diffs) / len(diffs),
            "median_difference": median_or_none(diffs)}


def plot(rows: list[dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rng = random.Random(42)
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.4), gridspec_kw={"width_ratios": [1, 1.1]})
    data = [[v for v in (to_float(r.get(c)) for r in rows) if v is not None] for c, _, _ in METRICS]
    positions = [2, 1]
    for values, pos, color in zip(data, positions, SERIES):
        left.scatter(values, [pos + rng.uniform(-0.18, 0.18) for _ in values], s=8, color=color,
                     alpha=0.35, edgecolors="none", zorder=2)
    left.boxplot(data, positions=positions, orientation="horizontal", widths=0.55, whis=(5, 95),
                 showfliers=False, zorder=3, patch_artist=True,
                 medianprops={"color": INK, "linewidth": 2},
                 boxprops={"facecolor": "none", "edgecolor": INK, "linewidth": 1},
                 whiskerprops={"color": INK, "linewidth": 1}, capprops={"color": INK, "linewidth": 1})
    left.set_yticks(positions, [label for _, label, _ in METRICS])
    left.set_xlim(-0.02, 1.02)
    left.set_title("Distribuição (proporção)", color=INK, fontsize=10.5, loc="left")

    xs, ys = paired(rows, "rework_rate", "cfr_delivery")
    right.plot([0, 1], [0, 1], color=MUTED, linestyle=(0, (3, 3)), linewidth=0.9, zorder=1)
    right.scatter(xs, ys, s=18, color=SERIES[0], alpha=0.5, edgecolors="white", linewidths=0.5, zorder=2)
    right.set_xlim(-0.02, 1.02)
    right.set_ylim(-0.02, 1.02)
    right.set_xlabel("Rework rate", color=MUTED)
    right.set_ylabel("CFR (b)", color=MUTED)
    right.set_title("Rework × CFR (b) (tracejado: y = x)", color=INK, fontsize=10.5, loc="left")
    for ax in (left, right):
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRID)
        ax.tick_params(colors=MUTED)
    left.spines["left"].set_visible(False)
    fig.suptitle("RQ 08: rework rate e CFR (b)", color=INK, x=0.01, ha="left", fontsize=11)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def to_markdown(desc: list[dict], comp: dict, n_repos: int) -> str:
    lines = [
        "# Resultados: RQ 08 (bônus)",
        "",
        f"Gerado por `python -m analysis.rework` a partir de `repositories_metrics.csv` ({n_repos} repositórios).",
        "",
        "## Tabela: rework rate e CFR (b)",
        "",
        "| Métrica | Definição | n | Mediana | Q1 | Q3 | IQR | Repos. com 0 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for d in desc:
        lines.append(
            f"| {d['label']} | {d['definition']} | {d['n']} | {_fmt(d['median'], 3)} | {_fmt(d['q1'], 3)} | "
            f"{_fmt(d['q3'], 3)} | {_fmt(d['iqr'], 3)} | {_fmt(d['zero_pct'], 1)}% |"
        )
    lines += [
        "",
        f"Spearman rework × CFR (b): ρ = {_fmt(comp['rho'], 3)} (p {_p(comp['p_value'], '= ')}, n = {comp['n']}), "
        f"{strength(comp['rho'])}. O rework rate supera o CFR (b) em {_fmt(comp['rework_greater_pct'], 1)}% dos "
        f"repositórios e empata em {_fmt(comp['equal_pct'], 1)}%; diferença mediana (rework − CFR b) = "
        f"{_fmt(comp['median_difference'], 3)}.",
        "",
        "![Rework rate](rework.png)",
    ]
    return "\n".join(lines) + "\n"


def run(input_path: Path, output_dir: Path) -> dict:
    rows = load_rows(input_path)
    desc, comp = describe(rows), compare(rows)
    write_csv(output_dir / "rework.csv", [{**d, **{f"spearman_{k}": v for k, v in comp.items()}} for d in desc])
    try:
        plot(rows, output_dir / "rework.png")
    except ImportError:
        print("matplotlib não instalado: rework.png não gerado (pip install -e \".[analysis]\")")
    (output_dir / "rq08.md").write_text(to_markdown(desc, comp, len(rows)), encoding="utf-8")
    return {"repositories": len(rows), "descritivas": desc, "comparacao": comp}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="RQ 08 (bônus): rework rate")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    run(args.input, args.output)
    print((args.output / "rq08.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
