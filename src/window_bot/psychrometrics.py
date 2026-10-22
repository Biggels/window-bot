"""Moist-air conversions.

Everything here works in degrees Celsius and humidity ratio (kg of water vapor
per kg of dry air). Humidity ratio is the quantity that is conserved when
outdoor air comes inside and warms or cools, which is why the model tracks it
instead of relative humidity.
"""

from __future__ import annotations

import math

SEA_LEVEL_PRESSURE_HPA = 1013.25

# Magnus coefficients over water (Alduchov & Eskridge, 1996).
_MAGNUS_B = 17.625
_MAGNUS_C = 243.04
_MAGNUS_A_HPA = 6.1094

_VAPOR_TO_DRY_AIR_MASS = 0.622


def fahrenheit_to_celsius(value: float) -> float:
    return (value - 32.0) * 5.0 / 9.0


def celsius_to_fahrenheit(value: float) -> float:
    return value * 9.0 / 5.0 + 32.0


def saturation_vapor_pressure(temperature_c: float) -> float:
    """Saturation vapor pressure in hPa."""
    return _MAGNUS_A_HPA * math.exp(_MAGNUS_B * temperature_c / (temperature_c + _MAGNUS_C))


def humidity_ratio_from_dew_point(dew_point_c: float, pressure_hpa: float = SEA_LEVEL_PRESSURE_HPA) -> float:
    vapor_pressure = saturation_vapor_pressure(dew_point_c)
    return _VAPOR_TO_DRY_AIR_MASS * vapor_pressure / (pressure_hpa - vapor_pressure)


def humidity_ratio_from_relative_humidity(
    temperature_c: float,
    relative_humidity: float,
    pressure_hpa: float = SEA_LEVEL_PRESSURE_HPA,
) -> float:
    vapor_pressure = relative_humidity / 100.0 * saturation_vapor_pressure(temperature_c)
    return _VAPOR_TO_DRY_AIR_MASS * vapor_pressure / (pressure_hpa - vapor_pressure)


def relative_humidity(
    temperature_c: float,
    humidity_ratio: float,
    pressure_hpa: float = SEA_LEVEL_PRESSURE_HPA,
) -> float:
    """Relative humidity in percent (may exceed 100 for supersaturated inputs)."""
    vapor_pressure = humidity_ratio * pressure_hpa / (_VAPOR_TO_DRY_AIR_MASS + humidity_ratio)
    return 100.0 * vapor_pressure / saturation_vapor_pressure(temperature_c)


def dew_point(humidity_ratio: float, pressure_hpa: float = SEA_LEVEL_PRESSURE_HPA) -> float:
    vapor_pressure = humidity_ratio * pressure_hpa / (_VAPOR_TO_DRY_AIR_MASS + humidity_ratio)
    gamma = math.log(vapor_pressure / _MAGNUS_A_HPA)
    return _MAGNUS_C * gamma / (_MAGNUS_B - gamma)


def dew_point_for_relative_humidity(temperature_c: float, relative_humidity_percent: float) -> float:
    """Dew point of air at ``temperature_c`` with the given relative humidity."""
    return dew_point(humidity_ratio_from_relative_humidity(temperature_c, relative_humidity_percent))
