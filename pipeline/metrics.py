"""Funções puras para cálculo das métricas DORA.

As funções recebem dados já normalizados da coleta e não conhecem a API do GitHub.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from statistics import median

VALID_SUCCESS = "success"
VALID_FAILURES = frozenset({"failure", "timed_out", "startup_failure"})
IGNORED_CONCLUSIONS = frozenset(
    {"cancelled", "skipped", "neutral", "action_required", "stale", None, ""}
)


def _median_or_none(values: Iterable[float]) -> float | None:
    values = list(values)
    return median(values) if values else None


def deployment_frequency(release_dates: Sequence[datetime], weeks: float = 52.14) -> float:
    """Retorna releases por semana dentro da janela de observação."""
    if weeks <= 0:
        raise ValueError("weeks deve ser maior que zero")
    return len(release_dates) / weeks


def lead_time_by_release(
    releases: Sequence[tuple[datetime, Sequence[datetime]]],
) -> float | None:
    """Calcula a mediana do lead time pelo commit mais antigo de cada release."""
    lead_times = [
        (release_date - min(commit_dates)).total_seconds() / 86400
        for release_date, commit_dates in releases
        if commit_dates
    ]
    return _median_or_none(lead_times)


def lead_time_by_commit(
    releases: Sequence[tuple[datetime, Sequence[datetime]]],
) -> float | None:
    """Calcula a mediana do lead time de cada commit incluído nas releases."""
    lead_times = [
        (release_date - commit_date).total_seconds() / 86400
        for release_date, commit_dates in releases
        for commit_date in commit_dates
    ]
    return _median_or_none(lead_times)


def change_failure_rate(conclusions: Iterable[str | None]) -> float | None:
    """Calcula CFR do proxy de CI, ignorando conclusões inconclusivas."""
    relevant = [conclusion for conclusion in conclusions if conclusion not in IGNORED_CONCLUSIONS]
    if not relevant:
        return None
    failures = sum(conclusion in VALID_FAILURES for conclusion in relevant)
    return failures / len(relevant)


def recovery_episodes(
    runs: Sequence[dict],
) -> tuple[list[float], int]:
    """Retorna tempos de recuperação em horas e quantidade de episódios censurados.

    Cada item deve conter ``conclusion``, ``run_started_at`` e ``updated_at`` como
    datetimes. A sequência deve pertencer a um único workflow e estar ordenada.
    """
    recovery_hours: list[float] = []
    censored = 0
    failure_started_at: datetime | None = None

    for run in runs:
        conclusion = run.get("conclusion")
        if conclusion in IGNORED_CONCLUSIONS:
            continue
        if conclusion in VALID_FAILURES:
            if failure_started_at is None:
                failure_started_at = run["run_started_at"]
        elif conclusion == VALID_SUCCESS and failure_started_at is not None:
            recovery_hours.append(
                (run["updated_at"] - failure_started_at).total_seconds() / 3600
            )
            failure_started_at = None

    if failure_started_at is not None:
        censored = 1
    return recovery_hours, censored


def recovery_time(runs: Sequence[dict]) -> tuple[float | None, int]:
    """Calcula a mediana do tempo de recuperação de um workflow."""
    episodes, censored = recovery_episodes(runs)
    return _median_or_none(episodes), censored


def classify_metric(metric: str, value: float) -> str:
    """Classifica uma métrica nos cortes fixos definidos no enunciado."""
    if metric == "deployment_frequency":
        thresholds = [(7, "Elite"), (1, "High"), (1 / 4.345, "Medium")]
        return next((label for threshold, label in thresholds if value >= threshold), "Low")
    if metric == "lead_time_days":
        thresholds = [(1, "Elite"), (7, "High"), (30, "Medium")]
        return next((label for threshold, label in thresholds if value < threshold), "Low")
    if metric == "change_failure_rate":
        thresholds = [(0.15, "Elite"), (0.30, "High"), (0.45, "Medium")]
        return next((label for threshold, label in thresholds if value <= threshold), "Low")
    if metric == "recovery_hours":
        thresholds = [(1, "Elite"), (24, "High"), (168, "Medium")]
        return next((label for threshold, label in thresholds if value < threshold), "Low")
    raise ValueError(f"métrica desconhecida: {metric}")


def classify_repository(metrics: dict[str, float]) -> str:
    """Calcula a classificação geral pela mediana inteira das quatro métricas."""
    points = {"Elite": 4, "High": 3, "Medium": 2, "Low": 1}
    categories = [classify_metric(metric, value) for metric, value in metrics.items()]
    if len(categories) != 4:
        raise ValueError("são necessárias exatamente quatro métricas")
    score = sorted(points[category] for category in categories)[1]
    return {4: "Elite", 3: "High", 2: "Medium", 1: "Low"}[score]
