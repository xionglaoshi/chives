"""Clocks injected into the engine; the only place that reads the system time."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from .models import CN_TZ


class RealClock:
    def __init__(self, stop: threading.Event | None = None) -> None:
        self._stop = stop

    def now(self) -> datetime:
        return datetime.now(CN_TZ)

    def sleep(self, seconds: float) -> None:
        seconds = max(0.0, float(seconds))
        if self._stop is not None:
            self._stop.wait(seconds)
            return
        time.sleep(seconds)


class SimulatedClock:
    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("simulated clock needs a timezone-aware start")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now += timedelta(seconds=max(0.0, float(seconds)))
