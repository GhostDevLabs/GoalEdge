"""Daily background refresher for the Flashscore fixture source.

The requirement is that real matches — with their correct dates, kick-off times
and results — are fetched **every day**, not only when someone remembers to hit
the admin endpoint. This module runs that refresh on a timer inside the running
app, so a long-lived process stays current without an external cron.

Design notes
------------
* **No new dependency.** A tiny asyncio loop is enough; pulling in a scheduler
  package for one job would add a moving part for no gain.
* **Never breaks the request path.** The job runs in its own task and swallows
  its own failures into a log line, so a feed outage cannot take the app down.
* **Catches up after a restart.** Rather than sleeping a full interval before
  the first run, it refreshes immediately on boot and then every ``interval``.
* **Refreshes a window, not just today.** Results appear after a match ends, so
  each run re-pulls today plus the last few days to settle them.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .config import settings
from .database import SessionLocal
from .models import Fixture
from .sync import sync_day, sync_forward, sync_recent

log = logging.getLogger("goaledge.refresh")

#: Seconds between full fixture-window refreshes. A separate, narrower refresh
#: keeps today's scores current while a match is around kick-off or in play.
DEFAULT_INTERVAL = 30 * 60
#: While a match is in play, update today's scores more often than the full
#: fixture window. This avoids re-fetching the whole schedule for every score.
LIVE_SCORE_REFRESH_SECONDS = 15
#: How long to let the app serve requests before the first refresh runs. The
#: refresh takes a write lock that SQLite holds against readers, so starting it
#: during boot made the first page load wait for the whole refresh.
DEFAULT_STARTUP_DELAY = 20


class DailyRefresher:
    """A cancellable asyncio task that refreshes real fixtures on a timer."""

    def __init__(
        self,
        interval_seconds: int = DEFAULT_INTERVAL,
        lookback_days: int = 2,
        forward_days: int = 7,
        startup_delay: int = DEFAULT_STARTUP_DELAY,
    ):
        self.interval = interval_seconds
        #: Seconds to wait before the FIRST refresh, so boot is not blocked by it.
        self.startup_delay = startup_delay
        self.lookback_days = lookback_days
        #: How many days AHEAD to sync, so tomorrow's card exists today. The feed
        #: only publishes about a week forward, so this is a week rather than the
        #: whole season.
        self.forward_days = forward_days
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.last_run: datetime | None = None
        self.last_result: dict | None = None
        self.runs = 0
        self.failures = 0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())
        log.info(
            "flashscore refresher: started (every %ss, lookback %sd)",
            self.interval,
            self.lookback_days,
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 - shutdown must not raise
            pass
        self._task = None
        log.info("flashscore refresher: stopped")

    # -- the loop ----------------------------------------------------------

    async def _loop(self) -> None:
        # Let the app finish starting before the first refresh. The refresh opens
        # a write transaction, and SQLite serialises writers against readers -- so
        # a run that starts the instant the server is up blocks every API request
        # for as long as it lasts, and the first page load sits on its spinner.
        # A short delay costs nothing and keeps boot responsive.
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=self.startup_delay)
        except asyncio.TimeoutError:
            pass
        next_full_refresh = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_full_refresh:
                await self.run_once()
                next_full_refresh = time.monotonic() + self.interval
                continue
            try:
                # Check for active matches between full fixture refreshes. The
                # check is cheap; the day feed is fetched only near kick-off or in play.
                wait_seconds = min(
                    LIVE_SCORE_REFRESH_SECONDS,
                    next_full_refresh - now,
                )
                await asyncio.wait_for(self._stop.wait(), timeout=wait_seconds)
            except asyncio.TimeoutError:
                await self.refresh_live_scores()

    async def run_once(self) -> dict:
        """Refresh in a worker thread so the event loop is never blocked."""
        try:
            result = await asyncio.to_thread(self._sync_blocking)
            self.last_run = datetime.now(timezone.utc)
            self.last_result = result
            self.runs += 1
            if result.get("error"):
                self.failures += 1
                log.warning("flashscore refresher: %s", result["error"])
            else:
                log.info("flashscore refresher: %s fixture(s) refreshed", result.get("updated", 0))
            return result
        except Exception as exc:  # noqa: BLE001 - a bad run must never kill the loop
            self.failures += 1
            log.exception("flashscore refresher failed")
            return {"error": str(exc)}

    async def refresh_live_scores(self) -> dict | None:
        """Refresh today's scores when a fixture is near kick-off or in play."""
        try:
            result = await asyncio.to_thread(self._sync_live_scores_blocking)
        except Exception as exc:  # noqa: BLE001 - a failed score refresh must not kill the loop
            self.failures += 1
            log.exception("flashscore live-score refresh failed")
            return {"error": str(exc)}
        if result is None:
            return None
        if result.get("error"):
            self.failures += 1
            log.warning("flashscore live-score refresh: %s", result["error"])
        else:
            log.info(
                "flashscore live-score refresh: %s fixture(s) updated",
                result.get("updated", 0),
            )
        return result

    def _sync_blocking(self) -> dict:
        db = SessionLocal()
        try:
            # Only the Flashscore match feeds may be fetched. Do not query
            # external odds, injury or AI providers during scheduled refreshes.
            outcomes = sync_recent(db, days=self.lookback_days, history=False)
            forward = sync_forward(db, days=self.forward_days)
            outcomes = outcomes + forward
        finally:
            db.close()
        return {
            "runs": [
                {"date": o.date, "created": o.created, "updated": o.updated, "error": o.error}
                for o in outcomes
            ],
            "created": sum(o.created for o in outcomes),
            "updated": sum(o.updated for o in outcomes),
            "error": next((o.error for o in outcomes if o.error), None),
        }

    def _sync_live_scores_blocking(self) -> dict | None:
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            active_fixture = db.scalar(
                select(Fixture.id)
                .where(
                    Fixture.status.in_(("scheduled", "live")),
                    Fixture.kickoff >= now - timedelta(minutes=120),
                    Fixture.kickoff <= now + timedelta(minutes=15),
                )
                .limit(1)
            )
            if active_fixture is None:
                return None

            outcome = sync_day(db, "today")
            return {"updated": outcome.updated, "error": outcome.error}
        finally:
            db.close()

    # -- introspection -----------------------------------------------------

    def status(self) -> dict:
        return {
            "running": self._task is not None and not self._task.done(),
            "interval_seconds": self.interval,
            "startup_delay": self.startup_delay,
            "lookback_days": self.lookback_days,
            "forward_days": self.forward_days,
            "runs": self.runs,
            "failures": self.failures,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_result": self.last_result,
        }


#: Process-wide refresher, started and stopped by the app lifespan.
refresher = DailyRefresher(
    interval_seconds=int(getattr(settings, "flashscore_refresh_seconds", DEFAULT_INTERVAL)),
    lookback_days=2,
    forward_days=int(getattr(settings, "flashscore_forward_days", 7)),
)
