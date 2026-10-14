"""SportMonks fixture client.

Optional live-match provider for the match centre and livescore views. The app
keeps Flashscore as the default source for real fixtures, but a configured token
allows the site to replace the live feed with SportMonks payloads without
changing the frontend contract.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Any

from .config import settings


class SportMonksUnavailable(RuntimeError):
    """Raised when SportMonks can't answer the request."""


_DEFAULT_INCLUDE = (
    "state;participants;venue;scores;weatherReport;league;events.player;"
    "statistics.type;events.type;events.period;sidelined.sideline.player;"
    "sidelined.sideline.type"
)


def _token() -> str:
    token = (settings.sportmonks_api_token or "").strip()
    if not token:
        raise SportMonksUnavailable("SPORTMONKS_API_TOKEN is not configured")
    return token


def _request(path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = {
        "api_token": _token(),
        **(params or {}),
    }
    url = f"{settings.sportmonks_base_url.rstrip('/')}{path}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, headers={"User-Agent": "GoalEdge/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=settings.sportmonks_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, TypeError) as exc:
        raise SportMonksUnavailable(f"SportMonks request failed: {exc}") from exc
    if isinstance(payload, dict):
        return payload
    return {"data": payload}


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _status_name(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("state") or value.get("name") or value.get("short_name")
    state = str(value or "").strip().lower()
    if state in {"ft", "full time", "finished"}:
        return "finished"
    if state in {"live", "inplay", "in-play", "ht", "half time"}:
        return "live"
    if state in {"scheduled", "ns", "not started"}:
        return "scheduled"
    if state.startswith("inplay"):
        return "live"
    return state or "scheduled"


def _team_from_participant(team: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(team, dict):
        return {"name": "Unknown", "logo": None, "short_code": None, "location": "home"}
    meta = team.get("meta") or {}
    return {
        "name": team.get("name") or "Unknown",
        "logo": team.get("image_path") or team.get("logo_path"),
        "short_code": team.get("short_code"),
        "location": meta.get("location") or "home",
    }


def _normalise_event(event: dict[str, Any]) -> dict[str, Any]:
    kind = (event.get("type") or {}).get("name") or event.get("type_name") or "note"
    name = str(kind).strip().lower()
    if "goal" in name:
        kind_name = "goal"
    elif "yellow" in name:
        kind_name = "yellow"
    elif "red" in name:
        kind_name = "red"
    elif "sub" in name:
        kind_name = "sub"
    elif "assist" in name:
        kind_name = "assist"
    elif "var" in name:
        kind_name = "var"
    elif "penalty" in name:
        kind_name = "penalty"
    else:
        kind_name = "note"

    team_data = event.get("participant") or event.get("team")
    return {
        "id": event.get("id"),
        "minute": _as_int(event.get("minute")),
        "kind": kind_name,
        "player": event.get("player_name") or (event.get("player") or {}).get("name") or "Unknown",
        "team_id": event.get("participant_id") or (team_data or {}).get("id"),
        "team": (team_data or {}).get("name") if isinstance(team_data, dict) else None,
        "type": str(kind),
        "detail": event.get("info") or event.get("addition") or "",
        "score": event.get("result"),
    }


def _normalise_fixture(raw: dict[str, Any]) -> dict[str, Any]:
    participants = raw.get("participants") or []
    home_participant = next((p for p in participants if (p.get("meta") or {}).get("location") == "home"), participants[0] if participants else {})
    away_participant = next((p for p in participants if (p.get("meta") or {}).get("location") == "away"), participants[-1] if participants else {})
    home = _team_from_participant(home_participant)
    away = _team_from_participant(away_participant)

    score_items = raw.get("scores") or []
    goals_by_participant: dict[str, int] = {}
    for item in score_items:
        if not isinstance(item, dict):
            continue
        score = item.get("score") or {}
        participant_id = item.get("participant_id") or (item.get("participant") or {}).get("id")
        if participant_id is None:
            continue
        value = _as_int(score.get("goals")) if isinstance(score, dict) else None
        if value is not None:
            goals_by_participant[str(participant_id)] = value

    home_goals = goals_by_participant.get(str((home_participant or {}).get("id")))
    away_goals = goals_by_participant.get(str((away_participant or {}).get("id")))
    if home_goals is None and home_participant:
        home_goals = goals_by_participant.get(str(home_participant.get("id")))
    if away_goals is None and away_participant:
        away_goals = goals_by_participant.get(str(away_participant.get("id")))
    if home_goals is None:
        home_goals = _as_int((raw.get("score") or {}).get("home"))
    if away_goals is None:
        away_goals = _as_int((raw.get("score") or {}).get("away"))

    league = raw.get("league") or {}
    venue = raw.get("venue") or {}
    kickoff_raw = raw.get("starting_at") or raw.get("kickoff")
    kickoff: datetime | None = None
    if kickoff_raw:
        try:
            kickoff = datetime.fromisoformat(str(kickoff_raw).replace("Z", "+00:00"))
        except ValueError:
            kickoff = None
    if kickoff is not None and kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)

    return {
        "id": raw.get("id"),
        "fixture_id": raw.get("id"),
        "match_id": str(raw.get("id")),
        "kickoff": kickoff.isoformat() if kickoff else None,
        "status": _status_name(raw.get("state") or raw.get("status") or raw.get("state_id")),
        "home_team": {"name": home["name"], "logo": home["logo"], "short_code": home.get("short_code")},
        "away_team": {"name": away["name"], "logo": away["logo"], "short_code": away.get("short_code")},
        "competition": {
            "name": league.get("name"),
            "label": league.get("name"),
            "country": (league.get("country") or {}).get("name") if isinstance(league.get("country"), dict) else None,
            "id": league.get("id"),
        },
        "venue": {"name": venue.get("name"), "city": venue.get("city_name"), "capacity": venue.get("capacity")},
        "home_goals": home_goals,
        "away_goals": away_goals,
        "score": {"home": home_goals, "away": away_goals, "display": f"{home_goals or 0}-{away_goals or 0}" if home_goals is not None and away_goals is not None else None},
        "weather": raw.get("weatherReport"),
        "events": [_normalise_event(e) for e in (raw.get("events") or []) if isinstance(e, dict)],
        "statistics": raw.get("statistics") or [],
        "raw": raw,
    }


def fetch_fixture(fixture_id: int | str) -> dict[str, Any]:
    payload = _request(
        f"/football/fixtures/{fixture_id}",
        params={"include": _DEFAULT_INCLUDE},
    )
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        return _normalise_fixture(data)
    if isinstance(data, list) and data:
        return _normalise_fixture(data[0])
    raise SportMonksUnavailable(f"SportMonks did not return fixture {fixture_id}")


def fetch_fixtures_for_date(target_date: str | date) -> list[dict[str, Any]]:
    requested = target_date.isoformat() if isinstance(target_date, date) else str(target_date)
    payload = _request(
        "/football/fixtures",
        params={
            "include": _DEFAULT_INCLUDE,
            "filter[date]": requested,
        },
    )
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    return [_normalise_fixture(item) for item in rows if isinstance(item, dict)]
