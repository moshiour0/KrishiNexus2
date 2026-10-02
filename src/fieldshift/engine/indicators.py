# -*- coding: utf-8 -*-
"""
fieldshift.engine.indicators
=============================
Computes one IndicatorSet for a (rotation, weather scenario) pair, given the
rotation's feasibility schedule. Every formula here is a documented,
transparent heuristic (blueprint Section 6.4/6.6, "publish the formula") --
none of it claims to be a peer-reviewed agronomic index. Swap in
expert-reviewed weights once Section 10 (Quality/Validation) review happens.
"""
from __future__ import annotations

from fieldshift.engine.constraints import ScheduledCrop, _window_end
from fieldshift.engine.models import CropProfile, DailyWeather, FieldContext, IndicatorSet
from fieldshift.engine.water import crop_water_requirement

HEAVY_RAIN_MM = 50.0   # placeholder threshold; blueprint 6.4 recommends a local percentile instead
RESIDUE_SCORE = {"low": 0.2, "medium": 0.6, "high": 1.0}


def _daily_by_date(daily: tuple[DailyWeather, ...]) -> dict:
    return {w.d: w for w in daily}


def compute_indicators(rotation_crop_ids: tuple, schedule: list, crop_lookup: dict,
                        daily: tuple[DailyWeather, ...], field: FieldContext,
                        year: int) -> IndicatorSet:
    by_date = _daily_by_date(daily)
    date_index = {w.d: i for i, w in enumerate(daily)}

    irrigation_total = 0.0
    water_risk_components = []
    heat_days_total = 0
    waterlog_days_total = 0
    labour_values = []

    for sched in schedule:
        crop: CropProfile = crop_lookup[sched.crop_id]
        start_idx = date_index.get(sched.sow_date)
        if start_idx is None:
            raise ValueError(
                f"{sched.crop_id}: sow date {sched.sow_date} is outside the supplied "
                f"weather series -- widen the generated year range."
            )
        wr = crop_water_requirement(crop, daily, start_idx)
        irrigation_total += wr["irrigation_requirement_mm"]

        if field.irrigation_reliable:
            risk = 0.05
        else:
            etc = max(wr["etc_total_mm"], 1e-6)
            risk = max(0.0, min(1.0, 1 - wr["effective_rain_mm"] / etc))
        water_risk_components.append(risk)

        # Heat-sensitive window approximated as the crop's mid-season stage
        # (the Kc curve's mid-season period typically brackets flowering /
        # reproductive stages for annual field crops -- a documented
        # approximation, not a per-crop phenology model).
        ini, dev, mid, late = crop.stage_days
        sensitive_start = start_idx + ini + dev
        sensitive_end = sensitive_start + mid
        for i in range(sensitive_start, min(sensitive_end, len(daily))):
            if daily[i].tmax_c > crop.heat_critical_tmax_c:
                heat_days_total += 1

        # Waterlogging risk window: establishment (initial stage) + harvest
        # (late stage), per blueprint 6.4 ("during establishment and harvest windows").
        estab_end = start_idx + ini
        harvest_start = start_idx + ini + dev + mid
        harvest_end = start_idx + crop.duration_days
        for i in list(range(start_idx, min(estab_end, len(daily)))) + \
                 list(range(harvest_start, min(harvest_end, len(daily)))):
            if daily[i].rain_mm > HEAVY_RAIN_MM:
                waterlog_days_total += 1

        labour_values.append(crop.labour_person_days_per_ha)

    water_stress_risk = sum(water_risk_components) / max(len(water_risk_components), 1)

    # Soil health index (0-100), transparent weighted heuristic -- see module docstring.
    n_fix_component = 1.0 if any(crop_lookup[c].n_fixing for c in rotation_crop_ids) else 0.0
    residue_component = sum(RESIDUE_SCORE[crop_lookup[c].residue_return]
                             for c in rotation_crop_ids) / len(rotation_crop_ids)
    families = [crop_lookup[c].family for c in rotation_crop_ids]
    diversity_component = len(set(families)) / len(families)
    # Bare-soil proxy: total days the year's land is under a growing crop,
    # summed across the rotation's crops and capped at 365.
    days_covered = min(365, sum(crop_lookup[c].duration_days for c in rotation_crop_ids))
    bare_soil_fraction = max(0.0, min(1.0, (365 - days_covered) / 365))
    soil_health_index = 100 * (
        0.30 * n_fix_component + 0.25 * residue_component +
        0.20 * diversity_component + 0.25 * (1 - bare_soil_fraction)
    )

    income = sum(
        crop_lookup[c].reference_yield_kg_per_ha * crop_lookup[c].price_bdt_per_kg
        - crop_lookup[c].prod_cost_bdt_per_ha
        for c in rotation_crop_ids
    )

    labour_peak = max(labour_values) if labour_values else 0.0

    if len(schedule) < 2:
        turnaround_margin = 999   # no transition to be tight about
    else:
        margins = []
        for a, b in zip(schedule, schedule[1:]):
            crop_b = crop_lookup[b.crop_id]
            window_end_b = _window_end(crop_b.sowing_window, b.sow_date.year)
            margins.append((window_end_b - b.sow_date).days)
        turnaround_margin = min(margins)

    return IndicatorSet(
        irrigation_requirement_mm=round(irrigation_total, 1),
        water_stress_risk=round(water_stress_risk, 3),
        heat_stress_days=heat_days_total,
        waterlogging_risk_days=waterlog_days_total,
        soil_health_index=round(soil_health_index, 1),
        income_proxy_bdt_per_ha=round(income, 0),
        labour_peak_person_days_per_ha=labour_peak,
        turnaround_margin_days=turnaround_margin,
    )
