"""Seleção de repositórios, funil e coleta por repositório."""

from __future__ import annotations

import calendar
import csv
import json
import queue
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from .config import Config
from .github_client import GitHubApiError, GitHubClient, last_page_number

VALID_CONCLUSIONS = {"success", "failure", "timed_out", "startup_failure"}
RUN_FIELDS = (
    "id", "workflow_id", "name", "path", "event", "head_branch", "head_sha", "status",
    "conclusion", "run_attempt", "run_number", "created_at", "run_started_at", "updated_at",
)
RELEASE_FIELDS = (
    "id", "tag_name", "name", "draft", "prerelease", "created_at", "published_at",
    "target_commitish", "html_url",
)
REPO_FIELDS = (
    "id", "full_name", "html_url", "description", "fork", "archived", "default_branch",
    "stargazers_count", "forks_count", "open_issues_count", "language", "topics",
    "created_at", "pushed_at", "size", "license",
)
MAX_RELEASE_PAGES = 30
MAX_COMPARE_PAGES = 20

TAGS_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    refs(refPrefix: "refs/tags/", first: 100, after: $cursor,
         orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        target {
          __typename
          ... on Commit { oid authoredDate committedDate }
          ... on Tag { target { __typename ... on Commit { oid authoredDate committedDate } } }
        }
      }
    }
  }
}
"""


def _log(message: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + message, flush=True)


def window_bounds(config: Config) -> tuple[str, str]:
    return f"{config.start_date}T00:00:00Z", f"{config.end_date}T23:59:59Z"


def month_slices(start: str, end: str) -> list[tuple[str, str]]:
    """Divide [start, end] em fatias mensais."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    slices = []
    current = first
    while current <= last:
        month_end = date(current.year, current.month, calendar.monthrange(current.year, current.month)[1])
        slice_end = min(month_end, last)
        slices.append((current.isoformat(), slice_end.isoformat()))
        current = slice_end + timedelta(days=1)
    return slices


def split_range(start: str, end: str) -> tuple[tuple[str, str], tuple[str, str]]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    middle = first + (last - first) // 2
    return (first.isoformat(), middle.isoformat()), ((middle + timedelta(days=1)).isoformat(), last.isoformat())


def _pick(item: dict, fields) -> dict:
    out = {key: item.get(key) for key in fields}
    if "license" in out and isinstance(out["license"], dict):
        out["license"] = out["license"].get("spdx_id")
    return out


def slim_search(body: dict) -> dict:
    return {
        "total_count": body.get("total_count"),
        "incomplete_results": body.get("incomplete_results"),
        "items": [_pick(item, REPO_FIELDS) for item in body.get("items", [])],
    }


def slim_releases(body: list) -> list:
    out = []
    for release in body:
        item = _pick(release, RELEASE_FIELDS)
        item["body"] = (release.get("body") or "")[:2000]
        out.append(item)
    return out


def slim_runs(body: dict) -> dict:
    return {
        "total_count": body.get("total_count"),
        "workflow_runs": [_pick(run, RUN_FIELDS) for run in body.get("workflow_runs", [])],
    }


def slim_workflows(body: dict) -> dict:
    return {
        "total_count": body.get("total_count"),
        "workflows": [
            {k: w.get(k) for k in ("id", "name", "path", "state")} for w in body.get("workflows", [])
        ],
    }


def slim_compare(body: dict) -> dict:
    commits = []
    for commit in body.get("commits", []):
        info = commit.get("commit") or {}
        commits.append(
            {
                "sha": commit.get("sha"),
                "author_date": (info.get("author") or {}).get("date"),
                "committer_date": (info.get("committer") or {}).get("date"),
                "message": (info.get("message") or "").split("\n", 1)[0][:300],
            }
        )
    return {
        "status": body.get("status"),
        "ahead_by": body.get("ahead_by"),
        "behind_by": body.get("behind_by"),
        "total_commits": body.get("total_commits"),
        "commits": commits,
    }


class Collector:
    def __init__(self, client: GitHubClient, config: Config):
        self.client = client
        self.config = config
        self.start_ts, self.end_ts = window_bounds(config)

    def iter_candidates(self):
        """Busca fatiada por faixas de estrelas (limite de 1.000 por consulta)."""
        seen: set[str] = set()
        upper: int | None = None
        rank = 0
        while True:
            stars = f"{self.config.min_stars}..{upper}" if upper is not None else f">={self.config.min_stars}"
            query = f"stars:{stars} archived:false fork:false"
            lowest = None
            new_in_slice = 0
            returned = 0
            for _, items, _ in self.client.iter_pages(
                "/search/repositories",
                {"q": query, "sort": "stars", "order": "desc"},
                slim=slim_search,
            ):
                for item in items:
                    returned += 1
                    lowest = item["stargazers_count"] if lowest is None else min(lowest, item["stargazers_count"])
                    if item["full_name"] in seen:
                        continue
                    seen.add(item["full_name"])
                    new_in_slice += 1
                    rank += 1
                    yield rank, item
            if lowest is None or lowest <= self.config.min_stars or returned < 1000:
                return
            upper = lowest if new_in_slice else lowest - 1

    def _base(self, repo: dict) -> str:
        owner, name = repo["full_name"].split("/", 1)
        return f"/repos/{owner}/{name}"

    def fetch_workflows(self, repo: dict) -> list[dict]:
        return self.client.get_pages(
            f"{self._base(repo)}/actions/workflows", collection_key="workflows", slim=slim_workflows
        )

    def fetch_releases(self, repo: dict) -> tuple[list[dict], bool]:
        """Releases não-draft até cobrir a janela e a release estável anterior a ela.

        Retorna (releases ordenadas por published_at, cobriu_historico_anterior).
        """
        releases: list[dict] = []
        found_previous = False
        for page, items, _ in self.client.iter_pages(f"{self._base(repo)}/releases", slim=slim_releases):
            releases.extend(items)
            for item in items:
                published = item.get("published_at") or ""
                if published and published < self.start_ts and not item["draft"] and not item["prerelease"]:
                    found_previous = True
            oldest_created = min((i.get("created_at") or "9") for i in items) if items else ""
            if found_previous and oldest_created < self.start_ts:
                break
            if page >= MAX_RELEASE_PAGES:
                break
        published = [r for r in releases if not r.get("draft") and r.get("published_at")]
        published.sort(key=lambda r: (r["published_at"], r["id"]))
        return published, found_previous

    def count_runs(self, repo: dict) -> int:
        body = self.client.get(
            f"{self._base(repo)}/actions/runs",
            {
                "branch": repo["default_branch"],
                "event": "push",
                "created": f"{self.config.start_date}..{self.config.end_date}",
                "exclude_pull_requests": "true",
                "per_page": "1",
            },
            slim=slim_runs,
        )
        return int(body.get("total_count") or 0)

    def fetch_runs_range(self, repo: dict, start: str, end: str, capped: list) -> list[dict]:
        params = {
            "branch": repo["default_branch"],
            "event": "push",
            "created": f"{start}..{end}",
            "exclude_pull_requests": "true",
        }
        runs: list[dict] = []
        for page, items, body in self.client.iter_pages(
            f"{self._base(repo)}/actions/runs", params, collection_key="workflow_runs", slim=slim_runs
        ):
            if page == 1 and (body.get("total_count") or 0) > 1000 and start < end and self.config.split_capped_runs:
                left, right = split_range(start, end)
                return self.fetch_runs_range(repo, *left, capped) + self.fetch_runs_range(repo, *right, capped)
            if page == 1 and (body.get("total_count") or 0) > 1000:
                capped.append(start)
            runs.extend(items)
        return runs

    def fetch_runs(self, repo: dict) -> tuple[list[dict], list[str]]:
        capped: list[str] = []
        runs: list[dict] = []
        slices = month_slices(self.config.start_date, self.config.end_date)
        for chunk in self._parallel_map(lambda sl: self.fetch_runs_range(repo, sl[0], sl[1], capped), slices):
            runs.extend(chunk)
        unique = {run["id"]: run for run in runs}
        ordered = sorted(unique.values(), key=lambda r: (r.get("created_at") or "", r["id"]))
        return ordered, capped

    def fetch_compare(self, repo: dict, base: str, head: str) -> dict:
        path = f"{self._base(repo)}/compare/{quote(base, safe='')}...{quote(head, safe='')}"
        commits: list[dict] = []
        header: dict = {}
        truncated = False
        try:
            for page, _, body in self.client.iter_pages(path, collection_key="commits", slim=slim_compare):
                if page == 1:
                    header = {k: body.get(k) for k in ("status", "ahead_by", "behind_by", "total_commits")}
                commits.extend(body.get("commits", []))
                if page >= MAX_COMPARE_PAGES:
                    truncated = True
                    break
        except GitHubApiError as error:
            return {"base": base, "head": head, "error": error.status or "error", "commits": []}
        return {"base": base, "head": head, **header, "truncated": truncated, "commits": commits}

    def fetch_contributors(self, repo: dict) -> int | None:
        url = self.client.build_url(
            f"{self._base(repo)}/contributors", {"per_page": "1", "anon": "true"}
        )
        status, link, body = self.client.request(url)
        if status >= 300:
            return None
        last = last_page_number(link)
        return last if last is not None else len(body or [])

    def fetch_tags(self, repo: dict) -> list[dict]:
        owner, name = repo["full_name"].split("/", 1)
        tags: list[dict] = []
        cursor = None
        for page in range(1, 51):
            body = self.client.graphql(
                TAGS_QUERY,
                {"owner": owner, "name": name, "cursor": cursor},
                cache_key=f"tags:{repo['full_name']}:{cursor}",
            )
            refs = (((body.get("data") or {}).get("repository") or {}).get("refs")) or {}
            stop = False
            for node in refs.get("nodes", []):
                target = node.get("target") or {}
                if target.get("__typename") == "Tag":
                    target = target.get("target") or {}
                tags.append(
                    {
                        "name": node.get("name"),
                        "sha": target.get("oid"),
                        "author_date": target.get("authoredDate"),
                        "committer_date": target.get("committedDate"),
                    }
                )
                if (target.get("committedDate") or "9") < self.start_ts:
                    stop = True
            info = refs.get("pageInfo") or {}
            if stop or not info.get("hasNextPage"):
                break
            cursor = info.get("endCursor")
        return tags

    def in_window(self, timestamp: str | None) -> bool:
        return bool(timestamp) and self.start_ts <= timestamp <= self.end_ts

    def release_pairs(self, releases: list[dict]) -> list[tuple[str, str]]:
        """Pares (anterior, release) a comparar.

        - definição principal: release estável x estável anterior;
        - variante RQ 07 (release + pré-release): release x release anterior de qualquer tipo.
        """
        pairs: list[tuple[str, str]] = []
        previous_any = None
        previous_stable = None
        for release in releases:
            if self.in_window(release["published_at"]):
                if not release["prerelease"] and previous_stable is not None:
                    pairs.append((previous_stable["tag_name"], release["tag_name"]))
                if previous_any is not None:
                    pairs.append((previous_any["tag_name"], release["tag_name"]))
            previous_any = release
            if not release["prerelease"]:
                previous_stable = release
        return list(dict.fromkeys(pairs))

    def screen_and_collect(self, rank: int, repo: dict) -> dict:
        record = {
            "rank": rank,
            "full_name": repo["full_name"],
            "stars": repo.get("stargazers_count"),
            "language": repo.get("language"),
            "stage": "candidate",
            "discard_reason": None,
        }
        if repo.get("archived"):
            record["discard_reason"] = "archived"
            return record

        workflows = self.fetch_workflows(repo)
        record["n_workflows"] = len(workflows)
        if not workflows:
            record["discard_reason"] = "no_actions"
            return record
        record["stage"] = "with_actions"

        releases, covered_previous = self.fetch_releases(repo)
        window_stable = [r for r in releases if not r["prerelease"] and self.in_window(r["published_at"])]
        record["n_releases_window"] = len(window_stable)
        if len(window_stable) < self.config.min_releases:
            record["discard_reason"] = "few_releases"
            return record
        record["stage"] = "min_releases"

        total_runs = self.count_runs(repo)
        record["n_push_runs_total"] = total_runs
        if total_runs < self.config.min_runs:
            record["discard_reason"] = "few_workflow_runs"
            return record

        runs, capped_days = self.fetch_runs(repo)
        valid = [run for run in runs if run.get("conclusion") in VALID_CONCLUSIONS]
        record["n_valid_runs"] = len(valid)
        if len(valid) < self.config.min_runs:
            record["discard_reason"] = "few_valid_workflow_runs"
            return record
        record["stage"] = "eligible"

        compares = self._parallel_map(lambda pair: self.fetch_compare(repo, *pair), self.release_pairs(releases))
        contributors = self.fetch_contributors(repo)
        tags: list[dict] = []
        if self.config.collect_tags:
            try:
                tags = self.fetch_tags(repo)
            except GitHubApiError as error:
                _log(f"  tags indisponíveis para {repo['full_name']}: {error}")
        record["n_compares"] = len(compares)
        record["n_compare_errors"] = sum(1 for c in compares if c.get("error"))
        record["contributors"] = contributors

        full = {
            "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "window": {"start": self.config.start_date, "end": self.config.end_date},
            "repository": repo,
            "contributors": contributors,
            "workflows": workflows,
            "releases": releases,
            "releases_cover_previous": covered_previous,
            "compares": compares,
            "workflow_runs": runs,
            "runs_capped_days": capped_days,
            "tags": tags,
        }
        record["_full"] = full
        return record

    def _parallel_map(self, func, items: list) -> list:
        items = list(items)
        workers = max(1, self.config.inner_workers)
        if workers == 1 or len(items) <= 1:
            return [func(item) for item in items]
        with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
            return list(pool.map(func, items))

    def _workers(self) -> int:
        if self.config.workers > 0:
            return self.config.workers
        return max(1, min(6, 2 * len(self.client.pool.tokens)))

    def _process_batch(self, batch: list[tuple[int, dict]], writer) -> list[dict]:
        jobs: queue.Queue = queue.Queue()
        for item in batch:
            jobs.put(item)
        results: dict[int, dict] = {}
        lock = threading.Lock()

        def work():
            while True:
                try:
                    rank, repo = jobs.get_nowait()
                except queue.Empty:
                    return
                began = time.time()
                try:
                    record = self.screen_and_collect(rank, repo)
                except GitHubApiError as error:
                    record = {
                        "rank": rank, "full_name": repo["full_name"], "stars": repo.get("stargazers_count"),
                        "language": repo.get("language"), "stage": "error",
                        "discard_reason": f"api_error_{error.status or 'x'}",
                    }
                except Exception as error:  # noqa: BLE001
                    traceback.print_exc()
                    record = {
                        "rank": rank, "full_name": repo["full_name"], "stars": repo.get("stargazers_count"),
                        "language": repo.get("language"), "stage": "error",
                        "discard_reason": f"error_{type(error).__name__}",
                    }
                record["elapsed_s"] = round(time.time() - began, 1)
                full = record.pop("_full", None)
                if full is not None:
                    writer(full)
                status = "INCLUÍDO" if record["stage"] == "eligible" else f"descartado ({record['discard_reason']})"
                _log(f"#{rank} {repo['full_name']}: {status}")
                with lock:
                    results[rank] = record

        threads = [threading.Thread(target=work, daemon=True) for _ in range(self._workers())]
        for thread in threads:
            thread.start()
        while any(thread.is_alive() for thread in threads):
            time.sleep(0.5)  # permite Ctrl+C no Windows
        return [results[rank] for rank in sorted(results)]

    def run(self, writer=lambda full: None, on_batch=lambda records: None) -> tuple[list[dict], list[dict]]:
        records: list[dict] = []
        batch: list[tuple[int, dict]] = []
        candidates = self.iter_candidates()

        def eligible_count() -> int:
            return sum(r["stage"] == "eligible" for r in records)

        exhausted = False
        while eligible_count() < self.config.target_sample and len(records) < self.config.max_candidates:
            batch = []
            while len(batch) < self.config.batch_size and len(records) + len(batch) < self.config.max_candidates:
                try:
                    batch.append(next(candidates))
                except StopIteration:
                    exhausted = True
                    break
            if not batch:
                break
            records.extend(self._process_batch(batch, writer))
            on_batch(records)
            _log(
                f"== {len(records)} candidatos processados, {eligible_count()} elegíveis "
                f"(meta {self.config.target_sample}); chamadas à API: {self.client.calls}, "
                f"cache: {self.client.cache_hits}; {self.client.pool.summary()}"
            )
            if exhausted:
                break
        return records, build_funnel(records)


FUNNEL_STAGES = [
    ("candidates", "candidatos (busca, >= min_stars, não arquivados, não forks)", None),
    ("with_actions", "usam GitHub Actions", "no_actions"),
    ("min_releases", ">= 5 releases publicadas (não pré-release) na janela", "few_releases"),
    ("eligible", ">= 50 workflow runs válidos de push no default branch", "few_valid_workflow_runs"),
]


def build_funnel(records: list[dict]) -> list[dict]:
    order = {"candidate": 0, "with_actions": 1, "min_releases": 2, "eligible": 3}
    funnel = [
        {
            "stage": "candidates",
            "description": FUNNEL_STAGES[0][1],
            "count": len(records),
            "discarded": 0,
            "discard_reasons": "",
        }
    ]
    previous = len(records)
    for index, (stage, description, _) in enumerate(FUNNEL_STAGES[1:], start=1):
        stopped = [
            r for r in records
            if (r["stage"] != "error" and order.get(r["stage"], -1) == index - 1)
            or (index == 1 and r["stage"] == "error")
        ]
        reasons: dict[str, int] = {}
        for r in stopped:
            key = r.get("discard_reason") or "?"
            reasons[key] = reasons.get(key, 0) + 1
        count = previous - len(stopped)
        funnel.append(
            {
                "stage": stage,
                "description": description,
                "count": count,
                "discarded": len(stopped),
                "discard_reasons": "; ".join(f"{k}={v}" for k, v in sorted(reasons.items())),
            }
        )
        previous = count
    return funnel


SCREENING_FIELDS = [
    "rank", "full_name", "stars", "language", "stage", "discard_reason", "n_workflows",
    "n_releases_window", "n_push_runs_total", "n_valid_runs", "n_compares", "n_compare_errors",
    "contributors", "elapsed_s",
]


def repo_slug(full_name: str) -> str:
    return full_name.replace("/", "__")


def make_writer(output_dir: Path):
    repos_dir = output_dir / "repos"
    repos_dir.mkdir(parents=True, exist_ok=True)

    def write(full: dict) -> None:
        target = repos_dir / f"{repo_slug(full['repository']['full_name'])}.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(full, ensure_ascii=False), encoding="utf-8")
        tmp.replace(target)

    return write


def write_outputs(records: list[dict], funnel: list[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "screening.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SCREENING_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    with (output_dir / "funnel.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["stage", "description", "count", "discarded", "discard_reasons"])
        writer.writeheader()
        writer.writerows(funnel)
