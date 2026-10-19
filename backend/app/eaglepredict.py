"""Authorized EaglePredict provider scaffold.

No HTTP request is implemented here. EaglePredict has not supplied GoalEdge
with written permission or official API documentation, so guessing an endpoint,
authentication format, or response schema would be unreliable and unauthorized.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import settings

log = logging.getLogger("goaledge.eaglepredict")


@dataclass(frozen=True)
class EaglePredictMarket:
    key: str
    label: str
    aliases: tuple[str, ...]


MARKETS = (
    EaglePredictMarket("straight_win", "Straight Win", ("Straight Win",)),
    EaglePredictMarket("correct_score", "Correct Score", ("Correct Score",)),
    EaglePredictMarket("over_1_5", "Over 1.5 Goals", ("Over 1.5", "Over 1.5 Goals")),
    EaglePredictMarket("over_2_5", "Over 2.5 Goals", ("Over 2.5", "Over 2.5 Goals")),
    EaglePredictMarket("under_3_5", "Under 3.5 Goals", ("Under 3.5", "Under 3.5 Goals")),
    EaglePredictMarket("under_4_5", "Under 4.5 Goals", ("Under 4.5", "Under 4.5 Goals")),
    EaglePredictMarket("double_chance", "Double Chance", ("Double Chance",)),
    EaglePredictMarket("sure_3_odds", "Sure 3 Odds", ("Sure 3 Odd", "Sure 3 Odds")),
    EaglePredictMarket("rollover_1_30_odds", "Rollover 1.30 Odds", ("Roll Over 1.30 Odds", "Rollover 1.30 Odds")),
    EaglePredictMarket("multigoals", "MultiGoals", ("Multi Goals", "MultiGoals")),
    EaglePredictMarket("btts", "BTTS", ("BTTS", "Both Team to Score", "Both Teams To Score")),
    EaglePredictMarket("most_scoring_halves", "Most Scoring Halves", ("Most Scoring Halves",)),
    EaglePredictMarket("sure_2_odds", "Sure 2 Odds", ("Sure 2 Odd", "Sure 2 Odds")),
    EaglePredictMarket("win_either_halves", "Win Either Halves", ("Win Either Halves",)),
    EaglePredictMarket("draw_no_bet", "Draw No Bet", ("DNB", "Draw no Bet", "Draw No Bet")),
    EaglePredictMarket("over_9_5_corners", "Over 9.5 Corners", ("Over 9.5 Corners",)),
    EaglePredictMarket("under_9_5_corners", "Under 9.5 Corners", ("Under 9.5 Corners",)),
)


class EaglePredictProviderError(RuntimeError):
    """An authorized provider was selected but cannot be queried safely."""


def _configured() -> bool:
    return bool(
        settings.eaglepredict_enabled
        and (settings.eaglepredict_base_url or "").strip()
        and (settings.eaglepredict_api_key or "").strip()
    )


def status() -> dict:
    """Return metadata only; never expose URL, credentials, or fetched data."""
    configured = _configured()
    return {
        "provider": "eaglepredict",
        "configured": configured,
        "active": False,
        "reason": (
            "Provider is disabled pending written authorization and official API documentation."
            if not settings.eaglepredict_enabled
            else "Provider credentials or base URL are not configured."
            if not configured
            else "Provider configuration exists, but the official API contract has not been implemented."
        ),
        "markets": [
            {"key": market.key, "label": market.label, "source_labels": list(market.aliases)}
            for market in MARKETS
        ],
    }


class EaglePredictAdapter:
    """Boundary for a future licensed EaglePredict API client.

    Environment values are read only on the server. No cache is used until the
    provider's written terms define an allowed retention period.
    """

    def predictions(self) -> dict:
        now = datetime.now(timezone.utc)
        if not settings.eaglepredict_enabled or not _configured():
            return {
                "provider": "eaglepredict",
                "status": "provider_not_configured",
                "predictions": [],
                "fetched_at": now,
                "message": "EaglePredict is not configured. Written authorization and official API documentation are required before enabling it.",
            }

        # Do not make a speculative request. The URL, credential type, endpoint,
        # query parameters and payload mapping require provider documentation.
        log.warning("EaglePredict provider enabled but official API contract is not implemented")
        raise EaglePredictProviderError(
            "EaglePredict is configured but unavailable because its official API contract has not been implemented."
        )


def provider_response() -> dict:
    """Convert provider state into the stable public endpoint contract."""
    try:
        return EaglePredictAdapter().predictions()
    except EaglePredictProviderError as exc:
        log.warning("EaglePredict provider request failed: %s", exc)
        return {
            "provider": "eaglepredict",
            "status": "provider_error",
            "predictions": [],
            "fetched_at": datetime.now(timezone.utc),
            "message": "The EaglePredict provider could not be used. No EaglePredict predictions were returned.",
        }
