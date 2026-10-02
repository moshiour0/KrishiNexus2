# -*- coding: utf-8 -*-
"""
fieldshift.engine.weather
==========================
SYNTHETIC weather generator for the Mymensingh pilot block.

This exists so the whole pipeline runs offline with zero credentials, per
the blueprint's "snapshot rule" (Section 5.5). It is NOT a NASA POWER pull.
Every DailyWeather record it produces is tagged source="synthetic" so
provenance is honest end to end -- nothing downstream can mistake this for
real observational data.

Calibration is to well-established, general Bangladesh / Mymensingh climate
patterns (cool dry winter, hot pre-monsoon, wet monsoon June-September,
cooling post-monsoon) -- deliberately approximate. REPLACE with a real NASA
POWER daily pull (Appendix A.1 of the blueprint) as the first task of
Phase-1 Week 3.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

from fieldshift.engine.models import DailyWeather

# Monthly climatology targets for Mymensingh (illustrative, general-knowledge
# calibration -- NOT sourced from a specific station record). (month -> value)
_TMAX = {1: 24.5, 2: 27.5, 3: 32.0, 4: 33.5, 5: 32.5, 6: 31.5,
         7: 31.0, 8: 31.5, 9: 31.5, 10: 30.5, 11: 27.5, 12: 24.5}
_TMIN = {1: 12.0, 2: 15.0, 3: 19.5, 4: 23.5, 5: 24.5, 6: 25.5,
         7: 25.5, 8: 25.5, 9: 25.0, 10: 22.0, 11: 16.5, 12: 12.5}
_RAIN_MONTHLY_MM = {1: 8, 2: 20, 3: 45, 4: 130, 5: 260, 6: 420,
                     7: 440, 8: 350, 9: 290, 10: 130, 11: 20, 12: 5}
_RH = {1: 72, 2: 68, 3: 65, 4: 70, 5: 78, 6: 87,
       7: 89, 8: 88, 9: 87, 10: 82, 11: 75, 12: 73}
_WIND_MS = {m: 1.4 for m in range(1, 13)}
_WIND_MS.update({4: 1.9, 5: 2.1, 6: 1.9, 7: 1.7})   # pre-monsoon/monsoon a bit breezier
_CLOUD_FACTOR = {  # 1.0 = clear, lower = more cloud cover (reduces solar radiation)
    1: 0.92, 2: 0.90, 3: 0.85, 4: 0.78, 5: 0.68, 6: 0.50,
    7: 0.45, 8: 0.48, 9: 0.55, 10: 0.72, 11: 0.88, 12: 0.92,
}

LAT_DEG = 24.75
ELEV_M = 18.0


def _extraterrestrial_radiation_mj(day_of_year: int, lat_deg: float) -> float:
    """Ra, FAO-56 Eq. 21 -- used only to scale a plausible Rs, not for ET0 directly here."""
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * day_of_year / 365)
    delta = 0.409 * math.sin(2 * math.pi * day_of_year / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta))))
    gsc = 0.0820
    return (24 * 60 / math.pi) * gsc * dr * (
        ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws)
    )


def generate_year(year: int, seed: int = 42) -> tuple[DailyWeather, ...]:
    """One synthetic year of daily weather, Jan 1 through Dec 31."""
    rng = random.Random(seed)
    out = []
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        m = d.month
        # Smooth month-to-month by blending with a day-of-year sinusoid rather
        # than hard monthly steps, so the water-balance calc sees a plausible
        # continuous curve, not sawtooth jumps at month boundaries.
        frac = (d.timetuple().tm_yday - 1) / 365
        season_phase = math.sin(2 * math.pi * (frac - 0.12))  # peaks ~ early May

        tmax = _TMAX[m] + 1.5 * season_phase + rng.gauss(0, 1.1)
        tmin = _TMIN[m] + 1.0 * season_phase + rng.gauss(0, 1.0)
        tmin = min(tmin, tmax - 3.0)

        rh = max(35.0, min(98.0, _RH[m] + rng.gauss(0, 4)))
        wind = max(0.3, _WIND_MS[m] + rng.gauss(0, 0.4))

        ra = _extraterrestrial_radiation_mj(d.timetuple().tm_yday, LAT_DEG)
        rs = ra * _CLOUD_FACTOR[m] * (1 + rng.gauss(0, 0.05))
        rs = max(2.0, rs)

        # Rain: mostly zero, occasional wet days sized so the monthly total
        # tracks _RAIN_MONTHLY_MM. Monsoon months get more rainy days.
        days_in_month = (date(year, m % 12 + 1, 1) - timedelta(days=1)).day if m < 12 else 31
        wet_day_prob = {1: 0.06, 2: 0.10, 3: 0.15, 4: 0.30, 5: 0.45, 6: 0.60,
                        7: 0.65, 8: 0.60, 9: 0.55, 10: 0.30, 11: 0.08, 12: 0.05}[m]
        if rng.random() < wet_day_prob:
            mean_event = _RAIN_MONTHLY_MM[m] / max(1, days_in_month * wet_day_prob)
            rain = max(0.0, rng.gammavariate(1.6, mean_event / 1.6))
        else:
            rain = 0.0

        out.append(DailyWeather(
            d=d, tmax_c=round(tmax, 1), tmin_c=round(tmin, 1),
            rh_mean_pct=round(rh, 1), wind_2m_ms=round(wind, 2),
            solar_rad_mj_m2_day=round(rs, 2), rain_mm=round(rain, 1),
            source="synthetic",
        ))
        d += timedelta(days=1)
    return tuple(out)


def scale_scenario(daily: tuple[DailyWeather, ...], dtemp_c: float, rain_mult: float,
                    name: str) -> tuple[DailyWeather, ...]:
    """Delta-method climate scenario (blueprint Section 6.5): shift temperature,
    scale rainfall, applied to an existing daily series. Deliberately simple --
    swap in real NEX-GDDP-CMIP6 monthly deltas per Appendix A.2 in Phase 2."""
    out = []
    for w in daily:
        out.append(DailyWeather(
            d=w.d, tmax_c=round(w.tmax_c + dtemp_c, 1), tmin_c=round(w.tmin_c + dtemp_c, 1),
            rh_mean_pct=w.rh_mean_pct, wind_2m_ms=w.wind_2m_ms,
            solar_rad_mj_m2_day=w.solar_rad_mj_m2_day,
            rain_mm=round(w.rain_mm * rain_mult, 1), source=f"synthetic+delta({name})",
        ))
    return tuple(out)
