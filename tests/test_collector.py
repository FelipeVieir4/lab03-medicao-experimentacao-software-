import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from pipeline.collector import (
    Collector,
    build_funnel,
    make_writer,
    month_slices,
    split_range,
    write_outputs,
)
from pipeline.config import Config, load_config
from pipeline.dataset import build_dataset
from pipeline.github_client import GitHubClient, last_page_number, parse_link_header


def make_config(tmp_path, **kw):
    base = dict(
        token="t", tokens=("t",), start_date="2025-10-02", end_date="2026-10-01",
        max_repositories=0, cache_dir=tmp_path / "cache", output_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed", stars_query="", target_sample=1,
        batch_size=10, workers=1,
    )
    base.update(kw)
    return Config(**base)


def rel(i, tag, date, pre=False):
    return {"id": i, "tag_name": tag, "name": tag, "draft": False, "prerelease": pre,
            "created_at": date, "published_at": date, "html_url": f"https://x/{tag}", "body": ""}


RELEASES = [
    rel(1, "v1.0.0", "2025-09-01T00:00:00Z"),
    rel(2, "v1.1.0", "2025-11-01T00:00:00Z"),
    rel(3, "v1.1.1", "2025-11-03T00:00:00Z"),
    rel(4, "v1.2.0-rc1", "2025-12-01T00:00:00Z", pre=True),
    rel(5, "v1.2.0", "2026-01-10T00:00:00Z"),
    rel(6, "v1.3.0", "2026-03-10T00:00:00Z"),
    rel(7, "v1.4.0", "2026-09-28T00:00:00Z"),
]


def runs_page(n, start_id=0):
    out = []
    for i in range(n):
        out.append({"id": start_id + i, "workflow_id": 1, "name": "CI", "event": "push",
                    "conclusion": "failure" if i % 10 == 0 else "success",
                    "created_at": f"2026-02-{1 + i % 27:02d}T{i % 24:02d}:00:00Z",
                    "run_started_at": f"2026-02-{1 + i % 27:02d}T{i % 24:02d}:00:00Z",
                    "updated_at": f"2026-02-{1 + i % 27:02d}T{i % 24:02d}:10:00Z"})
    return out


class FakeClient(GitHubClient):
    def __init__(self, cache_dir):
        super().__init__(["tok"], cache_dir)
        self.http_calls = []

    def _http(self, url, data=None):
        self.http_calls.append(url)
        if data is not None:  # GraphQL tags
            return 200, None, {"data": {"repository": {"refs": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [{"name": "v1.4.0", "target": {"__typename": "Commit", "oid": "a",
                           "authoredDate": "2026-09-27T00:00:00Z", "committedDate": "2026-09-27T00:00:00Z"}}]}}}}
        parsed = urlparse(url)
        q = parse_qs(parsed.query)
        path = parsed.path
        if path == "/search/repositories":
            items = [
                {"full_name": "org/good", "default_branch": "main", "stargazers_count": 5000,
                 "language": "Python", "created_at": "2020-01-01T00:00:00Z", "archived": False},
                {"full_name": "org/noci", "default_branch": "main", "stargazers_count": 4000,
                 "archived": False},
            ]
            return 200, None, {"total_count": 2, "items": items}
        if path.endswith("/actions/workflows"):
            n = 0 if "noci" in path else 1
            return 200, None, {"total_count": n, "workflows": [{"id": 1, "name": "CI"}][:n]}
        if path.endswith("/releases"):
            return 200, None, list(reversed(RELEASES))
        if path.endswith("/actions/runs"):
            if q.get("per_page") == ["1"]:
                return 200, None, {"total_count": 120, "workflow_runs": runs_page(1)}
            if q["created"][0].startswith("2026-02"):
                page = int(q.get("page", ["1"])[0])
                if page == 1:
                    nxt = url + "&page=2"
                    return 200, f'<{nxt}>; rel="next"', {"total_count": 120, "workflow_runs": runs_page(100)}
                return 200, None, {"total_count": 120, "workflow_runs": runs_page(20, 100)}
            return 200, None, {"total_count": 0, "workflow_runs": []}
        if "/compare/" in path:
            base_head = path.split("/compare/")[1]
            if base_head == "v1.0.0...v1.1.0":
                return 404, None, {"message": "Not Found"}
            commits = [{"sha": "s1", "commit": {"message": "fix: crash\nbody",
                                                  "author": {"date": "2025-10-25T00:00:00Z"}}}]
            return 200, None, {"status": "ahead", "ahead_by": 1, "total_commits": 1,
                               "commits": commits, "files": [{"big": "x" * 100}]}
        if path.endswith("/contributors"):
            last = "https://api.github.com/repos/org/good/contributors?per_page=1&anon=true&page=42"
            return 200, f'<{last}>; rel="last"', [{"login": "a"}]
        raise AssertionError(url)


def test_link_helpers():
    header = '<https://a?page=2>; rel="next", <https://a?page=9>; rel="last"'
    assert parse_link_header(header)["next"] == "https://a?page=2"
    assert last_page_number(header) == 9
    assert last_page_number(None) is None


def test_month_and_split_slices():
    slices = month_slices("2025-10-02", "2026-10-01")
    assert slices[0] == ("2025-10-02", "2025-10-31")
    assert slices[-1] == ("2026-10-01", "2026-10-01")
    assert len(slices) == 13
    assert split_range("2026-01-01", "2026-01-31") == (("2026-01-01", "2026-01-16"), ("2026-01-17", "2026-01-31"))


def test_full_collection_funnel_cache_and_dataset(tmp_path):
    config = make_config(tmp_path)
    client = FakeClient(config.cache_dir)
    collector = Collector(client, config)
    records, funnel = collector.run(writer=make_writer(config.output_dir))
    write_outputs(records, funnel, config.output_dir)

    good = records[0]
    assert good["stage"] == "eligible" and good["n_valid_runs"] == 120 and good["contributors"] == 42
    assert records[1]["discard_reason"] == "no_actions"
    assert [f["count"] for f in funnel] == [2, 1, 1, 1]

    data = json.loads((config.output_dir / "repos" / "org__good.json").read_text())
    assert "files" not in json.dumps(data["compares"])  # resposta enxuta no cache
    assert any(c.get("error") == 404 for c in data["compares"])
    assert data["tags"][0]["name"] == "v1.4.0"

    # retomada: segunda execução não faz nenhuma chamada HTTP
    client2 = FakeClient(config.cache_dir)
    Collector(client2, config).run()
    assert client2.http_calls == []

    stats = build_dataset(config.output_dir, config.processed_dir)
    assert stats["repositories"] == 1
    metrics = (config.processed_dir / "repositories_metrics.csv").read_text()
    assert "org/good" in metrics
    assert (config.processed_dir / "gold_sample_template.csv").exists()


def test_build_funnel_counts_errors():
    records = [
        {"stage": "eligible"}, {"stage": "candidate", "discard_reason": "no_actions"},
        {"stage": "with_actions", "discard_reason": "few_releases"},
        {"stage": "error", "discard_reason": "api_error_451"},
    ]
    funnel = build_funnel(records)
    assert [f["count"] for f in funnel] == [4, 2, 1, 1]
    assert "api_error_451=1" in funnel[1]["discard_reasons"]


def test_load_config_reads_tokens(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('[collection]\nstart_date="2025-10-02"\nend_date="2026-10-01"\ntarget_sample=300\n')
    config = load_config(cfg, environ={"GITHUB_TOKENS": "a, b"})
    assert config.tokens == ("a", "b") and config.target_sample == 300


def test_token_pool_sticky_switch_and_events():
    import time as _t
    from pipeline.github_client import TokenPool

    pool = TokenPool(["aaaa1111", "bbbb2222"], switch_below=50)
    first = pool.acquire("core")
    assert pool.acquire("core") == first  # pegajoso
    pool.update("core", first, {"X-RateLimit-Remaining": "10", "X-RateLimit-Reset": str(_t.time() + 3600)})
    second = pool.acquire("core")
    assert second != first and pool.switches == 1
    assert pool.events[-1]["event"] == "switch"
    pool.exhaust("core", second, _t.time() + 3600)
    assert any(e["event"] == "exhausted" for e in pool.events)
    assert "core restante" in pool.summary()


def test_execution_metrics(tmp_path):
    import time as _t
    from pipeline.__main__ import _append_csv, execution_metrics

    config = make_config(tmp_path)
    client = FakeClient(config.cache_dir)
    collector = Collector(client, config)
    records, _ = collector.run()
    m = execution_metrics(client, collector, records, _t.time() - 60, "completed")
    assert m["api_calls"] == client.calls and m["eligible"] == 1 and m["n_tokens"] == 1
    _append_csv(tmp_path / "log.csv", [m])
    _append_csv(tmp_path / "log.csv", [m])
    assert len((tmp_path / "log.csv").read_text().strip().splitlines()) == 3
    client.close()
