"""Seção 6, passo 5: precisão, recall e F1 da heurística de release corretiva (CFR b).

Uso: python -m analysis.heuristica [--consenso CSV] [--releases CSV | --raw PASTA] [--output PASTA]

Compara cada versão da heurística (VERSIONS) com o rótulo de consenso da amostra-ouro
(data/gold/consenso.csv, gerado por analysis.concordancia) e gera em
reports/resultados/validacao/:
  - heuristica.csv          matriz de confusão, precisão, recall e F1 de cada versão
  - heuristica_detalhe.csv  cada release avaliada com o consenso e a saída de cada versão
  - heuristica.md           tabela formatada para o artigo

As versões v1-v5 e v7 usam colunas de releases.csv. A v6 também usa as release notes
(colunas notes_fix_terms e notes_feature_terms): elas existem em releases.csv depois de
recalcular o dataset; antes disso, use --raw data/raw/repos para calculá-las a partir dos
JSONs brutos, com o mesmo código do pipeline (pipeline.dataset.analyse_repository).
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Callable

from analysis.descritivas import _fmt
from pipeline.dataset import analyse_repository, is_line_patch, write_csv

DEFAULT_CONSENSUS = Path("data/gold/consenso.csv")
DEFAULT_RELEASES = Path("data/processed/releases.csv")
DEFAULT_OUTPUT = Path("reports/resultados/validacao")
F1_TARGET = 0.70


def to_bool(value: str | None) -> bool | None:
    return {"true": True, "false": False}.get((value or "").strip().lower())


def _int(value) -> int | None:
    return None if value in (None, "") else int(float(value))


def _v1(f: dict) -> bool:
    return f["fix"] if f["patch"] is None else (f["patch"] and f["fix"])


def _v6(f: dict) -> bool | None:
    """Mesma regra de pipeline.dataset.is_corrective_v6, a partir das features."""
    if f["fix_terms"] is None:
        return None  # sem release notes: versão não avaliável
    if f["line_patch"] is None:
        return f["fix_terms"] > f["feature_terms"]
    return f["line_patch"] and f["fix_terms"] >= f["feature_terms"]


# nome -> (descrição, regra(features)). Features: patch (só o PATCH mudou em relação à anterior
# por data; None fora do SemVer), fix (commit fix/hotfix/revert), line_patch (PATCH > 0, patch da
# própria linha MAJOR.MINOR), fix_terms e feature_terms (termos nas release notes)
VERSIONS: dict[str, tuple[str, Callable[[dict], bool | None]]] = {
    "v1": ("só o PATCH muda E há commit fix/hotfix/revert (fora do SemVer: só o commit)", _v1),
    "v2": ("há commit fix/hotfix/revert", lambda f: f["fix"]),
    "v3": ("só o PATCH muda em relação à anterior por data", lambda f: bool(f["patch"])),
    "v4": ("só o PATCH muda OU há commit fix/hotfix/revert", lambda f: bool(f["patch"]) or f["fix"]),
    "v5": ("é patch da própria linha MAJOR.MINOR (PATCH > 0)", lambda f: bool(f["line_patch"])),
    "v6": ("patch da própria linha E notas com termos de correção ≥ termos de funcionalidade", _v6),
    "v7": ("patch da própria linha E há commit fix/hotfix/revert", lambda f: bool(f["line_patch"]) and f["fix"]),
}
CURRENT = "v6"  # versão usada em pipeline/dataset.py (is_corrective_v6)


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


def releases_from_raw(raw_dir: Path) -> list[dict]:
    """Linhas de releases.csv recalculadas dos JSONs brutos, com o mesmo código do pipeline."""
    rows = []
    for path in sorted(raw_dir.glob("*.json")):
        rows.extend(analyse_repository(json.loads(path.read_text(encoding="utf-8")))["releases"])
    return [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in rows]


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
        features = {
            "patch": to_bool(release.get("patch_bump")),
            "fix": fix,
            "line_patch": is_line_patch(c["tag_name"]),
            "fix_terms": _int(release.get("notes_fix_terms")),
            "feature_terms": _int(release.get("notes_feature_terms")),
        }
        row = {"repo": c["repo"], "tag_name": c["tag_name"], "consenso": label, **features}
        for name, (_, rule) in VERSIONS.items():
            row[name] = rule(features)
        detail.append(row)
    truth = [d["consenso"] == "sim" for d in detail]
    metrics = []
    for name, (description, _) in VERSIONS.items():
        if any(d[name] is None for d in detail):
            continue  # faltam as release notes: rode com --raw ou recalcule o dataset
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
        name = f"**{m['version']}** (adotada)" if m["version"] == CURRENT else m["version"]
        lines.append(
            f"| {name} | {m['description']} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} | "
            f"{_fmt(m['precision'], 3)} | {_fmt(m['recall'], 3)} | {_fmt(m['f1'], 3)} | "
            f"{'atinge' if m['meets_target'] else 'não atinge'} |"
        )
    missing = [v for v in VERSIONS if v not in {m["version"] for m in metrics}]
    if missing:
        lines += ["", f"Não avaliadas (faltam as release notes): {', '.join(missing)}. "
                      "Rode com `--raw data/raw/repos` ou recalcule o dataset."]
    return "\n".join(lines) + "\n"


def run(consensus_path: Path, releases_path: Path, output_dir: Path, raw_dir: Path | None = None) -> dict:
    if not consensus_path.exists():
        raise SystemExit(f"{consensus_path} não existe: rode antes `python -m analysis.concordancia`")
    release_rows = releases_from_raw(raw_dir) if raw_dir else load_csv(releases_path)
    metrics, detail, skipped = evaluate(load_csv(consensus_path), release_rows)
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
    parser.add_argument("--raw", type=Path, help="pasta com os JSONs brutos (data/raw/repos), no lugar de --releases")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    run(args.consenso, args.releases, args.output, args.raw)
    print((args.output / "heuristica.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
