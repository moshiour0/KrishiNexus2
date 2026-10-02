from __future__ import annotations

from typing import Any


def explain(
    rotation_label: str,
    dimension_scores: dict[str, float],
    indicator_values: dict[str, float],
    baseline_values: dict[str, float] | None,
    scenario_scores: dict[str, float],
    dataset_registry: list[dict[str, Any]],
    constraint_notes: list[str] | None = None,
) -> dict[str, Any]:
    baseline_values = baseline_values or {}
    deltas = {k: v - baseline_values[k] for k, v in indicator_values.items() if k in baseline_values and isinstance(v, (int, float))}
    dims = sorted(dimension_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    evidence = []
    for name, score in dims[:5]:
        evidence.append({"dimension": name, "normalized_score": score, "evidence_fields": _fields_for_dimension(name, indicator_values)})
    lineage = [x for x in dataset_registry if x.get("status") not in {"unused"}]
    return {
        "rotation": rotation_label,
        "headline": f"{rotation_label} is evaluated from multi-source agronomic, water, climate, economic and operational evidence.",
        "top_dimensions": evidence,
        "scenario_scores": scenario_scores,
        "baseline_deltas": deltas,
        "constraint_notes": constraint_notes or [],
        "data_lineage": lineage,
        "uncertainty_statement": "Ranking uncertainty is propagated from sampled crop, soil, agronomic and economic inputs; it is not a guarantee of field outcome.",
    }


def _fields_for_dimension(name: str, values: dict[str, float]) -> dict[str, float]:
    mapping = {
        "soil_health": ["soc_change_proxy_pct", "residue_score", "ground_cover_fraction", "disease_break_value", "pH_suitability"],
        "nutrient_balance": ["nitrogen_balance_proxy", "phosphorus_balance_proxy", "potassium_balance_proxy", "legume_fraction"],
        "soil_water_resilience": ["water_holding_capacity_mm", "mean_rootzone_moisture_fraction", "soil_water_deficit_mm", "mean_smap_rootzone_moisture"],
        "irrigation_demand": ["irrigation_mm", "irrigation_reliability_burden", "water_productivity"],
        "drought_risk": ["water_stress_fraction", "severe_water_stress_fraction", "max_consecutive_dry_days"],
        "flood_waterlogging_risk": ["waterlogging_days", "heavy_rain_days", "flood_exposure"],
        "heat_stress_risk": ["heat_stress_days", "heat_degree_days"],
        "yield_potential": ["climate_adjusted_yield_kg_ha", "yield_factor"],
        "yield_stability": ["scenario_yield_min_ratio", "scenario_yield_cv", "mean_hls_ndvi", "mean_hls_ndmi"],
        "economic_return": ["net_return_bdt_ha", "roi", "income_volatility_proxy"],
        "operational_feasibility": ["labour_peak_person_days_ha", "labour_total_person_days_ha", "calendar_margin_days", "market_access_burden"],
        "rotation_diversity": ["family_diversity", "disease_break_value", "legume_fraction"],
        "observation_consistency": ["model_vs_modis_et_error_pct", "smap_model_abs_error_m3_m3", "remote_observation_coverage_fraction"],
    }
    return {k: values[k] for k in mapping.get(name, []) if k in values}
