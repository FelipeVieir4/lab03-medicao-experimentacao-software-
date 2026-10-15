"""Estatística descritiva das RQs 01 a 04 e classificação DORA de referência (C1).

Uso: python -m analysis.descritivas [--input CSV] [--output PASTA]

Lê apenas data/processed/repositories_metrics.csv (não usa a API) e gera em
reports/resultados/rq01_04/:
  - descritivas.csv       mediana, Q1, Q3 e IQR de cada métrica
  - classificacao_c1.csv  contagem e % de Elite/High/Medium/Low por métrica e geral
  - censura.csv           proporção de episódios (RQ 04) e releases (CFR b) censurados
  - distribuicoes.png     boxplots das métricas com os cortes DORA (requer matplotlib)
  - rq01_04.md            as três tabelas formatadas para o artigo
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from pipeline.dataset import median_or_none, quartiles, write_csv

DEFAULT_INPUT = Path("data/processed/repositories_metrics.csv")
DEFAULT_OUTPUT = Path("reports/resultados/rq01_04")

# (coluna, RQ, descrição, unidade)
METRICS = [
    ("deployment_frequency", "RQ 01", "Deployment frequency", "releases/semana"),
    ("lead_time_release_days", "RQ 02", "Lead time (a): por release", "dias"),
    ("lead_time_commit_days", "RQ 02", "Lead time (b): por commit", "dias"),
    ("cfr_ci", "RQ 03", "CFR (a): falha de pipeline", "proporção"),
    ("cfr_delivery", "RQ 03", "CFR (b): falha de entrega", "proporção"),
    ("recovery_hours", "RQ 04", "Tempo de recuperação", "horas"),
]

# (coluna, descrição) da combinação de referência C1
CLASS_COLUMNS = [
    ("class_c1_deployment_frequency", "Deployment frequency"),
    ("class_c1_lead_time_days", "Lead time (a)"),
    ("class_c1_change_failure_rate", "CFR (a)"),
    ("class_c1_recovery_hours", "Tempo de recuperação"),
    ("class_c1_overall", "Geral"),
]
CATEGORIES = ["Elite", "High", "Medium", "Low"]

# Painéis dos boxplots: (título, escala log, cortes DORA, [(coluna, rótulo)])
PANELS = [
    ("RQ 01: deployment frequency (releases/semana)", True, [1 / 4.345, 1, 7],
     [("deployment_frequency", "Releases")]),
    ("RQ 02: lead time (dias)", True, [1, 7, 30],
     [("lead_time_release_days", "(a) por release"), ("lead_time_commit_days", "(b) por commit")]),
    ("RQ 03: change failure rate (proporção)", False, [0.15, 0.30, 0.45],
     [("cfr_ci", "(a) pipeline"), ("cfr_delivery", "(b) entrega")]),
    ("RQ 04: tempo de recuperação (horas)", True, [1, 24, 168],
     [("recovery_hours", "Recuperação")]),
]
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
SERIES = ["#2a78d6", "#eb6834"]


def to_float(value: str | None) -> float | None:
    return float(value) if value not in (None, "") else None


def to_int(value: str | None) -> int:
    return int(float(value)) if value not in (None, "") else 0


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def describe(rows: list[dict]) -> list[dict]:
    """Mediana e IQR (Q1, Q3) de cada métrica das RQs 01 a 04."""
    result = []
    for column, rq, label, unit in METRICS:
        values = [v for v in (to_float(r.get(column)) for r in rows) if v is not None]
        q1, q3 = quartiles(values)
        result.append(
            {
                "rq": rq,
                "metric": column,
                "label": label,
                "unit": unit,
                "n": len(values),
                "missing": len(rows) - len(values),
                "median": median_or_none(values),
                "q1": q1,
                "q3": q3,
                "iqr": (q3 - q1) if q1 is not None else None,
            }
        )
    return result


def classification(rows: list[dict]) -> list[dict]:
    """Distribuição das categorias DORA na combinação C1; % sobre os repositórios classificados."""
    result = []
    for column, label in CLASS_COLUMNS:
        counts = {c: 0 for c in CATEGORIES}
        missing = 0
        for r in rows:
            value = r.get(column) or None
            if value in counts:
                counts[value] += 1
            else:
                missing += 1
        n = sum(counts.values())
        row = {"metric": column, "label": label, "n": n, "missing": missing}
        for c in CATEGORIES:
            row[c.lower()] = counts[c]
            row[f"{c.lower()}_pct"] = 100 * counts[c] / n if n else None
        result.append(row)
    return result


def censoring(rows: list[dict]) -> list[dict]:
    """Proporção de episódios de recuperação (RQ 04) e de releases do CFR (b) censurados."""
    specs = [
        ("recovery_episodes", "Episódios de recuperação (RQ 04)", "n_recovery_episodes", "n_recovery_censored"),
        ("releases_cfr_b", "Releases do CFR (b) (RQ 03)", "n_releases_cfr_evaluated", "n_releases_cfr_censored"),
    ]
    result = []
    for item, label, closed_col, censored_col in specs:
        closed = sum(to_int(r.get(closed_col)) for r in rows)
        censored = sum(to_int(r.get(censored_col)) for r in rows)
        total = closed + censored
        ratios = []
        for r in rows:
            c, k = to_int(r.get(closed_col)), to_int(r.get(censored_col))
            if c + k:
                ratios.append(k / (c + k))
        result.append(
            {
                "item": item,
                "label": label,
                "total": total,
                "censored": censored,
                "censored_pct": 100 * censored / total if total else None,
                "repos_with_items": len(ratios),
                "repos_with_censored": sum(x > 0 for x in ratios),
                "median_repo_censored_pct": 100 * median_or_none(ratios) if ratios else None,
            }
        )
    return result


def plot(rows: list[dict], path: Path) -> None:
    """Boxplots horizontais (bigodes = P5 e P95); linhas tracejadas = cortes Elite/High/Medium/Low."""
    import random

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rng = random.Random(42)  # jitter reproduzível dos pontos
    fig, axes = plt.subplots(2, 2, figsize=(11, 6.2))
    for ax, (title, log, cuts, series) in zip(axes.flat, PANELS):
        data = [[v for v in (to_float(r.get(c)) for r in rows) if v is not None and (v > 0 or not log)]
                for c, _ in series]
        positions = list(range(len(series), 0, -1))
        for cut in cuts:
            ax.axvline(cut, color=MUTED, linestyle=(0, (3, 3)), linewidth=0.9, zorder=1)
        for values, pos, color in zip(data, positions, SERIES):
            ax.scatter(values, [pos + rng.uniform(-0.18, 0.18) for _ in values], s=8, color=color,
                       alpha=0.35, edgecolors="none", zorder=2)
        ax.boxplot(data, positions=positions, orientation="horizontal", widths=0.55, whis=(5, 95), showfliers=False, zorder=3,
                   medianprops={"color": INK, "linewidth": 2},
                   boxprops={"facecolor": "none", "edgecolor": INK, "linewidth": 1},
                   whiskerprops={"color": INK, "linewidth": 1}, capprops={"color": INK, "linewidth": 1},
                   patch_artist=True)
        ax.set_yticks(positions, [label for _, label in series])
        if log:
            ax.set_xscale("log")
        ax.set_title(title, color=INK, fontsize=10.5, loc="left")
        ax.grid(True, axis="x", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=MUTED, length=0)
    fig.suptitle("Distribuição das métricas DORA (linhas tracejadas: cortes Elite | High | Medium | Low)",
                 color=INK, x=0.01, ha="left", fontsize=11)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _fmt(value, digits: int = 2) -> str:
    if value is None:
        return "–"
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}".replace(".", ",")


def to_markdown(desc: list[dict], classes: list[dict], cens: list[dict], n_repos: int) -> str:
    lines = [
        "# Resultados descritivos: RQs 01 a 04",
        "",
        f"Gerado por `python -m analysis.descritivas` a partir de `repositories_metrics.csv` ({n_repos} repositórios).",
        "",
        "## Tabela 1: mediana e IQR das métricas",
        "",
        "| RQ | Métrica | Unidade | n | Mediana | Q1 | Q3 | IQR |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for d in desc:
        digits = 3 if d["unit"] == "proporção" else 2
        lines.append(
            f"| {d['rq']} | {d['label']} | {d['unit']} | {d['n']} | {_fmt(d['median'], digits)} | "
            f"{_fmt(d['q1'], digits)} | {_fmt(d['q3'], digits)} | {_fmt(d['iqr'], digits)} |"
        )
    lines += [
        "",
        "## Tabela 2: classificação DORA na combinação de referência C1",
        "",
        "C1 = release estável, lead time (a), CFR (a) e tempo de recuperação. "
        "Percentuais sobre os repositórios classificados (n); repositórios sem a métrica ficam fora.",
        "",
        "| Métrica | n | Elite | High | Medium | Low | Sem dado |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for c in classes:
        cells = " | ".join(
            f"{c[k.lower()]} ({_fmt(c[f'{k.lower()}_pct'], 1)}%)" for k in CATEGORIES
        )
        lines.append(f"| {c['label']} | {c['n']} | {cells} | {c['missing']} |")
    lines += [
        "",
        "## Tabela 3: censura",
        "",
        "| Item | Total | Censurados | % censurados | Repos. com censura | Mediana por repo. (%) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for c in cens:
        lines.append(
            f"| {c['label']} | {c['total']} | {c['censored']} | {_fmt(c['censored_pct'])} | "
            f"{c['repos_with_censored']} de {c['repos_with_items']} | {_fmt(c['median_repo_censored_pct'])} |"
        )
    return "\n".join(lines) + "\n"


def run(input_path: Path, output_dir: Path) -> dict:
    rows = load_rows(input_path)
    desc, classes, cens = describe(rows), classification(rows), censoring(rows)
    write_csv(output_dir / "descritivas.csv", desc)
    write_csv(output_dir / "classificacao_c1.csv", classes)
    write_csv(output_dir / "censura.csv", cens)
    try:
        plot(rows, output_dir / "distribuicoes.png")
    except ImportError:
        print("matplotlib não instalado: distribuicoes.png não gerado (pip install -e \".[analysis]\")")
    (output_dir / "rq01_04.md").write_text(to_markdown(desc, classes, cens, len(rows)), encoding="utf-8")
    return {"repositories": len(rows), "descritivas": desc, "classificacao": classes, "censura": cens}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Estatística descritiva das RQs 01 a 04")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = run(args.input, args.output)
    print(f"{result['repositories']} repositórios -> {args.output}")
    print((args.output / "rq01_04.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
