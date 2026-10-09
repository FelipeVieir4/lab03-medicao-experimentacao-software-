from __future__ import annotations

import csv
import json
from pathlib import Path

from .config import Config
from .github_client import GitHubClient


class Collector:
    def __init__(self, client: GitHubClient, config: Config):
        self.client = client
        self.config = config

    def search_repositories(self) -> list[dict]:
        repositories = self.client.get_pages(
            "/search/repositories",
            {"q": self.config.stars_query, "sort": "stars", "order": "desc"},
            limit=self.config.max_repositories,
        )
        return repositories

    def collect_repository(self, repository: dict) -> dict:
        full_name = repository["full_name"]
        owner, name = full_name.split("/", 1)
        base = f"/repos/{owner}/{name}"
        workflows = self.client.get(f"{base}/actions/workflows").get("workflows", [])
        releases = self.client.get_pages(f"{base}/releases")
        releases = [
            release
            for release in releases
            if not release.get("draft")
            and not release.get("prerelease")
            and self.config.start_date <= (release.get("published_at") or "")[:10] <= self.config.end_date
        ]
        runs = self.client.get_pages(
            f"{base}/actions/runs",
            {
                "branch": repository["default_branch"],
                "event": "push",
                "created": f"{self.config.start_date}..{self.config.end_date}",
            },
            collection_key="workflow_runs",
        )
        valid_runs = [
            run for run in runs if run.get("conclusion") in {"success", "failure", "timed_out", "startup_failure"}
        ]
        return {
            "repository": repository,
            "workflows": workflows,
            "releases": releases,
            "workflow_runs": valid_runs,
            "included": len(releases) >= 5 and len(valid_runs) >= 50,
            "discard_reason": None
            if len(releases) >= 5 and len(valid_runs) >= 50
            else "minimum_releases_or_workflow_runs",
        }

    def run(self) -> tuple[list[dict], list[dict]]:
        candidates = self.search_repositories()
        records = [self.collect_repository(repository) for repository in candidates]
        funnel = [
            {"stage": "candidates", "count": len(candidates)},
            {"stage": "with_actions", "count": sum(bool(record["workflows"]) for record in records)},
            {"stage": "minimum_data", "count": sum(record["included"] for record in records)},
        ]
        return records, funnel


def write_outputs(records: list[dict], funnel: list[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        slug = record["repository"]["full_name"].replace("/", "__")
        (output_dir / f"{slug}.json").write_text(json.dumps(record, ensure_ascii=True, indent=2))
    with (output_dir / "funnel.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["stage", "count"])
        writer.writeheader()
        writer.writerows(funnel)
