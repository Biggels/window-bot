from __future__ import annotations

from datetime import datetime, time, timedelta
import unittest

from window_bot.house import IndoorState
from window_bot.planner import (
    Opening,
    add_local_days,
    build_outdoor_steps,
    estimate_indoor_state,
    is_quiet,
    plan_day,
    plan_day_start,
)
from window_bot.psychrometrics import fahrenheit_to_celsius

from helpers import TZ, diurnal, house, plan_settings, series

DAY = datetime(2026, 5, 10, 5, 0, tzinfo=TZ)
HISTORY_START = DAY - timedelta(days=4)


def make_plan(weather, settings=None, **kwargs):
    settings = settings or plan_settings()
    initial = kwargs.pop("initial_state", None) or estimate_indoor_state(house(), weather, DAY, settings.rain_probability_limit)
    return plan_day(house(), settings, weather, initial_state=initial, window_start=DAY, **kwargs)


class PlanDayTests(unittest.TestCase):
    def test_mild_dry_day_opens_for_long_stretches(self) -> None:
        weather = series(HISTORY_START, temperature_f=diurnal(58, 74), dew_point_f=45)

        plan = make_plan(weather)

        self.assertTrue(plan.openings)
        self.assertGreaterEqual(sum((o.duration for o in plan.openings), timedelta()), timedelta(hours=6))
        self.assertIsNone(plan.blocked_by)

    def test_hot_muggy_day_stays_closed_for_humidity(self) -> None:
        weather = series(HISTORY_START, temperature_f=diurnal(76, 95), dew_point_f=76)

        plan = make_plan(weather)

        self.assertEqual(plan.openings, ())
        self.assertEqual(plan.blocked_by, "humidity")

    def test_rain_blocks_openings(self) -> None:
        weather = series(HISTORY_START, temperature_f=diurnal(58, 74), dew_point_f=45, rain_probability=90)

        plan = make_plan(weather)

        self.assertEqual(plan.openings, ())
        self.assertEqual(plan.blocked_by, "rain")

    def test_cold_day_is_blocked_by_temperature(self) -> None:
        weather = series(HISTORY_START, temperature_f=diurnal(20, 34), dew_point_f=10)

        plan = make_plan(weather)

        self.assertEqual(plan.openings, ())
        self.assertEqual(plan.blocked_by, "temperature")

    def test_openings_start_and_end_outside_quiet_hours(self) -> None:
        settings = plan_settings()
        weather = series(HISTORY_START, temperature_f=diurnal(62, 72), dew_point_f=45)

        plan = make_plan(weather, settings)

        self.assertTrue(plan.openings)
        for opening in plan.openings:
            self.assertFalse(is_quiet(opening.start, settings))
            self.assertTrue(
                not is_quiet(opening.end, settings)
                or opening.end.time() == settings.quiet_start
                or opening.end == plan.window_end
            )

    def test_overnight_opening_lasts_until_wake_up(self) -> None:
        # Warm nights, dry air: staying open overnight is comfortable.
        weather = series(HISTORY_START, temperature_f=diurnal(66, 72), dew_point_f=45)

        plan = make_plan(weather)

        overnight = [o for o in plan.openings if o.end.date() != o.start.date()]
        for opening in overnight:
            self.assertEqual(opening.end, plan.window_end)

    def test_openings_respect_minimum_length_and_count(self) -> None:
        settings = plan_settings(max_openings=2, min_opening_minutes=45)
        weather = series(HISTORY_START, temperature_f=diurnal(70, 90), dew_point_f=66)

        plan = make_plan(weather, settings)

        self.assertLessEqual(len(plan.openings), 2)
        for opening in plan.openings:
            self.assertGreaterEqual(opening.duration, timedelta(minutes=45))

    def test_humidity_budget_is_respected(self) -> None:
        settings = plan_settings(max_extra_hours_above_limit=1.0)
        weather = series(HISTORY_START, temperature_f=diurnal(70, 92), dew_point_f=67)

        plan = make_plan(weather, settings)

        self.assertLessEqual(plan.hours_above_limit - plan.baseline_hours_above_limit, 1.0 + 1e-9)
        self.assertLessEqual(plan.mean_humidity, max(60.0, plan.baseline_mean_humidity) + 1e-9)

    def test_humid_morning_gets_a_short_airing_when_ac_will_dry_the_house(self) -> None:
        # Typical Cary July day: dew point near 69°F all day, high in the 90s.
        weather = series(HISTORY_START, temperature_f=diurnal(72, 93), dew_point_f=68)

        plan = make_plan(weather)

        self.assertTrue(plan.openings)
        self.assertTrue(all(o.duration <= timedelta(hours=2) for o in plan.openings))
        for detail in plan.details:
            self.assertLessEqual(detail.peak_humidity, 75.0 + 1e-9)

    def test_replan_keeps_finished_openings_and_reschedules_the_rest(self) -> None:
        weather = series(HISTORY_START, temperature_f=diurnal(58, 74), dew_point_f=45)
        initial = estimate_indoor_state(house(), weather, DAY, 40.0)
        earlier = [
            Opening(DAY.replace(hour=6), DAY.replace(hour=7)),
            Opening(DAY.replace(hour=15), DAY.replace(hour=18)),
        ]

        plan = make_plan(weather, initial_state=initial, decide_from=DAY.replace(hour=12, minute=30), earlier_openings=earlier)

        self.assertIn(earlier[0], plan.openings)
        self.assertTrue(all(o.start >= DAY.replace(hour=12, minute=30) for o in plan.openings if o != earlier[0]))

    def test_replan_keeps_start_of_opening_in_progress(self) -> None:
        weather = series(HISTORY_START, temperature_f=diurnal(58, 74), dew_point_f=45)
        in_progress = Opening(DAY.replace(hour=10), DAY.replace(hour=16))

        plan = make_plan(weather, decide_from=DAY.replace(hour=12, minute=30), earlier_openings=[in_progress])

        starts = [opening.start for opening in plan.openings]
        self.assertIn(in_progress.start, starts)
        kept = next(o for o in plan.openings if o.start == in_progress.start)
        self.assertGreaterEqual(kept.end, DAY.replace(hour=12, minute=30))

    def test_late_replan_has_no_time_left(self) -> None:
        weather = series(HISTORY_START, temperature_f=diurnal(58, 74), dew_point_f=45)

        plan = make_plan(weather, decide_from=DAY.replace(hour=22))

        self.assertEqual(plan.openings, ())
        self.assertEqual(plan.blocked_by, "no_time")


class PlanningHelpersTests(unittest.TestCase):
    def test_quiet_hours_wrap_midnight(self) -> None:
        settings = plan_settings(quiet_start=time(21), quiet_end=time(5))

        self.assertTrue(is_quiet(DAY.replace(hour=23), settings))
        self.assertTrue(is_quiet(DAY.replace(hour=4, minute=59), settings))
        self.assertFalse(is_quiet(DAY.replace(hour=5), settings))
        self.assertFalse(is_quiet(DAY.replace(hour=20, minute=59), settings))

    def test_plan_day_start_rolls_back_before_wake_up(self) -> None:
        settings = plan_settings()

        self.assertEqual(plan_day_start(DAY.replace(hour=14), settings), DAY)
        self.assertEqual(plan_day_start(DAY.replace(hour=3), settings), DAY - timedelta(days=1))

    def test_add_local_days_keeps_wall_clock_across_dst(self) -> None:
        before_fall_back = datetime(2026, 10, 31, 5, 0, tzinfo=TZ)

        self.assertEqual(add_local_days(before_fall_back, 1).hour, 5)
        self.assertNotEqual(add_local_days(before_fall_back, 1).utcoffset(), before_fall_back.utcoffset())

    def test_outdoor_steps_interpolate_between_hours(self) -> None:
        weather = series(HISTORY_START, temperature_f=lambda moment: 60 + moment.hour, dew_point_f=40)

        steps = build_outdoor_steps(weather, DAY, DAY + timedelta(hours=1), 40.0)

        self.assertEqual(len(steps), 4)
        self.assertAlmostEqual(steps[2].temperature_c, fahrenheit_to_celsius(65.5), places=6)

    def test_estimate_indoor_state_reflects_recent_weather(self) -> None:
        humid = series(HISTORY_START, temperature_f=70, dew_point_f=66)
        dry = series(HISTORY_START, temperature_f=70, dew_point_f=35)

        humid_state = estimate_indoor_state(house(), humid, DAY, 40.0)
        dry_state = estimate_indoor_state(house(), dry, DAY, 40.0)

        self.assertIsInstance(humid_state, IndoorState)
        self.assertGreater(humid_state.relative_humidity, dry_state.relative_humidity + 20)
