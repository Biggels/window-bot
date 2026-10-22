from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import unittest

from window_bot.house import STEP, IndoorState, OutdoorStep, simulate
from window_bot.psychrometrics import fahrenheit_to_celsius, humidity_ratio_from_dew_point

from helpers import TZ, house

START = datetime(2026, 7, 15, 5, 0, tzinfo=TZ)


def steady(temperature_f: float, dew_point_f: float, hours: float) -> list[OutdoorStep]:
    count = int(timedelta(hours=hours) / STEP)
    dew = fahrenheit_to_celsius(dew_point_f)
    return [
        OutdoorStep(
            time=START + index * STEP,
            temperature_c=fahrenheit_to_celsius(temperature_f),
            dew_point_c=dew,
            humidity_ratio=humidity_ratio_from_dew_point(dew),
            rain_likely=False,
        )
        for index in range(count)
    ]


def comfortable_state() -> IndoorState:
    return IndoorState.from_reading(temperature_c=fahrenheit_to_celsius(73), relative_humidity_percent=50.0)


class HouseModelTests(unittest.TestCase):
    def test_closed_house_is_held_between_setpoints(self) -> None:
        params = house()
        hot = simulate(params, comfortable_state(), steady(90, 55, 24), [False] * 96)
        cold = simulate(params, comfortable_state(), steady(30, 20, 24), [False] * 96)

        self.assertAlmostEqual(hot.temperature_c[-1], params.cool_setpoint_c, delta=0.05)
        self.assertAlmostEqual(cold.temperature_c[-1], params.heat_setpoint_c, delta=0.05)

    def test_opening_on_humid_day_raises_indoor_humidity(self) -> None:
        params = house()
        outdoor = steady(80, 70, 6)
        closed = simulate(params, comfortable_state(), outdoor, [False] * len(outdoor))
        aired = simulate(params, comfortable_state(), outdoor, [True] * 2 + [False] * (len(outdoor) - 2))

        self.assertGreater(max(aired.relative_humidity[:4]), max(closed.relative_humidity[:4]) + 10)

    def test_humidity_spike_mostly_fades_after_closing(self) -> None:
        params = house()
        outdoor = steady(80, 70, 8)
        aired = simulate(params, comfortable_state(), outdoor, [True] * 2 + [False] * (len(outdoor) - 2))

        peak = max(aired.relative_humidity)
        self.assertLess(aired.relative_humidity[-1], peak - 10)

    def test_dry_air_dries_the_house(self) -> None:
        params = house()
        start = IndoorState.from_reading(temperature_c=fahrenheit_to_celsius(70), relative_humidity_percent=65.0)
        outdoor = steady(68, 40, 4)
        aired = simulate(params, start, outdoor, [True] * len(outdoor))

        # Materials give up their moisture slowly, so it dries a lot but not all the way to outdoor air.
        self.assertLess(aired.relative_humidity[-1], 50.0)

    def test_opening_flushes_staleness_and_closing_lets_it_build(self) -> None:
        params = house()
        outdoor = steady(70, 50, 8)
        flags = [True] * 4 + [False] * (len(outdoor) - 4)
        trace = simulate(params, comfortable_state(), outdoor, flags)

        self.assertLess(trace.staleness[3], 0.1)
        self.assertGreater(trace.staleness[-1], trace.staleness[3] + 0.5)

    def test_closed_house_without_sources_converges_to_outdoor_moisture(self) -> None:
        params = replace(house(), moisture_generation_kg_per_day=0.0, ac_moisture_removal_kg_per_hour=0.0)
        outdoor = steady(72, 50, 24 * 20)
        trace = simulate(params, comfortable_state(), outdoor, [False] * len(outdoor))

        self.assertAlmostEqual(trace.final_state.air_humidity_ratio, outdoor[0].humidity_ratio, delta=2e-5)
        self.assertAlmostEqual(trace.final_state.buffer_humidity_ratio, outdoor[0].humidity_ratio, delta=2e-5)

    def test_ac_running_removes_moisture(self) -> None:
        outdoor = steady(92, 65, 12)
        flags = [False] * len(outdoor)
        with_ac = simulate(house(), comfortable_state(), outdoor, flags)
        without = simulate(replace(house(), ac_moisture_removal_kg_per_hour=0.0), comfortable_state(), outdoor, flags)

        self.assertLess(with_ac.relative_humidity[-1], without.relative_humidity[-1] - 5)
