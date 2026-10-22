"""Choose when to open the windows over a plan day.

A plan day runs from the end of quiet hours (wake-up) to the same time the
next morning, so an overnight opening belongs to the evening that starts it.
Windows are only opened or closed outside quiet hours.

The planner greedily adds up to ``max_openings`` openings, each time picking
the one that brings in the most fresh air (lowest average staleness, with a
small preference for openings that cost less heating or cooling), subject to:

* comfort: indoor temperature stays inside the configured band while open;
* rain: no opening while rain is likely;
* humidity: openings may add at most ``max_extra_hours_above_limit`` hours of
  indoor humidity above ``humidity_limit`` compared with keeping the house
  closed, and must not push the plan day's average humidity over the limit
  (or make it worse, if the closed house would already be over it);
* peak humidity: openings must not push indoor humidity above
  ``peak_humidity_limit`` at any moment the closed house would be below it;
* recovery: by the end of the evaluation period (the afternoon after the plan
  day), the house must hold no more moisture than the closed house would.
  Without this, each day's airings would leave the house a little wetter and
  the next day's budget would be judged from there, ratcheting up over weeks.

Humidity is judged against the closed house rather than in absolute terms
because the model's estimate of the closed house is its least certain part;
the difference an opening makes is much better determined.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Iterator, Sequence

from .house import (
    BUFFER_CAPACITY_RATIO,
    STEP,
    STEP_HOURS,
    HouseParameters,
    IndoorState,
    OutdoorStep,
    Trace,
    default_initial_state,
    simulate,
)
from .psychrometrics import dew_point, humidity_ratio_from_dew_point
from .weather import WeatherHour, WeatherSeries

# Humidity from an evening opening can linger past the plan day; count it too.
EVALUATION_TAIL = timedelta(hours=12)
SPIN_UP = timedelta(hours=72)
MIN_GAP_BETWEEN_OPENINGS = timedelta(hours=2)
CANDIDATE_DURATION_STEPS = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64)
ENERGY_WEIGHT = 0.01
MIN_IMPROVEMENT = 0.005
RAIN_MM_PER_HOUR = 0.3
# Allowed extra stored moisture at the end of the evaluation period, as a
# humidity ratio averaged over air and materials (about 0.5% RH at 75°F).
CARRYOVER_TOLERANCE = 0.0001
AFTERMATH = timedelta(hours=6)


@dataclass(frozen=True)
class PlanSettings:
    humidity_limit: float
    max_extra_hours_above_limit: float
    peak_humidity_limit: float
    open_min_indoor_temp_c: float
    open_max_indoor_temp_c: float
    max_openings: int
    min_opening_minutes: int
    rain_probability_limit: float
    quiet_start: time
    quiet_end: time


@dataclass(frozen=True)
class Opening:
    start: datetime
    end: datetime

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


@dataclass(frozen=True)
class OpeningDetail:
    opening: Opening
    outdoor_low_c: float
    outdoor_high_c: float
    outdoor_dew_point_c: float
    indoor_temp_at_close_c: float
    # Highest indoor humidity during the opening or the hours after it, and
    # what it would have been at that moment with the house kept closed.
    peak_humidity: float
    closed_humidity_at_peak: float
    # When humidity drops back under the limit, if that happens soon after closing.
    back_under_limit_at: datetime | None
    dries_house: bool


@dataclass(frozen=True)
class Plan:
    window_start: datetime
    window_end: datetime
    openings: tuple[Opening, ...]
    details: tuple[OpeningDetail, ...]
    # Why nothing new could be recommended: "humidity", "temperature", "rain",
    # "max_openings", "no_benefit" or "no_time".
    blocked_by: str | None
    outdoor_high_c: float
    outdoor_low_c: float
    outdoor_dew_point_low_c: float
    outdoor_dew_point_high_c: float
    # Outdoor range over the part of the day still being decided.
    outlook_high_c: float
    outlook_low_c: float
    hours_above_limit: float
    baseline_hours_above_limit: float
    mean_humidity: float
    baseline_mean_humidity: float
    end_state: IndoorState

    def openings_after(self, moment: datetime) -> tuple[Opening, ...]:
        return tuple(opening for opening in self.openings if opening.end > moment)


def is_quiet(moment: datetime, settings: PlanSettings) -> bool:
    clock = moment.time()
    if settings.quiet_start <= settings.quiet_end:
        return settings.quiet_start <= clock < settings.quiet_end
    return clock >= settings.quiet_start or clock < settings.quiet_end


def plan_day_start(moment: datetime, settings: PlanSettings) -> datetime:
    """Start (wake-up time) of the plan day containing ``moment``."""
    start = moment.replace(
        hour=settings.quiet_end.hour,
        minute=settings.quiet_end.minute,
        second=0,
        microsecond=0,
    )
    if start > moment:
        start = add_local_days(start, -1)
    return start


def add_local_days(moment: datetime, days: int) -> datetime:
    """Same wall-clock time ``days`` later."""
    return (moment.replace(tzinfo=None) + timedelta(days=days)).replace(tzinfo=moment.tzinfo)


def build_outdoor_steps(
    series: WeatherSeries,
    start: datetime,
    end: datetime,
    rain_probability_limit: float,
) -> list[OutdoorStep]:
    """Interpolate hourly weather onto the model's time step over [start, end).

    Steps advance in local wall-clock time, so a DST change stretches or skips
    one hour; that is well within the model's precision.
    """
    hours = series.hours
    if hours[0].time > start or hours[-1].time < end - timedelta(hours=1):
        raise ValueError("Weather data does not cover the requested planning period")

    steps = []
    index = 0
    moment = start
    while moment < end:
        while index + 1 < len(hours) and hours[index + 1].time <= moment:
            index += 1
        current = hours[index]
        following = hours[index + 1] if index + 1 < len(hours) else current
        span = (following.time - current.time).total_seconds()
        fraction = (moment - current.time).total_seconds() / span if span > 0 else 0.0
        ratio_now = humidity_ratio_from_dew_point(current.dew_point_c)
        ratio = ratio_now + (humidity_ratio_from_dew_point(following.dew_point_c) - ratio_now) * fraction
        steps.append(
            OutdoorStep(
                time=moment,
                temperature_c=current.temperature_c + (following.temperature_c - current.temperature_c) * fraction,
                dew_point_c=dew_point(ratio),
                humidity_ratio=ratio,
                rain_likely=_rain_likely(current, rain_probability_limit),
            )
        )
        moment += STEP
    return steps


def estimate_indoor_state(
    params: HouseParameters,
    series: WeatherSeries,
    at: datetime,
    rain_probability_limit: float,
    assumed_openings: Sequence[Opening] = (),
) -> IndoorState:
    """Estimate indoor conditions at ``at`` by running the model over the preceding days.

    This stands in for an indoor sensor. It assumes the windows were closed
    apart from ``assumed_openings`` (normally the openings previously recommended).
    """
    start = at - SPIN_UP
    while start < series.hours[0].time:
        start += STEP
    if start >= at:
        return default_initial_state(params, series.hours[0].temperature_c)
    steps = build_outdoor_steps(series, start, at, rain_probability_limit)
    initial = default_initial_state(params, steps[0].temperature_c)
    return simulate(params, initial, steps, _open_flags(steps, assumed_openings)).final_state


def plan_day(
    params: HouseParameters,
    settings: PlanSettings,
    series: WeatherSeries,
    *,
    initial_state: IndoorState,
    window_start: datetime,
    decide_from: datetime | None = None,
    earlier_openings: Sequence[Opening] = (),
) -> Plan:
    """Plan the day starting at ``window_start``, given ``initial_state`` at that moment.

    For a replan later in the day, ``earlier_openings`` are the openings
    recommended earlier and are assumed to have been followed. Openings that
    finished before ``decide_from`` are kept as they were; one still in
    progress keeps its start but gets a fresh closing time; new openings are
    only chosen from ``decide_from`` on.
    """
    window_end = add_local_days(window_start, 1)
    steps = build_outdoor_steps(series, window_start, window_end + EVALUATION_TAIL, settings.rain_probability_limit)
    day_steps = sum(1 for step in steps if step.time < window_end)
    decide_index = _index_of(steps, max(decide_from or window_start, window_start))
    decide_time = _time_at(steps, decide_index)

    decided: list[Opening] = []
    in_progress: Opening | None = None
    for opening in sorted(earlier_openings, key=lambda item: item.start):
        if opening.end <= window_start or opening.start >= decide_time:
            continue  # Outside this day, or not started yet and so up for re-planning.
        if opening.end <= decide_time:
            decided.append(opening)
        else:
            in_progress = opening

    evaluator = _Evaluator(params, settings, steps, day_steps, initial_state)
    baseline = evaluator.evaluate([False] * len(steps))
    evaluator.peak_ceiling = [max(settings.peak_humidity_limit, value) for value in baseline.trace.relative_humidity]
    current = evaluator.evaluate(_open_flags(steps, decided))
    chosen = list(decided)

    if in_progress is not None:
        start_index = _index_of(steps, in_progress.start)
        options = list(
            _openings_from(steps, day_steps, start_index, decide_index, chosen, settings, already_open=True)
        )
        best = _best(evaluator, steps, chosen, options, baseline, comfort_from=decide_index)[0]
        if best is None:
            close_now = Opening(start=in_progress.start, end=decide_time)
            best = (evaluator.evaluate(_open_flags(steps, [*chosen, close_now])), close_now)
        current, opening = best
        chosen.append(opening)

    first_failures: dict[str, int] | None = None
    new_count = 0
    while len(chosen) < settings.max_openings:
        candidates = [
            opening
            for start_index in range(decide_index, day_steps)
            for opening in _openings_from(steps, day_steps, start_index, start_index + 1, chosen, settings)
        ]
        best, failures = _best(evaluator, steps, chosen, candidates, baseline)
        if first_failures is None:
            first_failures = failures
        if best is None or best[0].score > current.score - MIN_IMPROVEMENT:
            break
        current, opening = best
        chosen.append(opening)
        new_count += 1

    blocked_by = None
    if new_count == 0 and in_progress is None:
        if first_failures is None:
            blocked_by = "max_openings"
        else:
            blocked_by = _blocked_reason(first_failures, steps, decide_index, day_steps, settings)

    chosen.sort(key=lambda item: item.start)
    flags = _open_flags(steps, chosen)
    day = steps[:day_steps]
    outlook = steps[decide_index:day_steps] or day[-1:]
    return Plan(
        window_start=window_start,
        window_end=window_end,
        openings=tuple(chosen),
        details=tuple(_describe(opening, steps, current.trace, baseline.trace, settings) for opening in chosen),
        blocked_by=blocked_by,
        outdoor_high_c=max(step.temperature_c for step in day),
        outdoor_low_c=min(step.temperature_c for step in day),
        outdoor_dew_point_low_c=min(step.dew_point_c for step in day),
        outdoor_dew_point_high_c=max(step.dew_point_c for step in day),
        outlook_high_c=max(step.temperature_c for step in outlook),
        outlook_low_c=min(step.temperature_c for step in outlook),
        hours_above_limit=current.hours_above,
        baseline_hours_above_limit=baseline.hours_above,
        mean_humidity=current.mean_humidity,
        baseline_mean_humidity=baseline.mean_humidity,
        end_state=simulate(params, initial_state, day, flags[:day_steps]).final_state,
    )


@dataclass
class _Evaluation:
    trace: Trace
    score: float
    hours_above: float
    mean_humidity: float
    # How far humidity goes over the peak limit where the closed house would not.
    peak_excess: float
    stored_moisture: float


class _Evaluator:
    def __init__(
        self,
        params: HouseParameters,
        settings: PlanSettings,
        steps: list[OutdoorStep],
        day_steps: int,
        initial_state: IndoorState,
    ) -> None:
        self.params = params
        self.settings = settings
        self.steps = steps
        self.day_steps = max(day_steps, 1)
        self.initial_state = initial_state
        self.peak_ceiling: list[float] | None = None

    def evaluate(self, flags: list[bool]) -> _Evaluation:
        trace = simulate(self.params, self.initial_state, self.steps, flags)
        humidity = trace.relative_humidity
        limit = self.settings.humidity_limit
        day = self.day_steps
        return _Evaluation(
            trace=trace,
            score=sum(trace.staleness[:day]) / day + ENERGY_WEIGHT * sum(trace.hvac_load),
            hours_above=sum(1 for value in humidity if value > limit) * STEP_HOURS,
            mean_humidity=sum(humidity[:day]) / day,
            peak_excess=(
                max(value - ceiling for value, ceiling in zip(humidity, self.peak_ceiling))
                if self.peak_ceiling is not None
                else 0.0
            ),
            stored_moisture=_stored_moisture(trace.final_state),
        )

    def comfortable(self, trace: Trace, start_index: int, end_index: int) -> bool:
        low = self.settings.open_min_indoor_temp_c
        high = self.settings.open_max_indoor_temp_c
        return all(low <= value <= high for value in trace.temperature_c[start_index:end_index])


def _best(
    evaluator: _Evaluator,
    steps: list[OutdoorStep],
    chosen: Sequence[Opening],
    candidates: Sequence[Opening],
    baseline: _Evaluation,
    comfort_from: int | None = None,
) -> tuple[tuple[_Evaluation, Opening] | None, dict[str, int]]:
    """Best feasible candidate (lowest score) plus a count of why the others failed."""
    best: tuple[_Evaluation, Opening] | None = None
    failures: dict[str, int] = {}
    uncomfortable_starts: set[datetime] = set()
    settings = evaluator.settings
    for opening in candidates:
        if opening.start in uncomfortable_starts:
            continue
        result = evaluator.evaluate(_open_flags(steps, [*chosen, opening]))
        start_index = comfort_from if comfort_from is not None else _index_of(steps, opening.start)
        if not evaluator.comfortable(result.trace, start_index, _index_of(steps, opening.end)):
            # Candidates from one start come shortest first, so longer ones fail too.
            uncomfortable_starts.add(opening.start)
            failures["temperature"] = failures.get("temperature", 0) + 1
            continue
        if (
            result.hours_above - baseline.hours_above > settings.max_extra_hours_above_limit + 1e-9
            or result.mean_humidity > max(settings.humidity_limit, baseline.mean_humidity) + 1e-9
            or result.peak_excess > 1e-9
            or result.stored_moisture > baseline.stored_moisture + CARRYOVER_TOLERANCE
        ):
            failures["humidity"] = failures.get("humidity", 0) + 1
            continue
        if best is None or result.score < best[0].score:
            best = (result, opening)
    return best, failures


def _openings_from(
    steps: list[OutdoorStep],
    day_steps: int,
    start_index: int,
    min_end_index: int,
    chosen: Sequence[Opening],
    settings: PlanSettings,
    *,
    already_open: bool = False,
) -> Iterator[Opening]:
    """Valid openings starting at ``start_index`` and ending no earlier than ``min_end_index``, shortest first.

    ``already_open`` is for an opening in progress: its start is in the past,
    so only its closing time is being chosen.
    """
    start = steps[start_index].time
    if not already_open and (is_quiet(start, settings) or steps[start_index].rain_likely):
        return
    if _overlaps(start, start, chosen):
        return

    min_steps = 1 if already_open else max(1, -(-settings.min_opening_minutes // int(STEP.total_seconds() // 60)))
    ends = {start_index + duration for duration in CANDIDATE_DURATION_STEPS if duration >= min_steps}
    bedtime = next((i for i in range(start_index + 1, day_steps) if is_quiet(steps[i].time, settings)), None)
    if bedtime is not None and bedtime - start_index >= min_steps:
        ends.add(bedtime)
    if day_steps - start_index >= min_steps:
        ends.add(day_steps)
    if already_open:
        ends.add(min_end_index)  # Close now.

    for end_index in sorted(ends):
        if end_index < min_end_index or end_index <= start_index:
            continue
        if end_index > day_steps:
            break
        first_undecided = min_end_index if already_open else start_index
        if any(step.rain_likely for step in steps[first_undecided:end_index]):
            break
        end = _time_at(steps, end_index)
        runs_overnight = bedtime is not None and end_index > bedtime
        if runs_overnight and end_index != day_steps:
            continue  # Nobody is awake to close it, so it stays open until wake-up.
        if is_quiet(end, settings) and end_index not in (bedtime, day_steps):
            continue
        if _overlaps(start, end, chosen):
            break
        yield Opening(start=start, end=end)


def _stored_moisture(state: IndoorState) -> float:
    return (state.air_humidity_ratio + BUFFER_CAPACITY_RATIO * state.buffer_humidity_ratio) / (
        1.0 + BUFFER_CAPACITY_RATIO
    )


def _overlaps(start: datetime, end: datetime, chosen: Sequence[Opening]) -> bool:
    return any(
        start < opening.end + MIN_GAP_BETWEEN_OPENINGS and end > opening.start - MIN_GAP_BETWEEN_OPENINGS
        for opening in chosen
    )


def _blocked_reason(
    failures: dict[str, int],
    steps: list[OutdoorStep],
    decide_index: int,
    day_steps: int,
    settings: PlanSettings,
) -> str:
    # If even comfortable times fail on humidity, humidity is the reason worth reporting.
    for reason in ("humidity", "temperature"):
        if failures.get(reason):
            return reason
    awake = [step for step in steps[decide_index:day_steps] if not is_quiet(step.time, settings)]
    if not awake:
        return "no_time"
    if all(step.rain_likely for step in awake):
        return "rain"
    return "no_benefit"


def _describe(
    opening: Opening,
    steps: list[OutdoorStep],
    trace: Trace,
    closed: Trace,
    settings: PlanSettings,
) -> OpeningDetail:
    start = _index_of(steps, opening.start)
    end = max(start + 1, _index_of(steps, opening.end))
    during = steps[start:end]
    ratios = [step.humidity_ratio for step in during]
    humidity = trace.relative_humidity
    aftermath_end = min(len(steps), end + int(AFTERMATH / STEP))
    peak = max(humidity[start:aftermath_end])
    peak_index = humidity.index(peak, start, aftermath_end)
    back_under = next(
        (steps[i].time for i in range(peak_index, aftermath_end) if humidity[i] <= settings.humidity_limit),
        None,
    )
    return OpeningDetail(
        opening=opening,
        outdoor_low_c=min(step.temperature_c for step in during),
        outdoor_high_c=max(step.temperature_c for step in during),
        outdoor_dew_point_c=dew_point(sum(ratios) / len(ratios)),
        indoor_temp_at_close_c=trace.temperature_c[end - 1],
        peak_humidity=peak,
        closed_humidity_at_peak=closed.relative_humidity[peak_index],
        back_under_limit_at=back_under if peak > settings.humidity_limit else None,
        dries_house=humidity[end - 1] < closed.relative_humidity[end - 1] - 5,
    )


def _open_flags(steps: Sequence[OutdoorStep], openings: Sequence[Opening]) -> list[bool]:
    return [any(opening.start <= step.time < opening.end for opening in openings) for step in steps]


def _index_of(steps: Sequence[OutdoorStep], moment: datetime) -> int:
    for index, step in enumerate(steps):
        if step.time >= moment:
            return index
    return len(steps)


def _time_at(steps: Sequence[OutdoorStep], index: int) -> datetime:
    return steps[index].time if index < len(steps) else steps[-1].time + STEP


def _rain_likely(hour: WeatherHour, rain_probability_limit: float) -> bool:
    if hour.precipitation_probability is not None:
        return hour.precipitation_probability >= rain_probability_limit
    return hour.precipitation_mm >= RAIN_MM_PER_HOUR
