from __future__ import annotations

import argparse

from .collector import Collector, write_outputs
from .config import load_config
from .github_client import GitHubClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Coleta dados para as métricas DORA")
    parser.add_argument("--config", default="config.toml")
    args = parser.parse_args()
    config = load_config(args.config)
    if not config.token:
        parser.error("defina GITHUB_TOKEN antes de iniciar a coleta")
    collector = Collector(GitHubClient(config.token, config.cache_dir), config)
    records, funnel = collector.run()
    write_outputs(records, funnel, config.output_dir)
    print(f"Coleta concluída: {len(records)} candidatos; dados em {config.output_dir}")


if __name__ == "__main__":
    main()
