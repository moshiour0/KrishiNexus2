# -*- coding: utf-8 -*-
"""
fieldshift.engine.water
========================
FAO-56 Penman-Monteith reference evapotranspiration, the crop coefficient
curve, and the irrigation requirement calculation. This is the single most
"validity-critical" module in the project (blueprint Appendix A.5) -- every
public function has a docstring naming its FAO-56 source equation, and
tests/test_engine.py checks physical sanity (monotonicity, plausible
magnitude) rather than a from-memory worked-example number that can't be
verified without the source document open.

Reference: Allen, R.G., Pereira, L.S., Raes, D., Smith, M. (1998). Crop
evapotranspiration -- Guidelines for computing crop water requirements.
FAO Irrigation and Drainage Paper 56. https://www.fao.org/3/x0490e/x0490e00.htm
"""
from __future__ import annotations

import math

from fieldshift.engine.models import DailyWeather, CropProfile
from fieldshift.engine.weather import ELEV_M, LAT_DEG, _extraterrestrial_radiation_mj

GSC = 0.0820           # solar constant, MJ m-2 min-1 (FAO-56 Eq. 28)
SIGMA = 4.903e-9        # Stefan-Boltzmann constant, MJ K-4 m-2 day-1 (FAO-56 Eq. 39)
ALBEDO = 0.23           # reference crop albedo (FAO-56 Eq. 38)


def _saturation_vapour_pressure(t_c: float) -> float:
    """e_o(T), FAO-56 Eq. 11 (kPa)."""
    return 0.6108 * math.exp(17.27 * t_c / (t_c + 237.3))


def _slope_svp_curve(t_c: float) -> float:
    """Delta, FAO-56 Eq. 13 (kPa/degC)."""
    es = _saturation_vapour_pressure(t_c)
    return 4098 * es / (t_c + 237.3) ** 2


def _psychrometric_constant(elev_m: float) -> float:
    """gamma, FAO-56 Eq. 7-8 (kPa/degC)."""
    p = 101.3 * ((293 - 0.0065 * elev_m) / 293) ** 5.26
    return 0.665e-3 * p


def _net_radiation_mj(w: DailyWeather, day_of_year: int, lat_deg: float, elev_m: float) -> float:
    """Rn = Rns - Rnl, FAO-56 Eq. 40, via Eq. 21 (Ra), Eq. 37 (Rso), Eq. 38 (Rns), Eq. 39 (Rnl)."""
    ra = _extraterrestrial_radiation_mj(day_of_year, lat_deg)
    rso = (0.75 + 2e-5 * elev_m) * ra
    rns = (1 - ALBEDO) * w.solar_rad_mj_m2_day
    tmax_k, tmin_k = w.tmax_c + 273.16, w.tmin_c + 273.16
    es_mean = (_saturation_vapour_pressure(w.tmax_c) + _saturation_vapour_pressure(w.tmin_c)) / 2
    ea = es_mean * (w.rh_mean_pct / 100.0)
    rs_rso = max(0.3, min(1.0, w.solar_rad_mj_m2_day / max(rso, 1e-6)))
    rnl = SIGMA * ((tmax_k ** 4 + tmin_k ** 4) / 2) * (0.34 - 0.14 * math.sqrt(max(ea, 0))) \
        * (1.35 * rs_rso - 0.35)
    return rns - rnl


def reference_et0_mm(w: DailyWeather, day_of_year: int,
                      lat_deg: float = LAT_DEG, elev_m: float = ELEV_M) -> float:
    """
    ET0, FAO-56 Eq. 6 -- the Penman-Monteith equation for the grass reference crop:

        ET0 = (0.408*D*(Rn-G) + g*(900/(T+273))*u2*(es-ea)) / (D + g*(1+0.34*u2))

    Returns mm/day. G (soil heat flux) is taken as 0 for daily timestep per FAO-56.
    """
    t_mean = (w.tmax_c + w.tmin_c) / 2
    delta = _slope_svp_curve(t_mean)
    gamma = _psychrometric_constant(elev_m)
    rn = _net_radiation_mj(w, day_of_year, lat_deg, elev_m)
    g = 0.0
    es = (_saturation_vapour_pressure(w.tmax_c) + _saturation_vapour_pressure(w.tmin_c)) / 2
    ea = es * (w.rh_mean_pct / 100.0)
    u2 = w.wind_2m_ms

    numerator = 0.408 * delta * (rn - g) + gamma * (900 / (t_mean + 273)) * u2 * (es - ea)
    denominator = delta + gamma * (1 + 0.34 * u2)
    et0 = numerator / denominator
    return max(0.0, et0)


def kc_on_day(crop: CropProfile, day_index: int) -> float:
    """
    Crop coefficient on a given day of the crop's growth cycle (0-indexed),
    FAO-56 Chapter 6: constant at Kc_ini through the initial stage, linear
    interpolation Kc_ini -> Kc_mid across the development stage, constant at
    Kc_mid through the mid-season stage, linear interpolation
    Kc_mid -> Kc_end across the late-season stage.
    """
    ini, dev, mid, late = crop.stage_days
    if day_index < 0 or day_index >= crop.duration_days:
        return 0.0
    if day_index < ini:
        return crop.kc_ini
    if day_index < ini + dev:
        frac = (day_index - ini) / max(dev, 1)
        return crop.kc_ini + frac * (crop.kc_mid - crop.kc_ini)
    if day_index < ini + dev + mid:
        return crop.kc_mid
    frac = (day_index - ini - dev - mid) / max(late, 1)
    return crop.kc_mid + frac * (crop.kc_end - crop.kc_mid)


def effective_rainfall_mm(rain_mm: float) -> float:
    """
    Simplified effective-rainfall rule: 80% of gross rainfall counts toward
    crop water demand (a common rule-of-thumb fraction for well-managed
    fields). This is a placeholder simplification of the fuller USDA Soil
    Conservation Service / FAO-33 method -- replace in Phase 2 if precision
    matters more than the coarse resolution of the underlying rainfall data
    already justifies.
    """
    return 0.8 * rain_mm


def crop_water_requirement(crop: CropProfile, daily: tuple[DailyWeather, ...],
                            start_index: int,
                            lat_deg: float = LAT_DEG, elev_m: float = ELEV_M) -> dict:
    """
    Runs the crop's full growth cycle starting at daily[start_index] and
    returns cumulative ETc, effective rainfall, and the net irrigation
    requirement (blueprint Section 6.4, "Irrigation requirement (mm)").
    Raises IndexError if the series does not cover the full duration --
    callers should catch this as "insufficient weather data" (fail loud).
    """
    n = crop.duration_days
    end_index = start_index + n
    if end_index > len(daily):
        raise IndexError(
            f"weather series has {len(daily)} days but crop {crop.crop_id} "
            f"needs days [{start_index}, {end_index})"
        )
    etc_total = 0.0
    peff_total = 0.0
    rain_total = 0.0
    et0_values = []
    for i in range(n):
        w = daily[start_index + i]
        et0 = reference_et0_mm(w, w.d.timetuple().tm_yday, lat_deg, elev_m)
        kc = kc_on_day(crop, i)
        etc_total += et0 * kc
        rain_total += w.rain_mm
        peff_total += effective_rainfall_mm(w.rain_mm)
        et0_values.append(et0)
    irrigation_mm = max(0.0, etc_total - peff_total)
    return {
        "etc_total_mm": round(etc_total, 1),
        "rain_total_mm": round(rain_total, 1),
        "effective_rain_mm": round(peff_total, 1),
        "irrigation_requirement_mm": round(irrigation_mm, 1),
        "mean_et0_mm_day": round(sum(et0_values) / len(et0_values), 2),
    }
