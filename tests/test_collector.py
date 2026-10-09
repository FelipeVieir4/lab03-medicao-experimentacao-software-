from pathlib import Path

from pipeline.collector import Collector
from pipeline.config import Config


class FakeClient:
    def get_pages(self, path, params=None, collection_key=None, limit=None):
        if path == "/search/repositories":
            assert limit == 100
            return [{"full_name": "org/project", "default_branch": "main"}]
        if path.endswith("/releases"):
            return [{"draft": False, "prerelease": False, "published_at": "2025-06-01T00:00:00Z"}] * 5
        if path.endswith("/actions/runs"):
            assert collection_key == "workflow_runs"
            return [{"conclusion": "success"}] * 50
        raise AssertionError(path)

    def get(self, path, params=None):
        if path.endswith("/actions/workflows"):
            return {"workflows": [{"id": 1}]}
        raise AssertionError(path)


def test_collector_applies_sprint_one_minimums():
    config = Config(
        token="test",
        start_date="2025-01-01",
        end_date="2025-12-31",
        max_repositories=100,
        cache_dir=Path("data/cache"),
        output_dir=Path("data/raw"),
        stars_query="stars:>1000",
    )
    records, funnel = Collector(FakeClient(), config).run()

    assert records[0]["included"] is True
    assert funnel == [
        {"stage": "candidates", "count": 1},
        {"stage": "with_actions", "count": 1},
        {"stage": "minimum_data", "count": 1},
    ]
