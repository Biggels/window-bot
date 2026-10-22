from __future__ import annotations

import unittest

from window_bot.psychrometrics import (
    celsius_to_fahrenheit,
    dew_point,
    dew_point_for_relative_humidity,
    fahrenheit_to_celsius,
    humidity_ratio_from_dew_point,
    humidity_ratio_from_relative_humidity,
    relative_humidity,
    saturation_vapor_pressure,
)


class PsychrometricsTests(unittest.TestCase):
    def test_saturation_vapor_pressure_matches_reference_values(self) -> None:
        # Reference values from standard steam tables (hPa).
        self.assertAlmostEqual(saturation_vapor_pressure(0.0), 6.11, delta=0.02)
        self.assertAlmostEqual(saturation_vapor_pressure(20.0), 23.39, delta=0.1)
        self.assertAlmostEqual(saturation_vapor_pressure(30.0), 42.46, delta=0.3)

    def test_humidity_ratio_matches_psychrometric_chart(self) -> None:
        # 20°C at 50% RH is about 7.3 g/kg at sea level.
        self.assertAlmostEqual(humidity_ratio_from_relative_humidity(20.0, 50.0) * 1000, 7.3, delta=0.1)

    def test_conversions_round_trip(self) -> None:
        ratio = humidity_ratio_from_relative_humidity(25.0, 65.0)
        self.assertAlmostEqual(relative_humidity(25.0, ratio), 65.0, places=6)
        self.assertAlmostEqual(humidity_ratio_from_dew_point(dew_point(ratio)), ratio, places=9)
        self.assertAlmostEqual(celsius_to_fahrenheit(fahrenheit_to_celsius(71.3)), 71.3, places=9)

    def test_cool_humid_outdoor_air_is_moderate_once_warmed(self) -> None:
        # 55°F at 80% RH outside becomes roughly 44% RH at 72°F inside.
        ratio = humidity_ratio_from_relative_humidity(fahrenheit_to_celsius(55), 80.0)
        self.assertAlmostEqual(relative_humidity(fahrenheit_to_celsius(72), ratio), 44.0, delta=1.0)

    def test_dew_point_for_relative_humidity(self) -> None:
        # 60% RH at 72°F corresponds to a dew point of about 57°F.
        dew = dew_point_for_relative_humidity(fahrenheit_to_celsius(72), 60.0)
        self.assertAlmostEqual(celsius_to_fahrenheit(dew), 57.4, delta=0.3)
