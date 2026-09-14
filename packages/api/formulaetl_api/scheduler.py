"""Lightweight cron pipeline scheduler (Community self-hosted).

Persists schedules next to the pipeline store. A background poll loop fires
``POST``-equivalent runs when due. Cloud HA scheduling is an Enterprise/paid
direction — not claimed in this Community build.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


Clock = Callable[[], float]
RunCallback = Callable[[str], Any]


@dataclass
class ScheduleSpec:
    pipeline_id: str
    enabled: bool = False
    cron: str = "*/5 * * * *"  # every 5 minutes
    timezone: str = "UTC"
    next_run_at: float | None = None  # epoch seconds
    last_run_at: float | None = None
    last_run_id: str | None = None
    last_status: str | None = None
    updated_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduleSpec":
        return cls(
            pipeline_id=str(data["pipeline_id"]),
            enabled=bool(data.get("enabled", False)),
            cron=str(data.get("cron") or "*/5 * * * *"),
            timezone=str(data.get("timezone") or "UTC"),
            next_run_at=data.get("next_run_at"),
            last_run_at=data.get("last_run_at"),
            last_run_id=data.get("last_run_id"),
            last_status=data.get("last_status"),
            updated_at=data.get("updated_at"),
        )


def _parse_field(field_s: str, min_v: int, max_v: int) -> set[int]:
    """Parse one cron field into a set of allowed ints."""
    field_s = field_s.strip()
    if field_s == "*":
        return set(range(min_v, max_v + 1))
    out: set[int] = set()
    for part in field_s.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            part = base
        if part == "*":
            out.update(range(min_v, max_v + 1, step))
        elif "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1, step))
        else:
            val = int(part)
            if step > 1:
                out.update(range(val, max_v + 1, step))
            else:
                out.add(val)
    return {v for v in out if min_v <= v <= max_v}


_CRON_RE = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$")


def cron_matches(cron: str, dt: datetime) -> bool:
    """Return True if 5-field cron matches the given local datetime (minute resolution)."""
    m = _CRON_RE.match(cron.strip())
    if not m:
        raise ValueError(f"Invalid cron expression (need 5 fields): {cron!r}")
    minute, hour, day, month, weekday = m.groups()
    mins = _parse_field(minute, 0, 59)
    hours = _parse_field(hour, 0, 23)
    days = _parse_field(day, 1, 31)
    months = _parse_field(month, 1, 12)
    # cron weekday: 0-6 or 7 = Sunday; Python weekday() is Mon=0..Sun=6
    wdays_raw = _parse_field(weekday, 0, 7)
    wdays = set()
    for w in wdays_raw:
        if w == 7:
            wdays.add(6)  # Sunday as Python
        elif w == 0:
            wdays.add(6)  # Sunday
        else:
            # cron 1=Mon .. 6=Sat → Python 0=Mon .. 5=Sat
            wdays.add(w - 1 if w >= 1 else w)

    if dt.minute not in mins:
        return False
    if dt.hour not in hours:
        return False
    if dt.month not in months:
        return False
    # day-of-month OR day-of-week (classic cron OR when either is *)
    day_star = day == "*"
    dow_star = weekday == "*"
    day_ok = dt.day in days
    dow_ok = dt.weekday() in wdays
    if day_star and dow_star:
        return True
    if day_star:
        return dow_ok
    if dow_star:
        return day_ok
    return day_ok or dow_ok


def next_cron_fire(
    cron: str,
    after_epoch: float,
    tz_name: str = "UTC",
    *,
    max_minutes: int = 60 * 24 * 370,
) -> float:
    """Return next fire time (epoch) strictly after ``after_epoch`` (minute grid)."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    # Start at the next whole minute after after_epoch
    start = int(after_epoch) + 60 - (int(after_epoch) % 60)
    for i in range(max_minutes):
        epoch = start + i * 60
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(tz)
        if cron_matches(cron, dt):
            return float(epoch)
    raise ValueError(f"No cron match within {max_minutes} minutes for {cron!r}")


class ScheduleStore:
    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.Lock()

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, pipeline_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in pipeline_id)
        return self.root / f"{safe}.json"

    def get(self, pipeline_id: str) -> ScheduleSpec | None:
        path = self._path(pipeline_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ScheduleSpec.from_dict(data)

    def save(self, spec: ScheduleSpec) -> None:
        self.ensure()
        with self._lock:
            self._path(spec.pipeline_id).write_text(
                json.dumps(spec.to_dict(), indent=2), encoding="utf-8"
            )

    def list(self) -> list[ScheduleSpec]:
        self.ensure()
        out: list[ScheduleSpec] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                out.append(ScheduleSpec.from_dict(data))
            except Exception:
                continue
        return out

    def delete(self, pipeline_id: str) -> bool:
        path = self._path(pipeline_id)
        if path.exists():
            path.unlink()
            return True
        return False


class PipelineScheduler:
    """Background poller that fires due schedules via ``run_callback(pipeline_id)``."""

    def __init__(
        self,
        store: ScheduleStore,
        run_callback: RunCallback,
        *,
        clock: Clock | None = None,
        poll_interval_sec: float = 5.0,
    ):
        self.store = store
        self.run_callback = run_callback
        self.clock = clock or time.time
        self.poll_interval_sec = poll_interval_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fire_lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="formulaetl-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def upsert(
        self,
        pipeline_id: str,
        *,
        enabled: bool,
        cron: str,
        timezone: str = "UTC",
    ) -> ScheduleSpec:
        # Validate cron
        now = self.clock()
        next_run = next_cron_fire(cron, now, timezone) if enabled else None
        existing = self.store.get(pipeline_id)
        spec = ScheduleSpec(
            pipeline_id=pipeline_id,
            enabled=enabled,
            cron=cron,
            timezone=timezone,
            next_run_at=next_run,
            last_run_at=existing.last_run_at if existing else None,
            last_run_id=existing.last_run_id if existing else None,
            last_status=existing.last_status if existing else None,
            updated_at=now,
        )
        self.store.save(spec)
        return spec

    def tick(self) -> list[str]:
        """Check due schedules once; return pipeline ids that were fired. Used by tests."""
        fired: list[str] = []
        now = self.clock()
        for spec in self.store.list():
            if not spec.enabled:
                continue
            due_at = spec.next_run_at
            if due_at is None:
                # Compute next if missing
                try:
                    spec.next_run_at = next_cron_fire(spec.cron, now - 1, spec.timezone)
                    self.store.save(spec)
                except ValueError:
                    continue
                due_at = spec.next_run_at
            if due_at is None or due_at > now:
                continue
            with self._fire_lock:
                # Re-read to avoid double fire under concurrency
                fresh = self.store.get(spec.pipeline_id) or spec
                if not fresh.enabled or (fresh.next_run_at or 0) > now:
                    continue
                try:
                    result = self.run_callback(fresh.pipeline_id)
                    run_id = None
                    status = "triggered"
                    if isinstance(result, dict):
                        run_id = result.get("run_id")
                        status = str(result.get("status") or status)
                    elif hasattr(result, "run_id"):
                        run_id = getattr(result, "run_id", None)
                        status = str(getattr(result, "status", status))
                    fresh.last_run_at = now
                    fresh.last_run_id = str(run_id) if run_id else None
                    fresh.last_status = status
                    fresh.next_run_at = next_cron_fire(fresh.cron, now, fresh.timezone)
                    self.store.save(fresh)
                    fired.append(fresh.pipeline_id)
                except Exception as exc:
                    fresh.last_run_at = now
                    fresh.last_status = f"error: {exc}"
                    try:
                        fresh.next_run_at = next_cron_fire(fresh.cron, now, fresh.timezone)
                    except ValueError:
                        fresh.next_run_at = now + 3600
                    self.store.save(fresh)
        return fired

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                pass
            self._stop.wait(self.poll_interval_sec)
