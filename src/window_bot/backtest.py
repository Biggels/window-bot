"""Replay past weather through the planner to see what it would have recommended.

Each day is planned at wake-up with that day's actual weather standing in for
the forecast, and the plan is assumed to have been followed before planning
the next day.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .config import Config
from .planner import SPIN_UP, Plan, estimate_indoor_state, plan_day
from .weather import OpenMeteoClient, WeatherSeries


@dataclass(frozen=True)
class DayResult:
    day: date
    plan: Plan

    @property
    def open_hours(self) -> float:
        return sum(opening.duration.total_seconds() for opening in self.plan.openings) / 3600.0

    @property
    def peak_humidity(self) -> float | None:
        return max((detail.peak_humidity for detail in self.plan.details), default=None)

    @property
    def extra_hours_above_limit(self) -> float:
        return self.plan.hours_above_limit - self.plan.baseline_hours_above_limit


def fetch_history(config: Config, start: date, end: date, client: OpenMeteoClient | None = None) -> WeatherSeries:
    client = client or OpenMeteoClient(timeout_seconds=max(config.request_timeout_seconds, 60.0))
    # Extra days before for the indoor spin-up, and after for the last day's overnight and tail.
    return client.fetch_history(
        latitude=config.latitude,
        longitude=config.longitude,
        start=start - SPIN_UP - timedelta(days=1),
        end=end + timedelta(days=2),
    )


def run_backtest(config: Config, series: WeatherSeries, start: date, end: date) -> list[DayResult]:
    wake = config.plan.quiet_end
    first = datetime.combine(start, time(wake.hour, wake.minute), tzinfo=series.timezone)
    state = estimate_indoor_state(config.house, series, first, config.plan.rain_probability_limit)
    results = []
    day = start
    while day <= end:
        window_start = datetime.combine(day, time(wake.hour, wake.minute), tzinfo=series.timezone)
        plan = plan_day(config.house, config.plan, series, initial_state=state, window_start=window_start)
        results.append(DayResult(day=day, plan=plan))
        state = plan.end_state
        day += timedelta(days=1)
    return results


def summarize(results: list[DayResult]) -> str:
    by_month: dict[str, list[DayResult]] = defaultdict(list)
    for result in results:
        by_month[result.day.strftime("%Y-%m")].append(result)

    lines = [
        "month    days  days-open  open-h/day  openings  max-extra-h>limit  mean-RH (closed)  peak-RH",
    ]
    for month, days in sorted(by_month.items()):
        peaks = [day.peak_humidity for day in days if day.peak_humidity is not None]
        opened = [day for day in days if day.plan.openings]
        lines.append(
            f"{month}  {len(days):>4}  {len(opened):>9}  {sum(d.open_hours for d in days) / len(days):>10.1f}"
            f"  {sum(len(d.plan.openings) for d in days):>8}"
            f"  {max(d.extra_hours_above_limit for d in days):>17.1f}"
            f"  {sum(d.plan.mean_humidity for d in days) / len(days):>6.0f}%"
            f"({sum(d.plan.baseline_mean_humidity for d in days) / len(days):.0f}%)"
            f"  {max(peaks) if peaks else float('nan'):>8.0f}%"
        )
    blocked: dict[str, int] = defaultdict(int)
    for result in results:
        if not result.plan.openings:
            blocked[result.plan.blocked_by or "unknown"] += 1
    if blocked:
        lines.append("Closed-all-day reasons: " + ", ".join(f"{reason} {count}" for reason, count in sorted(blocked.items())))
    return "\n".join(lines)
