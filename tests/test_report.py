from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from window_bot.house import IndoorState
from window_bot.planner import Opening, OpeningDetail, Plan
from window_bot.psychrometrics import fahrenheit_to_celsius as f2c
from window_bot.report import Formatter, evening_message, midday_message, morning_message, plans_differ

from helpers import TZ, plan_settings

DAY = datetime(2026, 7, 15, 5, 0, tzinfo=TZ)


def detail(start: datetime, end: datetime, **overrides) -> OpeningDetail:
    values = dict(
        opening=Opening(start, end),
        outdoor_low_c=f2c(79),
        outdoor_high_c=f2c(81),
        outdoor_dew_point_c=f2c(69),
        indoor_temp_at_close_c=f2c(76),
        peak_humidity=74.0,
        closed_humidity_at_peak=62.0,
        back_under_limit_at=end + timedelta(minutes=15),
        dries_house=False,
    )
    values.update(overrides)
    return OpeningDetail(**values)


def plan(details: list[OpeningDetail], blocked_by: str | None = None) -> Plan:
    return Plan(
        window_start=DAY,
        window_end=DAY + timedelta(days=1),
        openings=tuple(d.opening for d in details),
        details=tuple(details),
        blocked_by=blocked_by,
        outdoor_high_c=f2c(92),
        outdoor_low_c=f2c(65),
        outdoor_dew_point_low_c=f2c(68),
        outdoor_dew_point_high_c=f2c(72),
        outlook_high_c=f2c(92),
        outlook_low_c=f2c(70),
        hours_above_limit=6.0,
        baseline_hours_above_limit=4.0,
        mean_humidity=55.0,
        baseline_mean_humidity=54.0,
        end_state=IndoorState.from_reading(temperature_c=24.0, relative_humidity_percent=50.0),
    )


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fmt = Formatter("fahrenheit", plan_settings())

    def test_morning_message_for_short_humid_airing(self) -> None:
        message = morning_message(plan([detail(DAY.replace(hour=9, minute=30), DAY.replace(hour=10, minute=15))]), self.fmt)

        self.assertEqual(
            message,
            "**Window plan · Wed Jul 15**\n"
            "• 9:30–10:15am — air out (45 min). 79–81°F, dew point 69°F; "
            "indoor humidity peaks ~74%, under 60% by 10:30am.\n"
            "Otherwise closed. High 92°F, low 65°F.",
        )

    def test_long_and_overnight_openings(self) -> None:
        long_day = detail(DAY.replace(hour=11), DAY.replace(hour=19), peak_humidity=50.0, dries_house=True)
        overnight = detail(
            DAY.replace(hour=19, minute=30),
            DAY + timedelta(days=1),
            peak_humidity=50.0,
            indoor_temp_at_close_c=f2c(66),
        )

        message = morning_message(plan([long_day, overnight]), self.fmt)

        self.assertIn("• 11am–7pm — open. 79–81°F, dew point 69°F; dries the house out; house ~76°F at close.", message)
        self.assertIn("• 7:30pm–5am — open overnight.", message)
        self.assertIn("house ~66°F at close", message)

    def test_humidity_peak_not_mentioned_when_closed_house_is_as_humid(self) -> None:
        message = morning_message(
            plan([detail(DAY.replace(hour=9), DAY.replace(hour=10), closed_humidity_at_peak=73.0)]), self.fmt
        )

        self.assertNotIn("peaks", message)

    def test_closed_day_explains_why(self) -> None:
        message = morning_message(plan([], blocked_by="humidity"), self.fmt)

        self.assertEqual(
            message,
            "**Window plan · Wed Jul 15**\nKeep closed today — too humid even for a short airing (dew point 68–72°F).",
        )

    def test_temperature_reason_picks_hot_or_cold(self) -> None:
        hot = morning_message(plan([], blocked_by="temperature"), self.fmt)

        self.assertIn("too hot outside (up to 92°F)", hot)

    def test_midday_message_only_lists_remaining_openings(self) -> None:
        morning = detail(DAY.replace(hour=6), DAY.replace(hour=7))
        afternoon = detail(DAY.replace(hour=16), DAY.replace(hour=17))

        message = midday_message(plan([morning, afternoon]), DAY.replace(hour=12, minute=30), self.fmt)

        self.assertTrue(message.startswith("**Plan update · Wed Jul 15**"))
        self.assertIn("4–5pm", message)
        self.assertNotIn("6–7am", message)

    def test_evening_message_includes_tomorrow(self) -> None:
        tomorrow = plan([detail(DAY.replace(hour=6) + timedelta(days=1), DAY.replace(hour=7) + timedelta(days=1))])

        message = evening_message(plan([], blocked_by="max_openings"), DAY.replace(hour=17, minute=30), tomorrow, self.fmt)

        self.assertIn("Keep closed tonight — today's openings are done.", message)
        self.assertIn("Tomorrow: air out 6–7am (high 92°F).", message)

    def test_plans_differ_uses_tolerance(self) -> None:
        base = (Opening(DAY.replace(hour=9), DAY.replace(hour=10)),)
        nudged = (Opening(DAY.replace(hour=9, minute=15), DAY.replace(hour=10, minute=15)),)
        moved = (Opening(DAY.replace(hour=11), DAY.replace(hour=12)),)

        self.assertFalse(plans_differ(base, nudged))
        self.assertTrue(plans_differ(base, moved))
        self.assertTrue(plans_differ(base, ()))
