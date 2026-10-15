"""RQ 05: correlação de Spearman entre deployment frequency e CFR (variantes a e b).

Uso: python -m analysis.correlacoes [--input CSV] [--output PASTA]

Lê apenas data/processed/repositories_metrics.csv (não usa a API) e gera em
reports/resultados/rq05/:
  - spearman.csv   ρ, p-valor e n de cada variante (e, à parte, CFR a × CFR b)
  - dispersao.png  gráficos de dispersão (eixo x em escala log)
  - rq05.md        tabela formatada para o artigo

O teste de Spearman é implementado aqui (biblioteca padrão); os gráficos usam
matplotlib (pip install -e ".[analysis]").
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from analysis.descritivas import _fmt, load_rows, to_float
from pipeline.dataset import write_csv

DEFAULT_INPUT = Path("data/processed/repositories_metrics.csv")
DEFAULT_OUTPUT = Path("reports/resultados/rq05")

X = ("deployment_frequency", "Deployment frequency (releases/semana)")
# (coluna, variante, rótulo do eixo y)
VARIANTS = [
    ("cfr_ci", "a", "CFR (a): falha de pipeline"),
    ("cfr_delivery", "b", "CFR (b): falha de entrega"),
]

INK, MUTED, GRID, SERIES = "#0b0b0b", "#52514e", "#e4e3df", "#2a78d6"


def paired(rows: list[dict], x: str, y: str) -> tuple[list[float], list[float]]:
    """Pares (x, y) dos repositórios que têm as duas métricas."""
    pairs = [(to_float(r.get(x)), to_float(r.get(y))) for r in rows]
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    return [a for a, _ in pairs], [b for _, b in pairs]


def ranks(values: list[float]) -> list[float]:
    """Postos 1..n, com empates recebendo a média dos postos."""
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            result[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return result


def _betacf(a: float, b: float, x: float) -> float:
    """Fração contínua da beta incompleta (Numerical Recipes, betacf)."""
    tiny = 1e-300
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1)
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        for aa in (m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)),
                   -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))):
            d = 1 + aa * d
            d = 1 / (d if abs(d) > tiny else tiny)
            c = 1 + aa / c
            c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1) < 1e-15:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Beta incompleta regularizada I_x(a, b)."""
    if x <= 0 or x >= 1:
        return 0.0 if x <= 0 else 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1 - front * _betacf(b, a, 1 - x) / b


def spearmanr(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """ρ de Spearman (Pearson dos postos) e p-valor bilateral pelo teste t com n − 2 g.l.

    Mesmo método do scipy.stats.spearmanr (padrão).
    """
    n = len(xs)
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    var = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    rho = cov / var
    df = n - 2
    if abs(rho) >= 1:
        return rho, 0.0
    t2 = rho * rho * df / (1 - rho * rho)
    return rho, betainc(df / 2, 0.5, df / (df + t2))


def spearman(rows: list[dict]) -> list[dict]:
    result = []
    for column, variant, label in VARIANTS:
        xs, ys = paired(rows, X[0], column)
        rho, p = spearmanr(xs, ys)
        result.append(
            {
                "variant": variant,
                "x": X[0],
                "y": column,
                "label": label,
                "n": len(xs),
                "rho": float(rho),
                "p_value": float(p),
            }
        )
    return result


def between_variants(rows: list[dict]) -> dict:
    """Spearman entre CFR (a) e CFR (b): as duas variantes medem a mesma coisa?"""
    xs, ys = paired(rows, "cfr_ci", "cfr_delivery")
    rho, p = spearmanr(xs, ys)
    return {"variant": "a_vs_b", "x": "cfr_ci", "y": "cfr_delivery", "label": "CFR (a) × CFR (b)",
            "n": len(xs), "rho": float(rho), "p_value": float(p)}


def plot(rows: list[dict], stats: list[dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(VARIANTS), figsize=(11, 4.4), sharex=True)
    for ax, (column, _, label), s in zip(axes, VARIANTS, stats):
        xs, ys = paired(rows, X[0], column)
        ax.scatter(xs, ys, s=22, color=SERIES, alpha=0.55, edgecolors="white", linewidths=0.6)
        ax.set_xscale("log")
        ax.set_ylim(-0.02, 1.02)
        ax.set_xlabel(X[1], color=MUTED)
        ax.set_ylabel(label, color=MUTED)
        ax.set_title(
            f"{label}\nρ = {_fmt(s['rho'], 3)}, p {_p(s['p_value'], '= ')}, n = {s['n']}",
            color=INK, fontsize=11, loc="left",
        )
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRID)
        ax.tick_params(colors=MUTED)
    fig.suptitle("RQ 05: velocidade × estabilidade (Spearman)", color=INK, x=0.01, ha="left")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _p(value: float, prefix: str = "") -> str:
    return "< 0,001" if value < 0.001 else prefix + _fmt(value, 3)


def strength(rho: float) -> str:
    """Intensidade pela escala usual para |ρ| (fraca < 0,3 ≤ moderada < 0,7 ≤ forte)."""
    size = abs(rho)
    label = "desprezível" if size < 0.1 else "fraca" if size < 0.3 else "moderada" if size < 0.7 else "forte"
    if label == "desprezível":
        return label
    return f"{label} {'positiva' if rho > 0 else 'negativa'}"


def to_markdown(stats: list[dict], n_repos: int, variants: dict | None = None) -> str:
    lines = [
        "# Resultados: RQ 05",
        "",
        f"Gerado por `python -m analysis.correlacoes` a partir de `repositories_metrics.csv` ({n_repos} repositórios).",
        "",
        "## Tabela 4: correlação de Spearman entre deployment frequency e CFR",
        "",
        "| Variante do CFR | n | ρ | p-valor | Intensidade (α = 0,05) |",
        "|---|---:|---:|---:|---|",
    ]
    for s in stats:
        significance = "significativa" if s["p_value"] < 0.05 else "não significativa"
        lines.append(
            f"| {s['label']} | {s['n']} | {_fmt(s['rho'], 3)} | {_p(s['p_value'])} | "
            f"{strength(s['rho'])}, {significance} |"
        )
    if variants:
        lines += [
            "",
            f"Complementar: entre as próprias variantes, {variants['label']} tem ρ = {_fmt(variants['rho'], 3)} "
            f"(p {_p(variants['p_value'], '= ')}, n = {variants['n']}).",
        ]
    lines += ["", "![Dispersão](dispersao.png)"]
    return "\n".join(lines) + "\n"


def run(input_path: Path, output_dir: Path) -> dict:
    rows = load_rows(input_path)
    stats, variants = spearman(rows), between_variants(rows)
    write_csv(output_dir / "spearman.csv", stats + [variants])
    plot(rows, stats, output_dir / "dispersao.png")
    (output_dir / "rq05.md").write_text(to_markdown(stats, len(rows), variants), encoding="utf-8")
    return {"repositories": len(rows), "spearman": stats, "cfr_a_vs_b": variants}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="RQ 05: correlação de Spearman")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = run(args.input, args.output)
    print(f"{result['repositories']} repositórios -> {args.output}")
    print((args.output / "rq05.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
