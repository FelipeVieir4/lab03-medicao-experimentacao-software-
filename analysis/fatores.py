"""RQ 06: características dos repositórios associadas ao desempenho DORA.

Uso: python -m analysis.fatores [--input CSV] [--consenso CSV] [--output PASTA]

Lê apenas data/processed/repositories_metrics.csv (não usa a API). Para cada fator
× métrica da combinação C1, aplica Kruskal-Wallis (ou Mann-Whitney, se o fator tiver
só dois grupos), corrige os p-valores por Holm e calcula o tamanho de efeito
(ε² = H / (n − 1) e Cliff's delta). Quando o teste principal é significativo depois
da correção, compara os grupos dois a dois (Mann-Whitney + Holm dentro da família,
com Cliff's delta). Gera em reports/resultados/rq06/:
  - testes.csv    um teste por fator × métrica (H ou U, p, p corrigido, efeito)
  - posthoc.csv   comparações par a par dos testes significativos
  - medianas.csv  n e mediana de cada grupo
  - efeitos.png   mapa de ε² por fator × métrica (requer matplotlib)
  - rq06.md       tabelas formatadas para o artigo

O tipo do projeto (rotulado na amostra-ouro) só entra se data/gold/consenso.csv
existir; ele cobre apenas os 60 repositórios da amostra-ouro.

Os testes são implementados com a biblioteca padrão, pelo mesmo motivo do Spearman
da RQ 05 (scipy bloqueado em uma das máquinas). Os resultados foram conferidos com
scipy.stats.kruskal, scipy.stats.mannwhitneyu e statsmodels multipletests(method='holm').
"""
from __future__ import annotations

import argparse
import csv
import math
from itertools import combinations
from pathlib import Path

from analysis.correlacoes import ranks
from analysis.descritivas import _fmt, load_rows, to_float
from pipeline.dataset import median_or_none, quartiles, write_csv

DEFAULT_INPUT = Path("data/processed/repositories_metrics.csv")
DEFAULT_CONSENSUS = Path("data/gold/consenso.csv")
DEFAULT_OUTPUT = Path("reports/resultados/rq06")
ALPHA = 0.05

# Métricas da combinação de referência C1: (coluna, rótulo, "maior é melhor"?)
METRICS = [
    ("deployment_frequency", "Deployment frequency", True),
    ("lead_time_release_days", "Lead time (a)", False),
    ("cfr_ci", "CFR (a)", False),
    ("recovery_hours", "Tempo de recuperação", False),
]

# Linguagens com menos repositórios que isso vão para "Outras"
MIN_LANGUAGE = 30
QUARTILE_LABELS = ["Q1", "Q2", "Q3", "Q4"]
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


# ---------------------------------------------------------------- fatores

def quartile_groups(rows: list[dict], column: str) -> dict[str, str]:
    """Repositório -> Q1..Q4 pelos quartis da coluna (Q1 = 25% menores)."""
    values = [to_float(r.get(column)) for r in rows]
    q1, q3 = quartiles(values)
    q2 = median_or_none(values)
    groups = {}
    for r, v in zip(rows, values):
        if v is None:
            continue
        groups[r["repo"]] = "Q1" if v <= q1 else "Q2" if v <= q2 else "Q3" if v <= q3 else "Q4"
    return groups


def language_groups(rows: list[dict], minimum: int = MIN_LANGUAGE) -> dict[str, str]:
    """Linguagem principal; as que têm menos de `minimum` repositórios viram "Outras"."""
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.get("language") or ""] = counts.get(r.get("language") or "", 0) + 1
    return {
        r["repo"]: (r.get("language") if r.get("language") and counts[r["language"]] >= minimum else "Outras")
        for r in rows
    }


def project_type_groups(path: Path) -> dict[str, str]:
    """Tipo do projeto do consenso da amostra-ouro (vazio se ainda não houver consenso)."""
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as file:
        return {r["repo"]: r["tipo_projeto"] for r in csv.DictReader(file) if r.get("tipo_projeto")}


def factors(rows: list[dict], consensus_path: Path | None = None) -> list[tuple[str, str, dict, list[str] | None]]:
    """(chave, rótulo, repo -> grupo, ordem dos grupos)."""
    result = [
        ("linguagem", "Linguagem principal", language_groups(rows), None),
        ("estrelas", "Estrelas (quartis)", quartile_groups(rows, "stars"), QUARTILE_LABELS),
        ("contribuidores", "Contribuidores (quartis)", quartile_groups(rows, "contributors"), QUARTILE_LABELS),
        ("idade", "Idade (quartis)", quartile_groups(rows, "age_years"), QUARTILE_LABELS),
    ]
    types = project_type_groups(consensus_path) if consensus_path else {}
    if types:
        result.append(("tipo", "Tipo do projeto (amostra-ouro)", types, None))
    return result


# ---------------------------------------------------------------- testes

def _gammaincc(a: float, x: float) -> float:
    """Gama incompleta superior regularizada Q(a, x) (Numerical Recipes, gammq)."""
    if x <= 0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1:  # série para P(a, x)
        ap, total = a, 1.0 / a
        delta = total
        for _ in range(1000):
            ap += 1
            delta *= x / ap
            total += delta
            if abs(delta) < abs(total) * 1e-15:
                break
        return 1.0 - total * math.exp(-x + a * math.log(x) - gln)
    tiny = 1e-300  # fração contínua para Q(a, x)
    b = x + 1 - a
    c, d = 1 / tiny, 1 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1 / (d if abs(d) > tiny else tiny)
        c = b + an / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        if abs(d * c - 1) < 1e-15:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def chi2_sf(x: float, df: int) -> float:
    return _gammaincc(df / 2, x / 2)


def norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def _tie_term(values: list[float]) -> float:
    """Σ (t³ − t) sobre os grupos de valores empatados."""
    counts: dict[float, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return sum(t ** 3 - t for t in counts.values())


def kruskal(groups: list[list[float]]) -> tuple[float, float]:
    """H de Kruskal-Wallis com correção de empates e p-valor (qui-quadrado, k − 1 g.l.).

    Mesmo método do scipy.stats.kruskal.
    """
    values = [v for g in groups for v in g]
    n = len(values)
    r = ranks(values)
    h, start = 0.0, 0
    for g in groups:
        h += sum(r[start:start + len(g)]) ** 2 / len(g)
        start += len(g)
    h = 12 / (n * (n + 1)) * h - 3 * (n + 1)
    correction = 1 - _tie_term(values) / (n ** 3 - n)
    h = h / correction if correction > 0 else 0.0
    return h, chi2_sf(h, len(groups) - 1)


def mannwhitney(x: list[float], y: list[float]) -> tuple[float, float]:
    """U₁ de Mann-Whitney (de x) e p-valor bilateral pela aproximação normal.

    Com correção de empates e de continuidade: o mesmo que
    scipy.stats.mannwhitneyu(x, y, method='asymptotic'). É o método que o scipy
    usa por padrão quando há empates ou grupos com mais de 8 valores.
    """
    n1, n2 = len(x), len(y)
    n = n1 + n2
    r = ranks(list(x) + list(y))
    u1 = sum(r[:n1]) - n1 * (n1 + 1) / 2
    mu = n1 * n2 / 2
    sigma = math.sqrt(n1 * n2 / 12 * ((n + 1) - _tie_term(list(x) + list(y)) / (n * (n - 1))))
    if sigma == 0:
        return u1, 1.0
    u = max(u1, n1 * n2 - u1)
    z = (u - mu - 0.5) / sigma
    return u1, min(1.0, 2 * norm_sf(z))


def holm(p_values: list[float]) -> list[float]:
    """p-valores corrigidos por Holm (como multipletests(method='holm'))."""
    m = len(p_values)
    order = sorted(range(m), key=p_values.__getitem__)
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return adjusted


def epsilon_squared(h: float, n: int) -> float:
    """ε² = H / (n − 1), como no enunciado."""
    return h / (n - 1)


def cliffs_delta(u1: float, n1: int, n2: int) -> float:
    """δ = 2·U₁ / (n₁·n₂) − 1. Positivo: valores de x tendem a ser maiores que os de y."""
    return 2 * u1 / (n1 * n2) - 1


def epsilon_magnitude(e2: float) -> str:
    """Escala usual para ε² (Rea & Parker): < 0,01 desprezível; < 0,08 pequeno; < 0,26 médio."""
    return "desprezível" if e2 < 0.01 else "pequeno" if e2 < 0.08 else "médio" if e2 < 0.26 else "grande"


def delta_magnitude(delta: float) -> str:
    """Romano et al. (2006): |δ| < 0,147 desprezível; < 0,33 pequeno; < 0,474 médio."""
    d = abs(delta)
    return "desprezível" if d < 0.147 else "pequeno" if d < 0.33 else "médio" if d < 0.474 else "grande"


# ---------------------------------------------------------------- análise

def grouped(rows: list[dict], groups: dict[str, str], column: str, order: list[str] | None) -> dict[str, list[float]]:
    data: dict[str, list[float]] = {}
    for r in rows:
        g, v = groups.get(r["repo"]), to_float(r.get(column))
        if g is not None and v is not None:
            data.setdefault(g, []).append(v)
    names = [g for g in order if g in data] if order else sorted(data, key=lambda g: (g == "Outras", -len(data[g]), g))
    return {g: data[g] for g in names}


def analyse(rows: list[dict], consensus_path: Path | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    tests, medians, families = [], [], []
    for fkey, flabel, groups, order in factors(rows, consensus_path):
        for column, mlabel, higher_better in METRICS:
            data = grouped(rows, groups, column, order)
            data = {g: v for g, v in data.items() if len(v) >= 2}
            names = list(data)
            n = sum(len(v) for v in data.values())
            for g in names:
                medians.append({"factor": fkey, "metric": column, "group": g, "n": len(data[g]),
                                "median": median_or_none(data[g])})
            if len(names) < 2:
                continue
            row = {"factor": fkey, "factor_label": flabel, "metric": column, "metric_label": mlabel,
                   "groups": len(names), "n": n}
            if len(names) == 2:
                x, y = data[names[0]], data[names[1]]
                u1, p = mannwhitney(x, y)
                delta = cliffs_delta(u1, len(x), len(y))
                row.update(test="Mann-Whitney", statistic=u1, p_value=p, effect="delta", effect_value=delta,
                           magnitude=delta_magnitude(delta), comparison=f"{names[0]} × {names[1]}")
            else:
                h, p = kruskal(list(data.values()))
                e2 = epsilon_squared(h, n)
                row.update(test="Kruskal-Wallis", statistic=h, p_value=p, effect="epsilon2", effect_value=e2,
                           magnitude=epsilon_magnitude(e2), comparison="")
                # Cliff's delta entre os extremos (Q4 × Q1) dá a direção nos fatores em quartis
                if order == QUARTILE_LABELS and "Q1" in data and "Q4" in data:
                    u1, _ = mannwhitney(data["Q4"], data["Q1"])
                    row["delta_q4_q1"] = cliffs_delta(u1, len(data["Q4"]), len(data["Q1"]))
            tests.append(row)
            families.append((row, data, higher_better))
    for row, p_adj in zip(tests, holm([t["p_value"] for t in tests])):
        row["p_holm"] = p_adj
        row["significant"] = p_adj < ALPHA
    posthoc = []
    for row, data, higher_better in families:
        if not row["significant"] or row["test"] != "Kruskal-Wallis":
            continue
        pairs = []
        for a, b in combinations(list(data), 2):
            u1, p = mannwhitney(data[a], data[b])
            delta = cliffs_delta(u1, len(data[a]), len(data[b]))
            pairs.append({"factor": row["factor"], "metric": row["metric"], "group_a": a, "group_b": b,
                          "n_a": len(data[a]), "n_b": len(data[b]),
                          "median_a": median_or_none(data[a]), "median_b": median_or_none(data[b]),
                          "u1": u1, "p_value": p, "delta": delta, "magnitude": delta_magnitude(delta)})
        for pair, p_adj in zip(pairs, holm([p["p_value"] for p in pairs])):
            pair["p_holm"] = p_adj
            pair["significant"] = p_adj < ALPHA
        posthoc.extend(pairs)
    return tests, posthoc, medians


# ---------------------------------------------------------------- saídas

def _p(value: float) -> str:
    return "< 0,001" if value < 0.001 else _fmt(value, 3)


def _median(value: float | None, column: str) -> str:
    if value is None:
        return "–"
    if column == "cfr_ci":
        return _fmt(100 * value, 1) + "%"
    return _fmt(value, 2)


def plot(tests: list[dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fkeys = list(dict.fromkeys(t["factor"] for t in tests))
    flabels = {t["factor"]: t["factor_label"] for t in tests}
    mkeys = [m for m, _, _ in METRICS]
    grid = [[next((t for t in tests if t["factor"] == f and t["metric"] == m), None) for m in mkeys] for f in fkeys]
    values = [[(t["effect_value"] if t and t["effect"] == "epsilon2" else 0.0) for t in line] for line in grid]
    fig, ax = plt.subplots(figsize=(7.4, 0.75 * len(fkeys) + 2.0))
    image = ax.imshow(values, cmap="Blues", vmin=0, vmax=max(0.1, max(max(v) for v in values)))
    for i, line in enumerate(grid):
        for j, t in enumerate(line):
            if t is None:
                continue
            mark = "*" if t["significant"] else ""
            color = "white" if values[i][j] > 0.6 * image.get_clim()[1] else INK
            ax.text(j, i, f"{_fmt(t['effect_value'], 3)}{mark}", ha="center", va="center", color=color, fontsize=10)
    short = {"deployment_frequency": "Deployment\nfrequency", "lead_time_release_days": "Lead time (a)",
             "cfr_ci": "CFR (a)", "recovery_hours": "Tempo de\nrecuperação"}
    ax.set_xticks(range(len(mkeys)), [short[m] for m in mkeys], color=MUTED)
    ax.set_yticks(range(len(fkeys)), [flabels[f] for f in fkeys], color=MUTED)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_title("RQ 06: tamanho de efeito ε² (Kruskal-Wallis)\n* = significativo (p < 0,05 após Holm)",
                 color=INK, fontsize=11, loc="left")
    fig.colorbar(image, ax=ax, fraction=0.03, pad=0.02)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def to_markdown(tests: list[dict], posthoc: list[dict], medians: list[dict], n_repos: int) -> str:
    lines = [
        "# Resultados: RQ 06",
        "",
        f"Gerado por `python -m analysis.fatores` a partir de `repositories_metrics.csv` ({n_repos} repositórios). "
        f"{len(tests)} testes; p-valores corrigidos por Holm; α = 0,05.",
        "",
        "## Testes por fator × métrica",
        "",
        "| Fator | Métrica | Teste | n | Estatística | p | p (Holm) | Efeito | δ (Q4 × Q1) |",
        "|---|---|---|---:|---:|---:|---:|---|---:|",
    ]
    for t in tests:
        name = "ε²" if t["effect"] == "epsilon2" else "δ"
        stat = ("H = " if t["test"] == "Kruskal-Wallis" else "U = ") + _fmt(t["statistic"], 2)
        bold = "**" if t["significant"] else ""
        delta = t.get("delta_q4_q1")
        lines.append(
            f"| {t['factor_label']} | {t['metric_label']} | {t['test']} | {t['n']} | {stat} | {_p(t['p_value'])} | "
            f"{bold}{_p(t['p_holm'])}{bold} | {name} = {_fmt(t['effect_value'], 3)} ({t['magnitude']}) | "
            f"{_fmt(delta, 3) if delta is not None else '–'} |"
        )
    lines += ["", "## Medianas por grupo", ""]
    for fkey in dict.fromkeys(t["factor"] for t in tests):
        label = next(t["factor_label"] for t in tests if t["factor"] == fkey)
        groups = list(dict.fromkeys(m["group"] for m in medians if m["factor"] == fkey))
        lines += [f"**{label}**", "", "| Métrica | " + " | ".join(groups) + " |",
                  "|---|" + "---:|" * len(groups)]
        n_line = {m["group"]: m["n"] for m in medians if m["factor"] == fkey and m["metric"] == "deployment_frequency"}
        lines.append("| n | " + " | ".join(str(n_line.get(g, "–")) for g in groups) + " |")
        for column, mlabel, _ in METRICS:
            values = {m["group"]: m["median"] for m in medians if m["factor"] == fkey and m["metric"] == column}
            lines.append(f"| {mlabel} | " + " | ".join(_median(values.get(g), column) for g in groups) + " |")
        lines.append("")
    if posthoc:
        lines += ["## Comparações par a par (só nos testes significativos)", "",
                  "| Fator | Métrica | Grupos | Medianas | p (Holm) | δ |", "|---|---|---|---|---:|---|"]
        mlabels = {m: label for m, label, _ in METRICS}
        for p in posthoc:
            if not p["significant"]:
                continue
            lines.append(
                f"| {p['factor']} | {mlabels[p['metric']]} | {p['group_a']} × {p['group_b']} | "
                f"{_median(p['median_a'], p['metric'])} × {_median(p['median_b'], p['metric'])} | "
                f"{_p(p['p_holm'])} | {_fmt(p['delta'], 3)} ({p['magnitude']}) |"
            )
        lines.append("")
    lines += ["![Tamanho de efeito](efeitos.png)"]
    return "\n".join(lines) + "\n"


def run(input_path: Path, output_dir: Path, consensus_path: Path | None = DEFAULT_CONSENSUS, with_plot: bool = True) -> dict:
    rows = load_rows(input_path)
    tests, posthoc, medians = analyse(rows, consensus_path)
    write_csv(output_dir / "testes.csv", tests)
    write_csv(output_dir / "posthoc.csv", posthoc)
    write_csv(output_dir / "medianas.csv", medians)
    if with_plot:
        plot(tests, output_dir / "efeitos.png")
    (output_dir / "rq06.md").write_text(to_markdown(tests, posthoc, medians, len(rows)), encoding="utf-8")
    return {"repositories": len(rows), "tests": tests, "posthoc": posthoc, "medians": medians}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="RQ 06: fatores × métricas DORA")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--consenso", type=Path, default=DEFAULT_CONSENSUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = run(args.input, args.output, args.consenso)
    significant = sum(t["significant"] for t in result["tests"])
    print(f"{result['repositories']} repositórios, {len(result['tests'])} testes, {significant} significativos -> {args.output}")


if __name__ == "__main__":
    main()
