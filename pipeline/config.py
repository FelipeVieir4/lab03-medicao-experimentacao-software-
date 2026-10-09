from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tomllib


@dataclass(frozen=True)
class Config:
    token: str | None
    start_date: str
    end_date: str
    max_repositories: int
    cache_dir: Path
    output_dir: Path
    stars_query: str


def load_config(path: str | Path) -> Config:
    with Path(path).open("rb") as file:
        data = tomllib.load(file)
    collection = data.get("collection", {})
    paths = data.get("paths", {})
    return Config(
        token=os.getenv("GITHUB_TOKEN"),
        start_date=collection["start_date"],
        end_date=collection["end_date"],
        max_repositories=int(collection.get("max_repositories", 100)),
        cache_dir=Path(paths.get("cache_dir", "data/cache")),
        output_dir=Path(paths.get("output_dir", "data/raw")),
        stars_query=collection.get("stars_query", "stars:>1000"),
    )
