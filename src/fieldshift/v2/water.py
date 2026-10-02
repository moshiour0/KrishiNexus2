from __future__ import annotations

import math
from datetime import date
from typing import Any

from fieldshift.engine.weather import _extraterrestrial_radiation_mj
from .models import CropV2, FieldV2, RemoteDay, WeatherDay

SIGMA = 4.903e-9
ALBEDO = 0.23


def svp(t: float) -> float:
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def slope_svp(t: float) -> float:
    return 4098 * svp(t) / (t + 237.3) ** 2


def gamma(elev_m: float) -> float:
    p = 101.3 * ((293 - 0.0065 * elev_m) / 293) ** 5.26
    return 0.665e-3 * p


def et0(day: WeatherDay, lat_deg: float, elev_m: float) -> float:
    doy = day.d.timetuple().tm_yday
    ra = _extraterrestrial_radiation_mj(doy, lat_deg)
    rso = (0.75 + 2e-5 * elev_m) * ra
    rns = (1 - ALBEDO) * day.solar_rad_mj_m2_day
    tkmax = day.tmax_c + 273.16
    tkmin = day.tmin_c + 273.16
    es = (svp(day.tmax_c) + svp(day.tmin_c)) / 2
    ea = es * day.rh_mean_pct / 100.0
    ratio = max(0.3, min(1.0, day.solar_rad_mj_m2_day / max(rso, 1e-6)))
    rnl = SIGMA * ((tkmax**4 + tkmin**4) / 2) * (0.34 - 0.14 * math.sqrt(max(ea, 0))) * (1.35 * ratio - 0.35)
    rn = rns - rnl
    tmean = (day.tmax_c + day.tmin_c) / 2
    d = slope_svp(tmean)
    g = gamma(elev_m)
    numerator = 0.408 * d * rn + g * (900 / (tmean + 273)) * day.wind_2m_ms * (es - ea)
    denominator = d + g * (1 + 0.34 * day.wind_2m_ms)
    return max(0.0, numerator / denominator)


def kc(crop: CropV2, index: int) -> float:
    if index < 0 or index >= crop.duration_days:
        return 0.0
    ini, dev, mid, late = crop.stage_days
    if index < ini:
        return crop.kc_ini
    if index < ini + dev:
        f = (index - ini) / max(1, dev)
        return crop.kc_ini + f * (crop.kc_mid - crop.kc_ini)
    if index < ini + dev + mid:
        return crop.kc_mid
    f = (index - ini - dev - mid) / max(1, late)
    return crop.kc_mid + f * (crop.kc_end - crop.kc_mid)


def _texture_storage(soil: Any) -> tuple[float, float, float]:
    if soil.field_capacity_v_v is not None and soil.wilting_point_v_v is not None:
        fc, wp = soil.field_capacity_v_v, soil.wilting_point_v_v
    else:
        clay = soil.clay_pct
        sand = soil.sand_pct
        if clay is not None and sand is not None:
            if clay >= 35: fc, wp = 0.40, 0.22
            elif clay >= 20: fc, wp = 0.32, 0.17
            elif sand >= 65: fc, wp = 0.18, 0.08
            else: fc, wp = 0.27, 0.14
        else:
            fc, wp = 0.27, 0.14
    return fc, wp, max(0.01, fc - wp)


def _runoff_fraction(rain_mm: float, soil: Any) -> float:
    if rain_mm <= 10:
        return 0.02
    clay = soil.clay_pct or 25
    drain = (soil.drainage_class or "medium").lower()
    if "poor" in drain or "very" in drain:
        return min(0.55, 0.12 + 0.0025 * rain_mm)
    return min(0.35, 0.05 + 0.0015 * rain_mm + 0.001 * max(0, clay - 30))


def simulate_crop_water(crop: CropV2, start_date: date, days: tuple[WeatherDay, ...], field: FieldV2,
                        remote_by_date: dict[date, RemoteDay] | None = None) -> dict[str, float]:
    remote_by_date = remote_by_date or {}
    idx = {d.d: i for i, d in enumerate(days)}
    if start_date not in idx:
        raise ValueError(f"weather does not cover {start_date}")
    start = idx[start_date]
    if start + crop.duration_days > len(days):
        raise ValueError("weather series shorter than crop cycle")
    fc, wp, aw = _texture_storage(field.soil)
    root_depth = crop.root_depth_m
    if field.soil.soil_depth_m is not None:
        root_depth = min(root_depth, field.soil.soil_depth_m)
    taw = aw * root_depth * 1000.0
    raw = 0.5 * taw
    depletion = 0.35 * taw
    irrig = 0.0
    etc_total = 0.0
    rain_eff_total = 0.0
    deficits = 0
    severe = 0
    heat_days = 0
    heat_degree_days = 0.0
    heavy_rain_days = 0
    waterlog_days = 0
    smape = []

    for j in range(crop.duration_days):
        w = days[start + j]
        e = et0(w, field.lat, field.elevation_m)
        demand = e * kc(crop, j)
        etc_total += demand
        rain = remote_by_date.get(w.d)
        rain_mm = rain.gpm_rain_mm if rain and rain.gpm_rain_mm is not None else w.rain_mm
        run_frac = _runoff_fraction(rain_mm, field.soil)
        infiltrated = rain_mm * (1 - run_frac)
        effective = min(infiltrated, max(0.0, taw - depletion))

        if crop.rice_paddy:
            effective *= 0.80
            standing_need = max(0.0, crop.percolation_mm_day + crop.seepage_mm_day) if j < crop.standing_water_days else 0.0
            demand += standing_need

        depletion = depletion + demand - effective
        if depletion > raw:
            need = depletion - raw
            reliability = field.farmer.irrigation_reliability
            irrigation_today = need / max(reliability, 0.05)
            irrig += irrigation_today
            depletion -= irrigation_today * reliability
        if depletion > taw:
            severe += 1
        if depletion > raw:
            deficits += 1
        if rain_mm >= 40:
            heavy_rain_days += 1
            if field.soil.drainage_class in ("poor", "very_poor") or crop.waterlogging_tolerance < 0.5:
                waterlog_days += 1

        hs_label, hs_start, hs_end = crop.heat_sensitive_stage
        if hs_start <= j < hs_end and w.tmax_c > crop.heat_threshold_c:
            heat_days += 1
            heat_degree_days += w.tmax_c - crop.heat_threshold_c
        if rain is not None and rain.smap_rootzone_m3_m3 is not None:
            smape.append(rain.smap_rootzone_m3_m3)
        else:
            smape.append(max(0.0, min(1.0, fc - depletion / max(root_depth * 1000, 1))))
        rain_eff_total += effective

    mean_dep = min(1.0, max(0.0, sum(smape) / max(len(smape), 1) / max(fc, 1e-6)))
    stress_frac = min(1.0, deficits / max(crop.duration_days, 1))
    severe_frac = min(1.0, severe / max(crop.duration_days, 1))
    return {
        "etc_mm": etc_total,
        "rain_effective_mm": rain_eff_total,
        "irrigation_mm": irrig,
        "root_zone_depletion_fraction": severe_frac,
        "water_stress_days": float(deficits),
        "severe_water_stress_days": float(severe),
        "water_stress_fraction": stress_frac,
        "mean_rootzone_moisture_fraction": mean_dep,
        "heat_stress_days": float(heat_days),
        "heat_degree_days": heat_degree_days,
        "heavy_rain_days": float(heavy_rain_days),
        "waterlogging_days": float(waterlog_days),
        "taw_mm": taw,
    }
