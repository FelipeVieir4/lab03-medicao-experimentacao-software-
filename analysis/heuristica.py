"""Seção 6, passo 5: precisão, recall e F1 da heurística de release corretiva (CFR b).

Uso: python -m analysis.heuristica [--consenso CSV] [--releases CSV] [--output PASTA]

Compara cada versão da heurística (VERSIONS) com o rótulo de consenso da amostra-ouro
(data/gold/consenso.csv, gerado por analysis.concordancia) e gera em
reports/resultados/validacao/:
  - heuristica.csv          matriz de confusão, precisão, recall e F1 de cada versão
  - heuristica_detalhe.csv  cada release avaliada com o consenso e a saída de cada versão
  - heuristica.md           tabela formatada para o artigo

As versões usam só as colunas patch_bump e has_fix_commit de releases.csv, sem a API.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Callable

from analysis.descritivas import _fmt
from pipeline.dataset import write_csv

DEFAULT_CONSENSUS = Path("data/gold/consenso.csv")
DEFAULT_RELEASES = Path("data/processed/releases.csv")
DEFAULT_OUTPUT = Path("reports/resultados/validacao")
F1_TARGET = 0.70


def to_bool(value: str | None) -> bool | None:
    return {"true": True, "false": False}.get((value or "").strip().lower())


def _v1(patch: bool | None, fix: bool) -> bool:
    return fix if patch is None else (patch and fix)


# nome -> (descrição, regra(patch_bump, has_fix_commit)); patch_bump é None fora do SemVer
VERSIONS: dict[str, tuple[str, Callable[[bool | None, bool], bool]]] = {
    "v1": ("só o PATCH muda E há commit fix/hotfix/revert (fora do SemVer: só o commit)", _v1),
    "v2": ("há commit fix/hotfix/revert", lambda patch, fix: fix),
    "v3": ("só o PATCH muda", lambda patch, fix: bool(patch)),
    "v4": ("só o PATCH muda OU há commit fix/hotfix/revert", lambda patch, fix: bool(patch) or fix),
}
CURRENT = "v1"  # versão usada em pipeline/dataset.py (is_corrective)


def precision_recall_f1(truth: list[bool], predicted: list[bool]) -> dict:
    """Como precision_recall_fscore_support(average='binary'), classe positiva = corretiva."""
    tp = sum(t and p for t, p in zip(truth, predicted))
    fp = sum(p and not t for t, p in zip(truth, predicted))
    fn = sum(t and not p for t, p in zip(truth, predicted))
    tn = len(truth) - tp - fp - fn
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else (0.0 if tp + fp + fn else None)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall, "f1": f1}


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def evaluate(consensus_rows: list[dict], release_rows: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """Retorna (métricas por versão, detalhe por release, contagens de exclusão)."""
    releases = {}
    for r in release_rows:
        releases.setdefault((r["repo"], r["tag_name"]), r)
    detail, skipped = [], {"sem_consenso": 0, "sem_release_anterior": 0, "fora_do_dataset": 0}
    for c in consensus_rows:
        label = c.get("release_corretiva") or None
        if label is None:
            skipped["sem_consenso"] += 1
            continue
        release = releases.get((c["repo"], c["tag_name"]))
        if release is None:
            skipped["fora_do_dataset"] += 1
            continue
        fix = to_bool(release.get("has_fix_commit"))
        if fix is None:  # sem release estável anterior: a heurística não se aplica
            skipped["sem_release_anterior"] += 1
            continue
        patch = to_bool(release.get("patch_bump"))
        row = {"repo": c["repo"], "tag_name": c["tag_name"], "consenso": label,
               "patch_bump": patch, "has_fix_commit": fix}
        for name, (_, rule) in VERSIONS.items():
            row[name] = rule(patch, fix)
        detail.append(row)
    truth = [d["consenso"] == "sim" for d in detail]
    metrics = []
    for name, (description, _) in VERSIONS.items():
        m = precision_recall_f1(truth, [d[name] for d in detail])
        metrics.append({"version": name, "description": description, "n": len(detail),
                        "positives": sum(truth), **m,
                        "meets_target": m["f1"] is not None and m["f1"] >= F1_TARGET})
    return metrics, detail, skipped


def to_markdown(metrics: list[dict], skipped: dict) -> str:
    n = metrics[0]["n"] if metrics else 0
    positives = metrics[0]["positives"] if metrics else 0
    lines = [
        "# Validação da heurística de release corretiva",
        "",
        f"Gerado por `python -m analysis.heuristica`. Releases avaliadas: {n} ({positives} corretivas no consenso). "
        f"Excluídas: {skipped['sem_consenso']} sem consenso, {skipped['sem_release_anterior']} sem release "
        f"anterior, {skipped['fora_do_dataset']} fora do dataset.",
        "",
        f"## Tabela: versões testadas (meta: F1 ≥ {_fmt(F1_TARGET)})",
        "",
        "| Versão | Regra | VP | FP | FN | VN | Precisão | Recall | F1 | Meta |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for m in metrics:
        name = f"**{m['version']}** (atual)" if m["version"] == CURRENT else m["version"]
        lines.append(
            f"| {name} | {m['description']} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} | "
            f"{_fmt(m['precision'], 3)} | {_fmt(m['recall'], 3)} | {_fmt(m['f1'], 3)} | "
            f"{'atinge' if m['meets_target'] else 'não atinge'} |"
        )
    return "\n".join(lines) + "\n"


def run(consensus_path: Path, releases_path: Path, output_dir: Path) -> dict:
    if not consensus_path.exists():
        raise SystemExit(f"{consensus_path} não existe: rode antes `python -m analysis.concordancia`")
    metrics, detail, skipped = evaluate(load_csv(consensus_path), load_csv(releases_path))
    if not detail:
        raise SystemExit("nenhuma release com rótulo de consenso: termine a rotulação e o desempate primeiro")
    write_csv(output_dir / "heuristica.csv", metrics)
    write_csv(output_dir / "heuristica_detalhe.csv", detail)
    (output_dir / "heuristica.md").write_text(to_markdown(metrics, skipped), encoding="utf-8")
    return {"metrics": metrics, "detail": detail, "skipped": skipped}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Precisão, recall e F1 da heurística de release corretiva")
    parser.add_argument("--consenso", type=Path, default=DEFAULT_CONSENSUS)
    parser.add_argument("--releases", type=Path, default=DEFAULT_RELEASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    run(args.consenso, args.releases, args.output)
    print((args.output / "heuristica.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
