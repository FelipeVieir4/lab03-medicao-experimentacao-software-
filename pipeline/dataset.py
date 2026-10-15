"""Gera os CSVs do dataset e as métricas DORA a partir dos JSONs coletados."""

from __future__ import annotations

import csv
import gzip
import json
import random
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

from .metrics import (
    VALID_FAILURES,
    VALID_SUCCESS,
    change_failure_rate,
    classify_metric,
    classify_repository,
    recovery_episodes,
)

FIX_RE = re.compile(r"\b(revert|reverts|reverted|hotfix|hot-fix|fix|fixes|fixed|bugfix)\b", re.IGNORECASE)
SEMVER_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
CORRECTIVE_WINDOW = timedelta(days=7)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def days(delta: timedelta) -> float:
    return delta.total_seconds() / 86400


def parse_semver(tag: str | None) -> tuple[int, int, int] | None:
    match = SEMVER_RE.search(tag or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def is_patch_bump(previous_tag: str | None, tag: str | None) -> bool | None:
    """True se só o PATCH aumentou (2.3.0 -> 2.3.1). None se não for SemVer."""
    old, new = parse_semver(previous_tag), parse_semver(tag)
    if old is None or new is None:
        return None
    return old[:2] == new[:2] and new[2] > old[2]


def has_fix_commit(messages: list[str]) -> bool:
    return any(FIX_RE.search(message or "") for message in messages)


def is_corrective(previous_tag: str, tag: str, messages: list[str]) -> bool:
    """Heurística v1 de release corretiva (a ser validada na amostra-ouro).

    Corretiva = só o PATCH mudou E há commit com revert/hotfix/fix entre as releases.
    Para tags fora do SemVer, basta o commit com revert/hotfix/fix.
    """
    patch = is_patch_bump(previous_tag, tag)
    fix = has_fix_commit(messages)
    return fix if patch is None else (patch and fix)


def median_or_none(values):
    values = [v for v in values if v is not None]
    return median(values) if values else None


def quartiles(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None, None
    def q(p):
        k = (len(values) - 1) * p
        f = int(k)
        c = min(f + 1, len(values) - 1)
        return values[f] + (values[c] - values[f]) * (k - f)
    return q(0.25), q(0.75)


def analyse_repository(data: dict) -> dict:
    """Retorna as tabelas (linhas) e as métricas de um repositório."""
    repo = data["repository"]
    name = repo["full_name"]
    start = parse_dt(data["window"]["start"] + "T00:00:00Z")
    end = parse_dt(data["window"]["end"] + "T23:59:59Z")
    weeks = (end - start).total_seconds() / (7 * 86400)
    in_window = lambda dt: dt is not None and start <= dt <= end  # noqa: E731

    compares = {(c["base"], c["head"]): c for c in data.get("compares", [])}
    releases = sorted(data.get("releases", []), key=lambda r: (r["published_at"], r["id"]))

    release_rows, commit_rows = [], []
    lt_release, lt_commit, lt_release_pre, lt_commit_pre = [], [], [], []
    compare_errors = 0

    previous_any = previous_stable = None
    stable_in_window = []
    for release in releases:
        published = parse_dt(release["published_at"])
        if in_window(published):
            # definição principal: estável x estável anterior
            row = {
                "repo": name,
                "tag_name": release["tag_name"],
                "published_at": release["published_at"],
                "prerelease": release["prerelease"],
                "html_url": release.get("html_url"),
                "previous_tag": None,
                "compare_status": None,
                "n_commits": None,
                "oldest_commit_date": None,
                "lead_time_release_days": None,
            }
            if not release["prerelease"]:
                stable_in_window.append(release)
                if previous_stable is None:
                    row["compare_status"] = "first_release"
                else:
                    row["previous_tag"] = previous_stable["tag_name"]
                    comp = compares.get((previous_stable["tag_name"], release["tag_name"]))
                    if comp is None or comp.get("error"):
                        compare_errors += 1
                        row["compare_status"] = f"error_{comp.get('error') if comp else 'missing'}"
                    else:
                        row["compare_status"] = "truncated" if comp.get("truncated") else "ok"
                        row["total_commits_api"] = comp.get("total_commits")
                        dates = [parse_dt(c["author_date"]) for c in comp["commits"] if c.get("author_date")]
                        row["n_commits"] = len(dates)
                        if dates:
                            oldest = min(dates)
                            row["oldest_commit_date"] = oldest.isoformat()
                            row["lead_time_release_days"] = days(published - oldest)
                            lt_release.append(row["lead_time_release_days"])
                        for c in comp["commits"]:
                            dt = parse_dt(c.get("author_date"))
                            lt = days(published - dt) if dt else None
                            if lt is not None:
                                lt_commit.append(lt)
                            commit_rows.append(
                                {
                                    "repo": name,
                                    "release_tag": release["tag_name"],
                                    "release_published_at": release["published_at"],
                                    "sha": c["sha"],
                                    "author_date": c.get("author_date"),
                                    "lead_time_days": lt,
                                    "message": c.get("message"),
                                }
                            )
            # variante RQ 07: release + pré-release
            if previous_any is not None:
                comp = compares.get((previous_any["tag_name"], release["tag_name"]))
                if comp and not comp.get("error"):
                    dates = [parse_dt(c["author_date"]) for c in comp["commits"] if c.get("author_date")]
                    if dates:
                        lt_release_pre.append(days(published - min(dates)))
                    lt_commit_pre.extend(days(published - d) for d in dates)
            release_rows.append(row)
        previous_any = release
        if not release["prerelease"]:
            previous_stable = release

    by_tag = {r["tag_name"]: r for r in release_rows}
    evaluated = failed = corrective_count = 0
    ordered_stable = [r for r in releases if not r["prerelease"]]
    for index, release in enumerate(ordered_stable):
        published = parse_dt(release["published_at"])
        if not in_window(published):
            continue
        row = by_tag[release["tag_name"]]
        prev = ordered_stable[index - 1] if index > 0 else None
        corrective = None
        if prev is not None:
            comp = compares.get((prev["tag_name"], release["tag_name"]))
            msgs = [c.get("message") or "" for c in (comp or {}).get("commits", [])]
            row["patch_bump"] = is_patch_bump(prev["tag_name"], release["tag_name"])
            row["has_fix_commit"] = has_fix_commit(msgs)
            corrective = is_corrective(prev["tag_name"], release["tag_name"], msgs)
        row["is_corrective_v1"] = corrective
        corrective_count += bool(corrective)
        if published > end - CORRECTIVE_WINDOW:
            row["cfr_b_status"] = "censored"
            continue
        nxt = ordered_stable[index + 1] if index + 1 < len(ordered_stable) else None
        evaluated += 1
        is_failed = False
        if nxt is not None and parse_dt(nxt["published_at"]) - published <= CORRECTIVE_WINDOW:
            comp = compares.get((release["tag_name"], nxt["tag_name"]))
            msgs = [c.get("message") or "" for c in (comp or {}).get("commits", [])]
            is_failed = is_corrective(release["tag_name"], nxt["tag_name"], msgs)
        row["cfr_b_status"] = "failed" if is_failed else "ok"
        failed += is_failed

    run_rows, episode_rows = [], []
    by_workflow = defaultdict(list)
    for run in data.get("workflow_runs", []):
        conclusion = run.get("conclusion")
        label = "success" if conclusion == VALID_SUCCESS else "failure" if conclusion in VALID_FAILURES else "ignored"
        run_rows.append(
            {
                "repo": name,
                "run_id": run["id"],
                "workflow_id": run.get("workflow_id"),
                "workflow_name": run.get("name"),
                "conclusion": conclusion,
                "classification": label,
                "created_at": run.get("created_at"),
                "run_started_at": run.get("run_started_at"),
                "updated_at": run.get("updated_at"),
                "head_sha": run.get("head_sha"),
            }
        )
        if label != "ignored":
            by_workflow[run.get("workflow_id")].append(run)

    cfr_a = change_failure_rate(r["conclusion"] for r in run_rows)
    all_episodes, censored_total = [], 0
    for workflow_id, runs in by_workflow.items():
        runs.sort(key=lambda r: (r.get("run_started_at") or r.get("created_at"), r["id"]))
        parsed = [
            {
                "conclusion": r["conclusion"],
                "run_started_at": parse_dt(r.get("run_started_at") or r.get("created_at")),
                "updated_at": parse_dt(r.get("updated_at")),
            }
            for r in runs
        ]
        hours, censored = recovery_episodes(parsed)
        all_episodes.extend(hours)
        censored_total += censored
        for h in hours:
            episode_rows.append({"repo": name, "workflow_id": workflow_id, "recovery_hours": h, "censored": False})
        if censored:
            episode_rows.append({"repo": name, "workflow_id": workflow_id, "recovery_hours": None, "censored": True})

    tag_rows = [
        {"repo": name, "tag": t["name"], "sha": t.get("sha"), "commit_author_date": t.get("author_date")}
        for t in data.get("tags", [])
    ]
    tags_in_window = sum(in_window(parse_dt(t["commit_author_date"])) for t in tag_rows)

    n_stable = len(stable_in_window)
    n_all = sum(1 for r in release_rows)
    created = parse_dt(repo.get("created_at"))
    metrics = {
        "repo": name,
        "stars": repo.get("stargazers_count"),
        "language": repo.get("language"),
        "contributors": data.get("contributors"),
        "created_at": repo.get("created_at"),
        "age_years": round(days(end - created) / 365.25, 2) if created else None,
        "default_branch": repo.get("default_branch"),
        "n_workflows": len(data.get("workflows", [])),
        "n_releases": n_stable,
        "n_releases_with_pre": n_all,
        "n_tags": tags_in_window,
        "n_valid_runs": sum(r["classification"] != "ignored" for r in run_rows),
        "n_failed_runs": sum(r["classification"] == "failure" for r in run_rows),
        "n_success_runs": sum(r["classification"] == "success" for r in run_rows),
        "runs_capped_days": len(data.get("runs_capped_days", [])),
        "deployment_frequency": n_stable / weeks,
        "deployment_frequency_with_pre": n_all / weeks,
        "deployment_frequency_tags": tags_in_window / weeks,
        "lead_time_release_days": median_or_none(lt_release),
        "lead_time_commit_days": median_or_none(lt_commit),
        "lead_time_release_days_with_pre": median_or_none(lt_release_pre),
        "lead_time_commit_days_with_pre": median_or_none(lt_commit_pre),
        "n_releases_lead_time": len(lt_release),
        "n_commits_lead_time": len(lt_commit),
        "n_compare_errors": compare_errors,
        "cfr_ci": cfr_a,
        "cfr_delivery": failed / evaluated if evaluated else None,
        "n_releases_cfr_evaluated": evaluated,
        "n_releases_cfr_censored": sum(1 for r in release_rows if r.get("cfr_b_status") == "censored"),
        "rework_rate": corrective_count / n_stable if n_stable else None,
        "recovery_hours": median_or_none(all_episodes),
        "n_recovery_episodes": len(all_episodes),
        "n_recovery_censored": censored_total,
        "recovery_censored_ratio": censored_total / (len(all_episodes) + censored_total)
        if (all_episodes or censored_total)
        else None,
    }
    add_classifications(metrics)
    return {
        "metrics": metrics,
        "releases": release_rows,
        "commits": commit_rows,
        "runs": run_rows,
        "episodes": episode_rows,
        "tags": tag_rows,
    }


def _classify(metric: str, value):
    return classify_metric(metric, value) if value is not None else None


def add_classifications(m: dict) -> None:
    combos = {
        # C1 (referência): release, lead time (a), CFR (a)
        "c1": ("deployment_frequency", "lead_time_release_days", "cfr_ci"),
        # C2: release + pré-release, lead time (b), CFR (b)
        "c2": ("deployment_frequency_with_pre", "lead_time_commit_days_with_pre", "cfr_delivery"),
    }
    for combo, (df, lt, cfr) in combos.items():
        values = {
            "deployment_frequency": m.get(df),
            "lead_time_days": m.get(lt),
            "change_failure_rate": m.get(cfr),
            "recovery_hours": m.get("recovery_hours"),
        }
        for metric, value in values.items():
            m[f"class_{combo}_{metric}"] = _classify(metric, value)
        m[f"class_{combo}_overall"] = (
            classify_repository(values) if all(v is not None for v in values.values()) else None
        )


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def gold_sample(metrics_rows, release_rows, seed: int, n_repos: int = 60, n_releases: int = 5):
    """Sorteio reproduzível da amostra-ouro (seção 6) e planilha de rotulagem."""
    rng = random.Random(seed)
    names = sorted(m["repo"] for m in metrics_rows)
    chosen = sorted(rng.sample(names, min(n_repos, len(names))))
    rows = []
    by_repo = defaultdict(list)
    for r in release_rows:
        if not r["prerelease"]:
            by_repo[r["repo"]].append(r)
    for repo in chosen:
        releases = sorted(by_repo[repo], key=lambda r: r["published_at"])
        picked = sorted(rng.sample(releases, min(n_releases, len(releases))), key=lambda r: r["published_at"])
        for r in picked:
            rows.append(
                {
                    "repo": repo,
                    "repo_url": f"https://github.com/{repo}",
                    "tag_name": r["tag_name"],
                    "published_at": r["published_at"],
                    "release_url": r["html_url"],
                    "compare_url": f"https://github.com/{repo}/compare/{r['previous_tag']}...{r['tag_name']}"
                    if r.get("previous_tag")
                    else "",
                    "tipo_projeto": "",
                    "entrega_real": "",
                    "release_corretiva": "",
                }
            )
    return chosen, rows


def build_dataset(raw_dir: Path, processed_dir: Path, seed: int = 42) -> dict:
    files = sorted((raw_dir / "repos").glob("*.json"))
    tables = defaultdict(list)
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        result = analyse_repository(data)
        tables["metrics"].append(result["metrics"])
        for key in ("releases", "commits", "runs", "episodes", "tags"):
            tables[key].extend(result[key])

    write_csv(processed_dir / "repositories_metrics.csv", tables["metrics"])
    write_csv(processed_dir / "releases.csv", tables["releases"])
    write_csv(processed_dir / "release_commits.csv.gz", tables["commits"])
    write_csv(processed_dir / "workflow_runs.csv.gz", tables["runs"])
    write_csv(processed_dir / "recovery_episodes.csv", tables["episodes"])
    write_csv(processed_dir / "tags.csv", tables["tags"])

    if tables["metrics"]:
        _, gold = gold_sample(tables["metrics"], tables["releases"], seed)
        write_csv(processed_dir / "gold_sample_template.csv", gold)
        summary = []
        for column in (
            "deployment_frequency", "lead_time_release_days", "lead_time_commit_days",
            "cfr_ci", "cfr_delivery", "recovery_hours",
        ):
            values = [m[column] for m in tables["metrics"]]
            q1, q3 = quartiles(values)
            summary.append(
                {
                    "metric": column,
                    "n": sum(v is not None for v in values),
                    "median": median_or_none(values),
                    "q1": q1,
                    "q3": q3,
                    "iqr": (q3 - q1) if q1 is not None else None,
                }
            )
        write_csv(processed_dir / "summary.csv", summary)
    return {"repositories": len(files), "releases": len(tables["releases"]), "runs": len(tables["runs"])}
