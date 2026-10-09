from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class GitHubApiError(RuntimeError):
    pass


class GitHubClient:
    """Cliente REST mínimo com cache, paginação e retry para a API do GitHub."""

    def __init__(self, token: str | None, cache_dir: Path, max_retries: int = 4):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "lab03-dora-pipeline",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _cache_path(self, path: str, params: dict[str, str] | None) -> Path:
        key = json.dumps([path, params or {}], sort_keys=True).encode()
        return self.cache_dir / f"{hashlib.sha256(key).hexdigest()}.json"

    def get(self, path: str, params: dict[str, str] | None = None):
        cache_path = self._cache_path(path, params)
        if cache_path.exists():
            return json.loads(cache_path.read_text())

        query = f"?{urlencode(params)}" if params else ""
        request = Request(f"https://api.github.com{path}{query}", headers=self.headers)
        for attempt in range(self.max_retries):
            try:
                with urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read())
                    cache_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2))
                    remaining = response.headers.get("X-RateLimit-Remaining")
                    if remaining == "0":
                        reset = int(response.headers.get("X-RateLimit-Reset", time.time()))
                        time.sleep(max(0, reset - int(time.time())))
                    return payload
            except HTTPError as error:
                if error.code == 403 and error.headers.get("X-RateLimit-Remaining") == "0":
                    reset = int(error.headers.get("X-RateLimit-Reset", time.time()))
                    time.sleep(max(0, reset - int(time.time())))
                    continue
                if error.code < 500:
                    raise GitHubApiError(f"GitHub respondeu HTTP {error.code} para {path}") from error
            except URLError:
                pass
            time.sleep(2**attempt)
        raise GitHubApiError(f"falha temporária após {self.max_retries} tentativas: {path}")

    def get_pages(
        self,
        path: str,
        params: dict[str, str] | None = None,
        collection_key: str | None = None,
        limit: int | None = None,
    ) -> list:
        if limit is not None and limit <= 0:
            return []
        page = 1
        items: list = []
        while True:
            page_size = min(limit - len(items), 100) if limit is not None else 100
            page_params = {**(params or {}), "page": str(page), "per_page": str(page_size)}
            payload = self.get(path, page_params)
            if isinstance(payload, list):
                page_items = payload
            else:
                key = collection_key or ("items" if "items" in payload else None)
                page_items = payload.get(key, []) if key else []
            items.extend(page_items)
            if limit is not None and len(items) >= limit:
                return items[:limit]
            if len(page_items) < 100:
                return items
            page += 1
