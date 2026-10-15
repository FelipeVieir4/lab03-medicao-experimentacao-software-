"""Cliente REST/GraphQL para a API do GitHub com cache em SQLite, paginação e rate limit."""

from __future__ import annotations

import gzip
import http.client
import json
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.github.com"
_LINK_RE = re.compile(r'<([^>]+)>;\s*rel="([^"]+)"')


class GitHubApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def parse_link_header(value: str | None) -> dict[str, str]:
    """Converte o cabeçalho Link em {rel: url}."""
    if not value:
        return {}
    return {rel: url for url, rel in _LINK_RE.findall(value)}


def last_page_number(link: str | None) -> int | None:
    """Número da última página indicado pelo cabeçalho Link, se houver."""
    last = parse_link_header(link).get("last")
    if not last:
        return None
    match = re.search(r"[?&]page=(\d+)", last)
    return int(match.group(1)) if match else None


def _log(message: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + message, flush=True)


def _decode(raw: bytes, headers) -> bytes:
    """Descompacta respostas gzip."""
    if raw and (headers.get("Content-Encoding") or "").lower() == "gzip":
        return gzip.decompress(raw)
    return raw


class TokenPool:
    """Rodízio de tokens por recurso (core, search, graphql)."""

    def __init__(self, tokens: list[str], switch_below: int = 50):
        if not tokens:
            raise ValueError("nenhum token informado")
        self.tokens = tokens
        self.switch_below = switch_below
        self.state: dict[tuple[str, str], tuple[int, float]] = {}
        self.current: dict[str, str] = {}
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.calls_by_token: dict[str, int] = {t: 0 for t in tokens}
        self.switches = 0
        self.wait_seconds = 0.0
        self._waiting_until: dict[str, float] = {}
        self._wait_counted: dict[str, float] = {}

    @staticmethod
    def label(token: str) -> str:
        return f"...{token[-4:]}"

    def _event(self, event: str, resource: str, token: str | None, **extra) -> None:
        row = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": event,
            "resource": resource,
            "token": self.label(token) if token else "",
            **extra,
        }
        self.events.append(row)
        details = " ".join(f"{k}={v}" for k, v in extra.items())
        _log(f"[token] {event} {resource} {row['token']} {details}".rstrip())

    def _remaining(self, resource: str, token: str, now: float) -> int:
        remaining, reset = self.state.get((resource, token), (10**6, 0.0))
        if reset and now >= reset:
            return 10**6
        return remaining

    def acquire(self, resource: str) -> str:
        while True:
            with self.lock:
                now = time.time()
                current = self.current.get(resource)
                if current and self._remaining(resource, current, now) > self.switch_below:
                    return current
                ranked = sorted(self.tokens, key=lambda t: self._remaining(resource, t, now), reverse=True)
                best = ranked[0]
                best_remaining = self._remaining(resource, best, now)
                current_remaining = self._remaining(resource, current, now) if current else 0
                if current_remaining > 1 and best_remaining <= self.switch_below:
                    return current
                if best_remaining > 1:
                    if current and best != current:
                        self.switches += 1
                        self._event(
                            "switch", resource, best,
                            previous=self.label(current),
                            previous_remaining=self._remaining(resource, current, now),
                            new_remaining=best_remaining if best_remaining < 10**6 else "cheia",
                        )
                    self.current[resource] = best
                    return best
                resets = [self.state.get((resource, t), (0, now + 60))[1] for t in self.tokens]
                wait = max(1.0, min(resets) - now + 2)
                if self._waiting_until.get(resource) != min(resets):
                    self._waiting_until[resource] = min(resets)
                    self._event("all_exhausted_wait", resource, None, wait_s=round(wait),
                                until=time.strftime("%H:%M:%S", time.localtime(min(resets))))
            time.sleep(wait)
            with self.lock:
                if self._wait_counted.get(resource) != self._waiting_until.get(resource):
                    self._wait_counted[resource] = self._waiting_until.get(resource)
                    self.wait_seconds += wait

    def count_call(self, token: str) -> None:
        with self.lock:
            self.calls_by_token[token] = self.calls_by_token.get(token, 0) + 1

    def update(self, resource: str, token: str, headers) -> None:
        remaining = headers.get("X-RateLimit-Remaining")
        reset = headers.get("X-RateLimit-Reset")
        resource = headers.get("X-RateLimit-Resource") or resource
        if remaining is None or reset is None:
            return
        with self.lock:
            self.state[(resource, token)] = (int(remaining), float(reset))

    def exhaust(self, resource: str, token: str, reset: float) -> None:
        with self.lock:
            already = self.state.get((resource, token)) == (0, reset)
            self.state[(resource, token)] = (0, reset)
            if already:
                return
            self._event("exhausted", resource, token, reset=time.strftime("%H:%M:%S", time.localtime(reset)))

    def summary(self) -> str:
        with self.lock:
            now = time.time()
            parts = []
            for token in self.tokens:
                remaining = self._remaining("core", token, now)
                parts.append(f"{self.label(token)}={remaining if remaining < 10**6 else '?'}")
            return "core restante: " + ", ".join(parts)


class ResponseCache:
    """Cache persistente em SQLite (um arquivo, seguro para várias threads)."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, timeout=60)
        self.conn.execute("PRAGMA journal_mode=PERSIST")  # WAL falhou em disco montado
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS responses ("
            " key TEXT PRIMARY KEY, status INTEGER, link TEXT, body TEXT, fetched_at REAL)"
        )
        self.conn.commit()
        self.lock = threading.Lock()

    def get(self, key: str):
        with self.lock:
            row = self.conn.execute(
                "SELECT status, link, body FROM responses WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        status, link, body = row
        return status, link, json.loads(body) if body is not None else None

    def put(self, key: str, status: int, link: str | None, body) -> None:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")) if body is not None else None
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?)",
                (key, status, link, payload, time.time()),
            )
            self.conn.commit()

    def close(self) -> None:
        with self.lock:
            self.conn.close()


class GitHubClient:
    """Cliente REST/GraphQL mínimo com cache, paginação, rodízio de tokens e retry."""

    # erros definitivos também ficam no cache
    CACHEABLE_ERRORS = {404, 409, 410, 422, 451}

    def __init__(
        self,
        tokens: list[str] | str | None,
        cache_dir: Path,
        max_retries: int = 6,
        timeout: int = 60,
    ):
        if isinstance(tokens, str):
            tokens = [tokens]
        self.pool = TokenPool([t for t in (tokens or []) if t])
        self.cache = ResponseCache(Path(cache_dir) / "github_cache.sqlite")
        self.max_retries = max_retries
        self.timeout = timeout
        self.calls = 0
        self.cache_hits = 0
        self.retries = 0
        self.backoff_seconds = 0.0
        self.secondary_wait_seconds = 0.0
        self._calls_lock = threading.Lock()

    @staticmethod
    def _resource_for(url: str) -> str:
        if "/search/" in url:
            return "search"
        if url.endswith("/graphql"):
            return "graphql"
        return "core"

    def _http(self, url: str, data: bytes | None = None):
        """Executa a requisição com rate limit e backoff. Retorna (status, link, body)."""
        resource = self._resource_for(url)
        attempt = 0
        while True:
            token = self.pool.acquire(resource)
            headers = {
                "Accept": "application/vnd.github+json",
                "Accept-Encoding": "gzip",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "lab03-dora-pipeline",
                "Authorization": f"Bearer {token}",
            }
            if data is not None:
                headers["Content-Type"] = "application/json"
            request = Request(url, data=data, headers=headers, method="POST" if data else "GET")
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = _decode(response.read(), response.headers)
                    self.pool.update(resource, token, response.headers)
                    self.pool.count_call(token)
                    with self._calls_lock:
                        self.calls += 1
                    body = json.loads(raw) if raw else None
                    return response.status, response.headers.get("Link"), body
            except HTTPError as error:
                self.pool.count_call(token)
                with self._calls_lock:
                    self.calls += 1
                self.pool.update(resource, token, error.headers)
                remaining = error.headers.get("X-RateLimit-Remaining")
                if error.code in (403, 429) and remaining == "0":
                    reset = float(error.headers.get("X-RateLimit-Reset", time.time() + 60))
                    self.pool.exhaust(resource, token, reset)
                    continue
                if error.code in (403, 429):
                    text = _decode(error.read(), error.headers).decode("utf-8", "replace")
                    if error.code == 429 or "secondary rate limit" in text.lower():
                        wait = int(error.headers.get("Retry-After") or 60)
                        self.pool._event("secondary_limit_wait", resource, token, wait_s=wait)
                        time.sleep(wait)
                        with self._calls_lock:
                            self.secondary_wait_seconds += wait
                        continue
                    return error.code, None, {"message": text[:500]}
                if error.code == 401:
                    raise GitHubApiError("token inválido (HTTP 401). Confira GITHUB_TOKEN.", 401)
                if error.code < 500:
                    try:
                        body = json.loads(_decode(error.read(), error.headers) or b"null")
                    except ValueError:
                        body = None
                    return error.code, None, body
            except (URLError, TimeoutError, ConnectionError, OSError, http.client.HTTPException, EOFError,
                    gzip.BadGzipFile, ValueError):
                pass
            if attempt >= self.max_retries:
                raise GitHubApiError(f"falha temporária após {self.max_retries} tentativas: {url}")
            wait = 2**attempt  # 1, 2, 4, 8, 16, 32 s
            attempt += 1
            with self._calls_lock:
                self.retries += 1
                self.backoff_seconds += wait
            time.sleep(wait)

    @staticmethod
    def build_url(path: str, params: dict | None = None) -> str:
        url = path if path.startswith("http") else f"{API}{path}"
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        return url

    def request(self, url: str, slim: Callable | None = None):
        """GET com cache. Retorna (status, link, body)."""
        cached = self.cache.get(url)
        if cached is not None:
            with self._calls_lock:
                self.cache_hits += 1
            return cached
        status, link, body = self._http(url)
        if status < 300 and slim is not None and body is not None:
            body = slim(body)
        if status < 300 or status in self.CACHEABLE_ERRORS:
            self.cache.put(url, status, link, body)
        return status, link, body

    def get(self, path: str, params: dict | None = None, slim: Callable | None = None):
        status, _, body = self.request(self.build_url(path, params), slim)
        if status >= 300:
            raise GitHubApiError(f"GitHub respondeu HTTP {status} para {path}", status)
        return body

    def iter_pages(
        self,
        path: str,
        params: dict | None = None,
        collection_key: str | None = None,
        slim: Callable | None = None,
    ):
        """Gera (página, itens, corpo) seguindo o cabeçalho Link até o fim."""
        url = self.build_url(path, {**(params or {}), "per_page": "100"})
        page = 1
        while url:
            status, link, body = self.request(url, slim)
            if status >= 300:
                raise GitHubApiError(f"GitHub respondeu HTTP {status} para {url}", status)
            if isinstance(body, list):
                items = body
            elif collection_key:
                items = (body or {}).get(collection_key, [])
            else:
                items = (body or {}).get("items", [])
            yield page, items, body
            url = parse_link_header(link).get("next")
            page += 1

    def get_pages(self, path, params=None, collection_key=None, limit=None, slim=None) -> list:
        items: list = []
        for _, page_items, _ in self.iter_pages(path, params, collection_key, slim):
            items.extend(page_items)
            if limit is not None and len(items) >= limit:
                return items[:limit]
        return items

    def graphql(self, query: str, variables: dict, cache_key: str):
        key = f"graphql::{cache_key}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached[2]
        payload = json.dumps({"query": query, "variables": variables}).encode()
        status, _, body = self._http(f"{API}/graphql", data=payload)
        if status >= 300 or body is None:
            raise GitHubApiError(f"GraphQL HTTP {status}", status)
        if body.get("errors") and not body.get("data"):
            raise GitHubApiError(f"GraphQL: {body['errors'][0].get('message')}")
        self.cache.put(key, status, None, body)
        return body

    def close(self) -> None:
        self.cache.close()


def tokens_from_env(environ) -> list[str]:
    raw = environ.get("GITHUB_TOKENS") or environ.get("GITHUB_TOKEN") or ""
    return [token.strip() for token in raw.split(",") if token.strip()]


if __name__ == "__main__":  # pragma: no cover
    sys.exit("use: python -m pipeline --config config.toml")
