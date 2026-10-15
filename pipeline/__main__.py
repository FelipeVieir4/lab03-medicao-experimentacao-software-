from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

from .collector import Collector, build_funnel, make_writer, write_outputs
from .config import load_config
from .dataset import build_dataset
from .github_client import GitHubApiError, GitHubClient

CORE_LIMIT_PER_HOUR = 5000


def _load_dotenv(path: str = ".env") -> None:
    """Lê GITHUB_TOKEN/GITHUB_TOKENS de um arquivo .env local (ignorado pelo Git)."""
    env = Path(path)
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class _Tee:
    """Escreve a saída no terminal e em data/raw/collect.log."""

    def __init__(self, stream, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = stream
        self.file = path.open("a", encoding="utf-8")

    def write(self, text):
        self.stream.write(text)
        self.file.write(text)
        self.file.flush()

    def flush(self):
        self.stream.flush()
        self.file.flush()


def _append_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    fields = list(rows[0].keys())
    with path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def execution_metrics(client: GitHubClient, collector: Collector, records: list[dict], began: float,
                      status: str) -> dict:
    """Métricas de uma execução da coleta (uma linha de data/raw/execution_log.csv)."""
    pool = client.pool
    duration_h = (time.time() - began) / 3600
    single_token_h = client.calls / CORE_LIMIT_PER_HOUR
    return {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(began)),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": status,
        "duration_min": round(duration_h * 60, 1),
        "n_tokens": len(pool.tokens),
        "workers": collector._workers(),
        "inner_workers": collector.config.inner_workers,
        "api_calls": client.calls,
        "cache_hits": client.cache_hits,
        "calls_by_token": ";".join(f"{pool.label(t)}:{n}" for t, n in pool.calls_by_token.items()),
        "token_switches": pool.switches,
        "ratelimit_wait_min": round(pool.wait_seconds / 60, 1),
        "secondary_wait_s": round(client.secondary_wait_seconds),
        "retries_5xx_network": client.retries,
        "backoff_s": round(client.backoff_seconds),
        "candidates_processed": len(records),
        "eligible": sum(r.get("stage") == "eligible" for r in records),
        "calls_per_hour": round(client.calls / duration_h) if duration_h > 0 else None,
        "min_hours_single_token": round(single_token_h, 2),
        "speedup_vs_single_token": round(single_token_h / duration_h, 2) if duration_h > 0 else None,
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Coleta e consolida dados para as métricas DORA")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument(
        "--step",
        choices=["all", "collect", "dataset"],
        default="all",
        help="all = coleta + dataset (padrão); collect = só coleta; dataset = só recalcula os CSVs",
    )
    args = parser.parse_args(argv)
    _load_dotenv()
    config = load_config(args.config)

    if args.step in ("all", "collect"):
        if not config.tokens:
            parser.error("defina GITHUB_TOKEN (ou GITHUB_TOKENS=tok1,tok2) no ambiente ou no arquivo .env")
        sys.stdout = _Tee(sys.stdout, config.output_dir / "collect.log")
        client = GitHubClient(list(config.tokens), config.cache_dir)
        collector = Collector(client, config)
        print(
            f"\n=== Execução iniciada em {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
            f"Janela {config.start_date}..{config.end_date} | meta {config.target_sample} repositórios elegíveis | "
            f"{len(config.tokens)} token(s), {collector._workers()} thread(s) entre repositórios, "
            f"{config.inner_workers} dentro de cada repositório",
            flush=True,
        )
        began = time.time()
        latest: list[dict] = []

        def on_batch(recs):
            latest[:] = recs
            write_outputs(recs, build_funnel(recs), config.output_dir)

        def finish(status: str) -> dict:
            metrics = execution_metrics(client, collector, latest, began, status)
            _append_csv(config.output_dir / "execution_log.csv", [metrics])
            _append_csv(config.output_dir / "token_events.csv", client.pool.events)
            client.close()
            print("\nResumo da execução:", flush=True)
            for key, value in metrics.items():
                print(f"  {key:<26} {value}", flush=True)
            return metrics

        try:
            records, funnel = collector.run(writer=make_writer(config.output_dir), on_batch=on_batch)
        except KeyboardInterrupt:
            finish("interrupted")
            print("\nInterrompido. Rode o mesmo comando para continuar de onde parou (cache).", flush=True)
            os._exit(130)
        except GitHubApiError as error:
            finish(f"error: {error}")
            sys.exit(f"Erro da API: {error}")
        latest[:] = records
        write_outputs(records, funnel, config.output_dir)
        finish("completed")
        print("\nFunil:", flush=True)
        for row in funnel:
            print(f"  {row['stage']:<14} {row['count']:>6}  {row['discard_reasons']}", flush=True)

    if args.step in ("all", "dataset"):
        stats = build_dataset(config.output_dir, config.processed_dir, config.seed)
        print(
            f"Dataset: {stats['repositories']} repositórios, {stats['releases']} releases, "
            f"{stats['runs']} workflow runs -> {config.processed_dir}",
            flush=True,
        )


if __name__ == "__main__":
    main()
