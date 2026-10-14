"""Cached football-data.org competition emblem lookup."""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request

from .config import settings

log = logging.getLogger(__name__)

_cache: dict[tuple[str, str], str] = {}
_expires_at = 0.0
_has_cache = False
_lock = threading.Lock()


def _key(name: str | None, country: str | None) -> tuple[str, str]:
    return (
        " ".join((name or "").casefold().split()),
        " ".join((country or "").casefold().split()),
    )


def _allowed_emblem(url: object) -> str | None:
    if not isinstance(url, str) or not url.startswith("https://crests.football-data.org/"):
        return None
    return url


def competition_emblems() -> dict[tuple[str, str], str]:
    """Fetch the provider's available competition emblems, using a daily cache."""
    global _cache, _expires_at, _has_cache

    if not settings.football_data_api_token:
        return {}

    with _lock:
        now = time.monotonic()
        if _has_cache and now < _expires_at:
            return dict(_cache)

        request = urllib.request.Request(
            f"{settings.football_data_base_url.rstrip('/')}/competitions",
            headers={
                "X-Auth-Token": settings.football_data_api_token,
                "Accept": "application/json",
                "User-Agent": "GoalEdge/1.0",
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=settings.football_data_timeout_seconds
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            log.warning("football-data.org competition emblem fetch failed: %s", exc)
            return dict(_cache)

        competitions = payload.get("competitions") if isinstance(payload, dict) else None
        if not isinstance(competitions, list):
            log.warning("football-data.org returned an unexpected competitions response")
            return dict(_cache)

        mapped: dict[tuple[str, str], str] = {}
        ambiguous: set[tuple[str, str]] = set()
        for item in competitions:
            if not isinstance(item, dict):
                continue
            area = item.get("area")
            country = area.get("name") if isinstance(area, dict) else None
            key = _key(item.get("name"), country)
            emblem = _allowed_emblem(item.get("emblem"))
            if not key[0] or not emblem:
                continue
            if key in mapped:
                ambiguous.add(key)
            else:
                mapped[key] = emblem

        for key in ambiguous:
            mapped.pop(key, None)

        _cache = mapped
        _expires_at = now + max(settings.football_data_cache_seconds, 60)
        _has_cache = True
        return dict(_cache)


def emblem_for_competition(
    name: str | None,
    country: str | None,
    emblems: dict[tuple[str, str], str] | None = None,
) -> str | None:
    """Resolve an exact league/country pair; never guess between same-named leagues."""
    return (emblems or {}).get(_key(name, country))
