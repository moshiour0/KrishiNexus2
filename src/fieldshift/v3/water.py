from __future__ import annotations

import math
from datetime import date
from typing import Any, TypedDict

from fieldshift.engine.weather import _extraterrestrial_radiation_mj

from .models import CropV2, FieldV2, RemoteDay, WeatherDay

SIGMA = 4.903e-9
ALBEDO = 0.23


class WaterResult(TypedDict):
    etc_mm: float
    etc_daily_mm: dict[date, float]
    rainfall_mm: float
    rain_effective_mm: float
    runoff_mm: float
    deep_drainage_mm: float
    paddy_outflow_mm: float
    irrigation_mm: float
    irrigation_gross_mm: float
    irrigation_effective_mm: float
    irrigation_loss_mm: float
    root_zone_depletion_fraction: float
    water_stress_days: float
    severe_water_stress_days: float
    water_stress_fraction: float
    mean_rootzone_moisture_fraction: float
    heat_stress_days: float
    heat_degree_days: float
    heavy_rain_days: float
    waterlogging_days: float
    taw_mm: float
    initial_storage_mm: float
    final_storage_mm: float
    water_balance_error_mm: float
    smap_abs_error_m3_m3: float
    smap_match_count: float
    curve_number: float


def svp(t: float) -> float:
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def slope_svp(t: float) -> float:
    return 4098 * svp(t) / (t + 237.3) ** 2


def gamma(elev_m: float) -> float:
    p = 101.3 * ((293 - 0.0065 * elev_m) / 293) ** 5.26
    return 0.665e-3 * p


def et0(day: WeatherDay, lat_deg: float, elev_m: float) -> float:
    """FAO-56 reference ET (mm/day) with daily net-radiation terms."""
    doy = day.d.timetuple().tm_yday
    ra = _extraterrestrial_radiation_mj(doy, lat_deg)
    rso = (0.75 + 2e-5 * elev_m) * ra
    rns = (1 - ALBEDO) * day.solar_rad_mj_m2_day
    tkmax = day.tmax_c + 273.16
    tkmin = day.tmin_c + 273.16
    es = (svp(day.tmax_c) + svp(day.tmin_c)) / 2
    ea = es * max(0.0, min(100.0, day.rh_mean_pct)) / 100.0
    ratio = max(0.3, min(1.0, day.solar_rad_mj_m2_day / max(rso, 1e-6)))
    rnl = SIGMA * ((tkmax**4 + tkmin**4) / 2) * (0.34 - 0.14 * math.sqrt(max(ea, 0))) * (1.35 * ratio - 0.35)
    rn = rns - rnl
    tmean = (day.tmax_c + day.tmin_c) / 2
    d = slope_svp(tmean)
    g = gamma(elev_m)
    numerator = 0.408 * d * rn + g * (900 / (tmean + 273)) * max(0.0, day.wind_2m_ms) * (es - ea)
    denominator = d + g * (1 + 0.34 * max(0.0, day.wind_2m_ms))
    return max(0.0, numerator / max(denominator, 1e-9))


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
        if clay is not None and clay >= 35:
            fc, wp = 0.40, 0.22
        elif clay is not None and clay >= 20:
            fc, wp = 0.32, 0.17
        elif sand is not None and sand >= 65:
            fc, wp = 0.18, 0.08
        else:
            fc, wp = 0.27, 0.14
    return fc, wp, max(0.01, fc - wp)


def estimate_curve_number(soil: Any) -> float:
    if getattr(soil, "curve_number", None) is not None:
        return float(soil.curve_number)
    drainage = (soil.drainage_class or "medium").lower()
    cn = 72.0
    if "poor" in drainage:
        cn += 10
    elif "well" in drainage:
        cn -= 5
    elif "rapid" in drainage:
        cn -= 8
    clay = soil.clay_pct or 30.0
    sand = soil.sand_pct or 35.0
    cn += max(-5.0, min(8.0, (clay - sand) * 0.06))
    return max(40.0, min(92.0, cn))


def _scs_runoff_mm(rain_mm: float, soil: Any) -> float:
    """SCS-CN event runoff for AMC-II; CN is explicit when supplied and estimated otherwise."""
    if rain_mm <= 0:
        return 0.0
    cn = estimate_curve_number(soil)
    s = max(1.0, 25400.0 / cn - 254.0)
    ia = 0.2 * s
    if rain_mm <= ia:
        return 0.0
    return min(rain_mm, (rain_mm - ia) ** 2 / max(rain_mm + 0.8 * s, 1e-9))


def _initial_depletion(taw_mm: float, crop: CropV2, start_date: date, remote_by_date: dict[date, RemoteDay], fc: float, wp: float) -> float:
    # Prefer a dated SMAP root-zone observation near planting; otherwise use an editable 35% TAW default.
    candidates = [(abs((d - start_date).days), x.smap_rootzone_m3_m3) for d, x in remote_by_date.items()
                  if x.smap_rootzone_m3_m3 is not None and abs((d - start_date).days) <= 7]
    if candidates:
        _, vwc = min(candidates, key=lambda x: x[0])
        frac = max(0.0, min(1.0, (float(vwc) - wp) / max(fc - wp, 1e-9)))
        return max(0.0, taw_mm * (1 - frac))
    return 0.35 * taw_mm


def simulate_crop_water(
    crop: CropV2,
    start_date: date,
    days: tuple[WeatherDay, ...],
    field: FieldV2,
    remote_by_date: dict[date, RemoteDay] | None = None,
) -> WaterResult:
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
    depletion = _initial_depletion(taw, crop, start_date, remote_by_date, fc, wp)
    initial_storage = taw - depletion
    irrigation_gross = 0.0
    irrigation_effective = 0.0
    irrigation_loss = 0.0
    runoff_total = 0.0
    deep_drainage_total = 0.0
    paddy_outflow_total = 0.0
    etc_total = 0.0
    etc_daily_mm: dict[date, float] = {}
    rain_effective_total = 0.0
    deficits = 0
    severe = 0
    heat_days = 0
    heat_degree_days = 0.0
    heavy_rain_days = 0
    waterlog_days = 0
    model_vwc: list[float] = []
    smap_residuals: list[float] = []

    for j in range(crop.duration_days):
        w = days[start + j]
        et_ref = et0(w, field.lat, field.elevation_m)
        demand = et_ref * kc(crop, j)
        etc_total += demand
        etc_daily_mm[w.d] = demand
        remote = remote_by_date.get(w.d)
        rain_mm = remote.gpm_rain_mm if remote and remote.gpm_rain_mm is not None else w.rain_mm
        runoff = _scs_runoff_mm(rain_mm, field.soil)
        infiltrated = max(0.0, rain_mm - runoff)
        runoff_total += runoff
        rain_effective_total += infiltrated
        storage_before = taw - depletion
        available = storage_before + infiltrated

        if crop.rice_paddy and j < crop.standing_water_days:
            paddy_outflow = crop.percolation_mm_day + crop.seepage_mm_day
            demand += paddy_outflow
            paddy_outflow_total += paddy_outflow

        # Irrigate only to refill to RAW; reliability is a conveyance/application efficiency, so gross withdrawals exceed net root-zone input.
        if available - demand < raw:
            net_need = max(0.0, raw - (available - demand))
            reliability = max(field.farmer.irrigation_reliability, 0.05)
            gross = net_need / reliability
            effective = gross * reliability
            loss = gross - effective
            irrigation_gross += gross
            irrigation_effective += effective
            irrigation_loss += loss
            available += effective

        post = available - demand
        if post > taw:
            deep = post - taw
            deep_drainage_total += deep
            storage = taw
        else:
            deep = 0.0
            storage = max(0.0, post)
        depletion = taw - storage
        if depletion > raw:
            deficits += 1
        if depletion > 0.8 * taw:
            severe += 1

        if rain_mm >= 40:
            heavy_rain_days += 1
        drainage_poor = (field.soil.drainage_class or "medium").lower() in {"poor", "very_poor"}
        storage_fraction = storage / max(taw, 1e-9)
        if rain_mm >= 40 and storage_fraction > 0.95 and (drainage_poor or crop.waterlogging_tolerance < 0.5):
            waterlog_days += 1

        _hs_label, hs_start, hs_end = crop.heat_sensitive_stage
        if hs_start <= j < hs_end and w.tmax_c > crop.heat_threshold_c:
            heat_days += 1
            heat_degree_days += w.tmax_c - crop.heat_threshold_c

        vwc = wp + aw * (storage / max(taw, 1e-9))
        model_vwc.append(vwc)
        if remote is not None and remote.smap_rootzone_m3_m3 is not None:
            smap_residuals.append(abs(vwc - remote.smap_rootzone_m3_m3))

    mean_moisture = sum(model_vwc) / max(len(model_vwc), 1)
    mean_moisture_fraction = max(0.0, min(1.0, (mean_moisture - wp) / max(fc - wp, 1e-9)))
    stress_frac = deficits / max(crop.duration_days, 1)
    severe_frac = severe / max(crop.duration_days, 1)
    initial = initial_storage
    final = taw - depletion
    balance_in = initial + rain_effective_total + irrigation_effective
    balance_out = final + etc_total + deep_drainage_total + paddy_outflow_total
    balance_error = balance_in - balance_out
    rainfall_total = 0.0
    for j in range(crop.duration_days):
        day_date = days[start + j].d
        rd = remote_by_date.get(day_date) if remote_by_date else None
        if rd is not None and rd.gpm_rain_mm is not None:
            rainfall_total += rd.gpm_rain_mm
        else:
            rainfall_total += days[start + j].rain_mm
    return {
        "etc_mm": etc_total,
        "etc_daily_mm": etc_daily_mm,
        "rainfall_mm": rainfall_total,
        "rain_effective_mm": rain_effective_total,
        "runoff_mm": runoff_total,
        "deep_drainage_mm": deep_drainage_total,
        "paddy_outflow_mm": paddy_outflow_total,
        "irrigation_mm": irrigation_gross,
        "irrigation_gross_mm": irrigation_gross,
        "irrigation_effective_mm": irrigation_effective,
        "irrigation_loss_mm": irrigation_loss,
        "root_zone_depletion_fraction": severe_frac,
        "water_stress_days": float(deficits),
        "severe_water_stress_days": float(severe),
        "water_stress_fraction": stress_frac,
        "mean_rootzone_moisture_fraction": mean_moisture_fraction,
        "heat_stress_days": float(heat_days),
        "heat_degree_days": heat_degree_days,
        "heavy_rain_days": float(heavy_rain_days),
        "waterlogging_days": float(waterlog_days),
        "taw_mm": taw,
        "initial_storage_mm": initial,
        "final_storage_mm": final,
        "water_balance_error_mm": balance_error,
        "smap_abs_error_m3_m3": sum(smap_residuals) / len(smap_residuals) if smap_residuals else 0.0,
        "smap_match_count": float(len(smap_residuals)),
        "curve_number": estimate_curve_number(field.soil),
    }
