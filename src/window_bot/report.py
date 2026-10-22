"""Turn plans into short Discord messages."""

from __future__ import annotations

from datetime import datetime, timedelta

from .planner import Opening, OpeningDetail, Plan, PlanSettings
from .psychrometrics import celsius_to_fahrenheit

LONG_OPENING = timedelta(hours=2)
# Only mention a humidity peak if opening raises it this much (percentage points) over staying closed.
NOTABLE_HUMIDITY_RISE = 3.0


class Formatter:
    def __init__(self, temperature_unit: str, settings: PlanSettings) -> None:
        self.fahrenheit = temperature_unit == "fahrenheit"
        self.settings = settings

    def temperature(self, value_c: float) -> str:
        value = celsius_to_fahrenheit(value_c) if self.fahrenheit else value_c
        return f"{value:.0f}°{'F' if self.fahrenheit else 'C'}"

    def temperature_range(self, low_c: float, high_c: float) -> str:
        low, high = self.temperature(low_c), self.temperature(high_c)
        return low if low == high else f"{low[:-2]}–{high}"


def morning_message(plan: Plan, fmt: Formatter) -> str:
    lines = [_headline("Window plan", plan.window_start)]
    lines += [_opening_line(detail, fmt) for detail in plan.details]
    lines.append(_rest_of_day(plan, plan.details, fmt))
    return "\n".join(lines)


def midday_message(plan: Plan, now: datetime, fmt: Formatter) -> str:
    remaining = [detail for detail in plan.details if detail.opening.end > now]
    lines = [_headline("Plan update", plan.window_start)]
    lines += [_opening_line(detail, fmt) for detail in remaining]
    lines.append(_rest_of_day(plan, remaining, fmt, rest_label="rest of the day"))
    return "\n".join(lines)


def evening_message(plan: Plan, now: datetime, tomorrow: Plan | None, fmt: Formatter) -> str:
    remaining = [detail for detail in plan.details if detail.opening.end > now]
    lines = [_headline("Tonight", plan.window_start)]
    lines += [_opening_line(detail, fmt) for detail in remaining]
    if not remaining:
        lines.append(f"Keep closed tonight — {_blocked_reason(plan, fmt)}.")
    if tomorrow is not None:
        lines.append(f"Tomorrow: {_compact_summary(tomorrow, fmt)}")
    return "\n".join(lines)


def plans_differ(old: tuple[Opening, ...], new: tuple[Opening, ...], tolerance: timedelta = timedelta(minutes=30)) -> bool:
    if len(old) != len(new):
        return True
    return any(
        abs(a.start - b.start) > tolerance or abs(a.end - b.end) > tolerance
        for a, b in zip(sorted(old, key=lambda o: o.start), sorted(new, key=lambda o: o.start))
    )


def _headline(title: str, day: datetime) -> str:
    return f"**{title} · {day:%a %b} {day.day}**"


def _opening_line(detail: OpeningDetail, fmt: Formatter) -> str:
    opening = detail.opening
    overnight = opening.end.date() != opening.start.date()
    times = _time_range(opening.start, opening.end)
    if overnight:
        action = "open overnight"
    elif opening.duration >= LONG_OPENING:
        action = "open"
    else:
        action = f"air out ({_duration(opening.duration)})"

    notes = [f"{fmt.temperature_range(detail.outdoor_low_c, detail.outdoor_high_c)}, dew point {fmt.temperature(detail.outdoor_dew_point_c)}"]
    limit = fmt.settings.humidity_limit
    if detail.peak_humidity > limit and detail.peak_humidity > detail.closed_humidity_at_peak + NOTABLE_HUMIDITY_RISE:
        humidity = f"indoor humidity peaks ~{detail.peak_humidity:.0f}%"
        if detail.back_under_limit_at is not None:
            humidity += f", under {limit:.0f}% by {_clock(detail.back_under_limit_at)}"
        notes.append(humidity)
    elif detail.dries_house:
        notes.append("dries the house out")
    if overnight or opening.duration >= LONG_OPENING:
        notes.append(f"house ~{fmt.temperature(detail.indoor_temp_at_close_c)} at close")
    return f"• {times} — {action}. " + "; ".join(notes) + "."


def _rest_of_day(plan: Plan, shown: list[OpeningDetail], fmt: Formatter, rest_label: str = "today") -> str:
    if not shown:
        return f"Keep closed {rest_label} — {_blocked_reason(plan, fmt)}."
    return f"Otherwise closed. High {fmt.temperature(plan.outdoor_high_c)}, low {fmt.temperature(plan.outdoor_low_c)}."


def _blocked_reason(plan: Plan, fmt: Formatter) -> str:
    dew = fmt.temperature_range(plan.outdoor_dew_point_low_c, plan.outdoor_dew_point_high_c)
    reason = plan.blocked_by
    if reason == "humidity":
        return f"too humid even for a short airing (dew point {dew})"
    if reason == "temperature":
        band_middle = (fmt.settings.open_min_indoor_temp_c + fmt.settings.open_max_indoor_temp_c) / 2
        if (plan.outlook_high_c + plan.outlook_low_c) / 2 >= band_middle:
            return f"too hot outside (up to {fmt.temperature(plan.outlook_high_c)})"
        return f"too cold outside (down to {fmt.temperature(plan.outlook_low_c)})"
    if reason == "rain":
        return "rain expected"
    if reason == "max_openings":
        return "today's openings are done"
    if reason == "no_time":
        return "no time left before quiet hours"
    return "nothing worth opening for"


def _compact_summary(plan: Plan, fmt: Formatter) -> str:
    if not plan.openings:
        return f"keep closed — {_blocked_reason(plan, fmt)}."
    parts = []
    for opening in plan.openings:
        label = "open" if opening.duration >= LONG_OPENING else "air out"
        parts.append(f"{label} {_time_range(opening.start, opening.end)}")
    return ", ".join(parts) + f" (high {fmt.temperature(plan.outdoor_high_c)})."


def _time_range(start: datetime, end: datetime) -> str:
    start_text, end_text = _clock(start), _clock(end)
    if start_text[-2:] == end_text[-2:] and start.date() == end.date():
        start_text = start_text[:-2]
    return f"{start_text}–{end_text}"


def _clock(moment: datetime) -> str:
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    minutes = f":{moment.minute:02d}" if moment.minute else ""
    return f"{hour}{minutes}{suffix}"


def _duration(value: timedelta) -> str:
    minutes = int(value.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} hr" if not rest else f"{hours}h{rest:02d}"
