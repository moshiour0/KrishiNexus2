from __future__ import annotations

from typing import TypedDict

from .models import CropV2, FieldV2


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def soil_water_capacity(field: FieldV2, root_depth_m: float) -> float:
    soil = field.soil
    if soil.field_capacity_v_v is not None and soil.wilting_point_v_v is not None:
        aw = soil.field_capacity_v_v - soil.wilting_point_v_v
    else:
        clay = soil.clay_pct or 25
        sand = soil.sand_pct or 35
        if clay > 35:
            aw = 0.18
        elif sand > 65:
            aw = 0.10
        else:
            aw = 0.14
    depth = min(root_depth_m, soil.soil_depth_m or root_depth_m)
    return aw * depth * 1000


def soil_mass_kg_ha(field: FieldV2) -> float:
    bd = field.soil.bulk_density_g_cm3 or 1.35
    depth = field.soil.soil_depth_m or 1.0
    return bd * depth * 10_000 * 1_000


def nutrient_stock_kg_ha(concentration_mgkg: float | None, field: FieldV2, availability_fraction: float = 1.0) -> float:
    if concentration_mgkg is None:
        return 0.0
    return concentration_mgkg * soil_mass_kg_ha(field) / 1_000_000.0 * availability_fraction


def soil_carbon_trajectory(rotation: tuple[CropV2, ...], field: FieldV2, years: int = 3) -> dict[str, float]:
    """Small auditable SOC trajectory proxy, not a calibrated RothC implementation.

    The model tracks an active and slow pool. All coefficients are explicit so they can be
    replaced by a calibrated SOC model when site data become available.
    """
    years = max(1, int(years))
    mass = soil_mass_kg_ha(field)
    initial_stock = (field.soil.soc_pct or 0.0) / 100.0 * mass
    active = 0.12 * initial_stock
    slow = 0.88 * initial_stock
    cycle_days = max(1, sum(c.duration_days for c in rotation) + 7 * max(0, len(rotation) - 1))
    cycle_years = cycle_days / 365.0
    repeats = max(1, round(years / cycle_years))
    annual_inputs = 0.0
    for _ in range(repeats):
        for crop in rotation:
            input_c = max(0.0, crop.residue_carbon_kg_ha * crop.residue_score)
            frac_year = crop.duration_days / 365.0
            active += 0.65 * input_c * frac_year
            slow += 0.35 * input_c * frac_year
            active *= 1.0 - 0.18 * frac_year
            slow *= 1.0 - 0.025 * frac_year
            annual_inputs += input_c * frac_year
    final_stock = max(0.0, active + slow)
    delta_pct = (final_stock - initial_stock) / max(initial_stock, 1.0) * 100.0
    return {
        "soc_initial_stock_kg_ha": initial_stock,
        "soc_final_stock_kg_ha": final_stock,
        "soc_change_pct": delta_pct,
        "soc_residue_input_kg_ha": annual_inputs / years,
        "soc_horizon_years": float(years),
    }


class YieldWaterInputs(TypedDict):
    water_stress_fraction: float
    heat_degree_days: float
    waterlogging_days: float


def yield_adjustment(crop: CropV2, water: YieldWaterInputs, field: FieldV2) -> dict[str, float]:
    water_penalty = _clamp(water["water_stress_fraction"] * (1.0 - 0.45 * crop.drought_tolerance) * crop.yield_stress_sens_water)
    heat_window_penalty = _clamp((water["heat_degree_days"] / max(1.0, crop.duration_days * 3.0)) * crop.yield_stress_sens_heat)
    flood_penalty = _clamp(water["waterlogging_days"] / max(1, crop.duration_days) * (1 - crop.waterlogging_tolerance))
    salinity = field.soil.ec_ds_m or 0.0
    salinity_penalty = _clamp(max(0.0, salinity - 2.0) / 8.0 * (1 - crop.salinity_tolerance))
    total = _clamp(1 - (0.55 * water_penalty + 0.25 * heat_window_penalty + 0.12 * flood_penalty + 0.08 * salinity_penalty))
    return {
        "water_penalty": water_penalty,
        "heat_penalty": heat_window_penalty,
        "flood_penalty": flood_penalty,
        "salinity_penalty": salinity_penalty,
        "yield_factor": total,
        "climate_adjusted_yield_kg_ha": crop.yield_kg_ha * total,
    }


def soil_indicators(rotation: tuple[CropV2, ...], field: FieldV2, soc_horizon_years: int = 3) -> dict[str, float]:
    soil = field.soil
    n_fix_fraction = sum(1 for c in rotation if c.n_fixing) / max(1, len(rotation))
    residue = sum(c.residue_score for c in rotation) / max(1, len(rotation))
    family_div = len({c.family for c in rotation}) / max(1, len(rotation))
    cover = min(1.0, sum(c.duration_days for c in rotation) / 365)
    ph_center = soil.ph if soil.ph is not None else 6.5
    ph_suitable = sum(1 for c in rotation if c.pH_range[0] <= ph_center <= c.pH_range[1]) / max(1, len(rotation))

    n_demand = sum(c.n_demand_kg_ha for c in rotation)
    p_demand = sum(c.p_demand_kg_ha for c in rotation)
    k_demand = sum(c.k_demand_kg_ha for c in rotation)

    n_supply = nutrient_stock_kg_ha(soil.total_n_mgkg, field, soil.n_mineralization_fraction) / soil.nutrient_profile_years
    p_supply = nutrient_stock_kg_ha(soil.available_p_mgkg, field, soil.p_available_fraction) / soil.nutrient_profile_years
    k_supply = nutrient_stock_kg_ha(soil.exchangeable_k_mgkg, field, soil.k_available_fraction) / soil.nutrient_profile_years
    # Agronomic proxy: biological N fixation is expressed in kg N/ha, not mixed with concentration units.
    n_fix_kg_ha = sum(min(60.0, 0.8 * c.n_demand_kg_ha) for c in rotation if c.n_fixing)
    n_balance = n_supply + n_fix_kg_ha - n_demand
    p_balance = p_supply - p_demand
    k_balance = k_supply - k_demand

    soc = soil_carbon_trajectory(rotation, field, soc_horizon_years)
    return {
        "soc_baseline_pct": soil.soc_pct if soil.soc_pct is not None else 0.0,
        "soc_change_proxy_pct": soc["soc_change_pct"],
        "soc_initial_stock_kg_ha": soc["soc_initial_stock_kg_ha"],
        "soc_final_stock_kg_ha": soc["soc_final_stock_kg_ha"],
        "nitrogen_balance_proxy": n_balance,
        "nitrogen_supply_kg_ha": n_supply,
        "nitrogen_fixation_kg_ha": n_fix_kg_ha,
        "phosphorus_balance_proxy": p_balance,
        "potassium_balance_proxy": k_balance,
        "pH_suitability": ph_suitable,
        "salinity_risk": _clamp(max(0.0, (soil.ec_ds_m or 0.0) - 2.0) / 8.0),
        "water_holding_capacity_mm": sum(soil_water_capacity(field, c.root_depth_m) for c in rotation) / max(1, len(rotation)),
        "legume_fraction": n_fix_fraction,
        "residue_score": residue,
        "family_diversity": family_div,
        "ground_cover_fraction": cover,
        "disease_break_value": sum(c.family_break_value for c in rotation) / max(1, len(rotation)),
    }
