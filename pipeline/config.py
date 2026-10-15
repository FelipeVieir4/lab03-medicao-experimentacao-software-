from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

from .github_client import tokens_from_env


@dataclass(frozen=True)
class Config:
    token: str | None
    start_date: str
    end_date: str
    max_repositories: int
    cache_dir: Path
    output_dir: Path
    stars_query: str
    tokens: tuple[str, ...] = field(default_factory=tuple)
    target_sample: int = 350
    max_candidates: int = 6000
    min_stars: int = 1000
    batch_size: int = 100
    workers: int = 0  # 0 = automático (2 por token, máx. 6)
    collect_tags: bool = True
    inner_workers: int = 4  # threads por repositório (meses de runs e compares em paralelo)
    split_capped_runs: bool = False  # True = subdivide meses com > 1.000 runs (muito caro)
    min_releases: int = 5
    min_runs: int = 50
    processed_dir: Path = Path("data/processed")
    seed: int = 42


def load_config(path: str | Path, environ=None) -> Config:
    environ = os.environ if environ is None else environ
    with Path(path).open("rb") as file:
        data = tomllib.load(file)
    collection = data.get("collection", {})
    paths = data.get("paths", {})
    tokens = tuple(tokens_from_env(environ))
    return Config(
        token=tokens[0] if tokens else None,
        tokens=tokens,
        start_date=collection["start_date"],
        end_date=collection["end_date"],
        max_repositories=int(collection.get("max_repositories", 0)),
        stars_query=collection.get("stars_query", "stars:>1000"),
        target_sample=int(collection.get("target_sample", 350)),
        max_candidates=int(collection.get("max_candidates", 6000)),
        min_stars=int(collection.get("min_stars", 1000)),
        batch_size=int(collection.get("batch_size", 100)),
        workers=int(collection.get("workers", 0)),
        collect_tags=bool(collection.get("collect_tags", True)),
        inner_workers=int(collection.get("inner_workers", 4)),
        split_capped_runs=bool(collection.get("split_capped_runs", False)),
        min_releases=int(collection.get("min_releases", 5)),
        min_runs=int(collection.get("min_runs", 50)),
        seed=int(collection.get("seed", 42)),
        cache_dir=Path(paths.get("cache_dir", "data/cache")),
        output_dir=Path(paths.get("output_dir", "data/raw")),
        processed_dir=Path(paths.get("processed_dir", "data/processed")),
    )
