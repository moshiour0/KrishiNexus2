from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fieldshift.v3.pipeline import DEFAULT_WEIGHTS, run_v3

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = ROOT / "data" / "v3" / "fieldshift_v3_release_run.json"

_LOCK = threading.Lock()
_RUNS: dict[str, dict[str, Any]] = {}

DIMENSION_LABELS = {
    "soil_health": "Soil health",
    "nutrient_balance": "Nutrient balance",
    "soil_water_resilience": "Soil water resilience",
    "irrigation_demand": "Water demand",
    "drought_risk": "Drought resilience",
    "flood_waterlogging_risk": "Flood resilience",
    "heat_stress_risk": "Heat resilience",
    "yield_potential": "Yield potential",
    "yield_stability": "Yield stability",
    "economic_return": "Economic return",
    "operational_feasibility": "Operational feasibility",
    "rotation_diversity": "Rotation diversity",
    "observation_consistency": "Observation consistency",
}

SCENARIO_LABELS = {
    "baseline": ("Current reference", "Reference weather / evidence available to the run"),
    "ssp245_midcentury": (
        "SSP2-4.5 mid-century",
        "NASA NEX-GDDP-CMIP6 projection when connected; otherwise an explicitly labeled diagnostic stress test.",
    ),
    "ssp585_midcentury": (
        "SSP5-8.5 mid-century",
        "NASA NEX-GDDP-CMIP6 projection when connected; otherwise an explicitly labeled diagnostic stress test.",
    ),
}

PRIORITY_PRESETS = {
    "water": {
        "soil_water_resilience": 0.18,
        "irrigation_demand": 0.20,
        "drought_risk": 0.16,
        "flood_waterlogging_risk": 0.08,
        "soil_health": 0.08,
        "nutrient_balance": 0.06,
        "yield_potential": 0.07,
        "yield_stability": 0.07,
        "economic_return": 0.05,
        "operational_feasibility": 0.03,
        "rotation_diversity": 0.01,
        "observation_consistency": 0.01,
    },
    "soil": {
        "soil_health": 0.20,
        "nutrient_balance": 0.16,
        "soil_water_resilience": 0.13,
        "rotation_diversity": 0.12,
        "drought_risk": 0.08,
        "irrigation_demand": 0.07,
        "flood_waterlogging_risk": 0.05,
        "heat_stress_risk": 0.04,
        "yield_potential": 0.05,
        "yield_stability": 0.04,
        "economic_return": 0.04,
        "operational_feasibility": 0.01,
        "observation_consistency": 0.01,
    },
    "income": {
        "economic_return": 0.22,
        "yield_potential": 0.17,
        "yield_stability": 0.13,
        "operational_feasibility": 0.10,
        "irrigation_demand": 0.08,
        "drought_risk": 0.07,
        "soil_health": 0.05,
        "nutrient_balance": 0.04,
        "soil_water_resilience": 0.04,
        "rotation_diversity": 0.03,
        "flood_waterlogging_risk": 0.03,
        "heat_stress_risk": 0.03,
        "observation_consistency": 0.01,
    },
    "yield": {
        "yield_potential": 0.23,
        "yield_stability": 0.20,
        "drought_risk": 0.10,
        "heat_stress_risk": 0.08,
        "flood_waterlogging_risk": 0.06,
        "irrigation_demand": 0.08,
        "economic_return": 0.08,
        "soil_water_resilience": 0.05,
        "soil_health": 0.04,
        "nutrient_balance": 0.03,
        "operational_feasibility": 0.02,
        "rotation_diversity": 0.02,
        "observation_consistency": 0.01,
    },
    "labour": {
        "operational_feasibility": 0.25,
        "irrigation_demand": 0.13,
        "yield_stability": 0.10,
        "economic_return": 0.10,
        "soil_health": 0.08,
        "yield_potential": 0.08,
        "drought_risk": 0.07,
        "soil_water_resilience": 0.07,
        "nutrient_balance": 0.05,
        "rotation_diversity": 0.03,
        "flood_waterlogging_risk": 0.02,
        "heat_stress_risk": 0.01,
        "observation_consistency": 0.01,
    },
    "risk": {
        "drought_risk": 0.18,
        "flood_waterlogging_risk": 0.13,
        "heat_stress_risk": 0.14,
        "yield_stability": 0.15,
        "soil_water_resilience": 0.10,
        "irrigation_demand": 0.10,
        "soil_health": 0.06,
        "nutrient_balance": 0.03,
        "yield_potential": 0.03,
        "economic_return": 0.03,
        "operational_feasibility": 0.02,
        "rotation_diversity": 0.02,
        "observation_consistency": 0.01,
    },
}


def _normalise(weights: dict[str, float]) -> dict[str, float]:
    keys = list(DEFAULT_WEIGHTS)
    merged = {k: max(0.0, float(weights.get(k, DEFAULT_WEIGHTS[k]))) for k in keys}
    total = sum(merged.values()) or 1.0
    return {k: v / total for k, v in merged.items()}


def priorities_from_ui(payload: dict[str, Any]) -> dict[str, float]:
    raw = payload.get("priorities")
    if isinstance(raw, dict) and raw:
        return _normalise({str(k): float(v) for k, v in raw.items() if k in DEFAULT_WEIGHTS})
    selected = payload.get("priority_choices") or ["water", "soil", "income"]
    choices = [str(x) for x in selected if str(x) in PRIORITY_PRESETS]
    if not choices:
        choices = ["water", "soil", "income"]
    merged = {k: 0.0 for k in DEFAULT_WEIGHTS}
    for choice in choices:
        for key, value in PRIORITY_PRESETS[choice].items():
            merged[key] += value
    return _normalise(merged)


def _load_snapshot() -> dict[str, Any]:
    if not SNAPSHOT.exists():
        raise FileNotFoundError(f"Demo snapshot not found: {SNAPSHOT}")
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def _engine_run_to_dict(run: Any) -> dict[str, Any]:
    return json.loads(json.dumps(asdict(run), default=str))


def _scenario_meta(name: str) -> dict[str, str]:
    label, description = SCENARIO_LABELS.get(name, (name.replace("_", " ").title(), "Scenario"))
    return {"id": name, "label": label, "description": description}


def _field_context(field: dict[str, Any] | None, demo: bool = False) -> dict[str, Any]:
    field = field or {}
    lat = float(field.get("lat", 24.75))
    lon = float(field.get("lon", 90.41))
    area = float(field.get("area_ha", 0.4))
    farmer = field.get("farmer") or {}
    return {
        "id": field.get("field_id", "mymensingh_demo_v3" if demo else f"field_{uuid.uuid4().hex[:8]}"),
        "location": {
            "lat": lat,
            "lon": lon,
            "label": field.get("label") or ("Mymensingh demo field" if demo else f"Field at {lat:.4f}, {lon:.4f}"),
        },
        "area_ha": area,
        "land_type": field.get("land_type", "medium highland"),
        "previous_crop": field.get("previous_crop", "Rice"),
        "soil_data_source": field.get("soil_data_source", "regional-defaults"),
        "soil_inputs": field.get("soil") or {},
        "constraints": {
            "water_available_mm_season": farmer.get("water_available_mm_season", 900),
            "irrigation_reliability": farmer.get("irrigation_reliability", 0.80),
            "budget_bdt_ha": farmer.get("budget_bdt_ha", 100000),
            "labour_available_person_days_ha": farmer.get("labour_available_person_days_ha", 120),
        },
        "data_state": "demo_snapshot" if demo else "analysis_input",
    }


def _evidence_state(lineage: list[dict[str, Any]], remote_coverage: float) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for record in lineage:
        name = record.get("name") or record.get("source") or "Evidence source"
        status = record.get("status", "available")
        source_type = record.get("source_type", "unknown")
        confidence = record.get("confidence")
        items.append({
            "id": hashlib.sha1(name.encode()).hexdigest()[:10],
            "name": name,
            "status": status,
            "source_type": source_type,
            "confidence": confidence,
            "coverage": record.get("coverage"),
            "retrieval_mode": record.get("retrieval_mode"),
            "data_start_date": record.get("data_start_date"),
            "data_end_date": record.get("data_end_date"),
            "fallback": record.get("fallback"),
            "error": record.get("error"),
            "setup_hint": record.get("setup_hint"),
            "quality_status": record.get("quality_status"),
            "quality_note": record.get("quality_note"),
            "retrieval_date": record.get("retrieval_date"),
            "temporal_resolution": record.get("temporal_resolution"),
            "spatial_resolution": record.get("spatial_resolution"),
            "citation": record.get("citation"),
        })
    usable = [i for i in items if i["status"] in {"available", "partial", "stale"}]
    satellite_sources = sum(1 for i in usable if i["source_type"] == "satellite")
    quality = "high" if satellite_sources >= 2 and remote_coverage > 0.5 else "moderate" if usable else "limited"
    return {"quality": quality, "coverage_fraction": remote_coverage, "items": items}


def _strategy_view(ev: dict[str, Any], rank: int) -> dict[str, Any]:
    base = ev["indicators_by_scenario"].get("baseline") or next(iter(ev["indicators_by_scenario"].values()))
    values = base.get("values", {})
    robust = ev["robustness"]
    scenarios = ev.get("scenario_scores", {})
    baseline_score = scenarios.get("baseline", {}).get("overall_score", robust.get("score_mean", 0.0))
    return {
        "id": ev["rotation"]["rotation_id"],
        "rank": rank,
        "label": ev["rotation"]["label"],
        "crop_ids": ev["rotation"].get("crop_ids", []),
        "timeline": ev.get("schedule", []),
        "baseline_score": baseline_score,
        "risk_adjusted_score": robust.get("risk_adjusted_score", 0.0),
        "score_range": [robust.get("score_p10", 0.0), robust.get("score_p90", 0.0)],
        "top1_probability": robust.get("top1_probability", 0.0),
        "rank_range": [robust.get("rank_mean", 0.0), robust.get("rank_p90", 0.0)],
        "pareto_optimal": bool(robust.get("pareto_optimal", False)),
        "metrics": {
            "water_mm": values.get("irrigation_mm"),
            "effective_water_mm": values.get("irrigation_effective_mm"),
            "soil_change_pct": values.get("soc_change_proxy_pct"),
            "yield_kg_ha": values.get("climate_adjusted_yield_kg_ha"),
            "yield_factor": values.get("yield_factor"),
            "net_return_bdt_ha": values.get("net_return_bdt_ha"),
            "labour_days_ha": values.get("labour_total_person_days_ha"),
            "water_stress": values.get("water_stress_fraction"),
            "heat_stress_days": values.get("heat_stress_days"),
            "waterlogging_days": values.get("waterlogging_days"),
            "observation_consistency": scenarios.get("baseline", {}).get("dimension_scores", {}).get("observation_consistency", 0.0),
        },
        "dimensions": scenarios.get("baseline", {}).get("dimension_scores", {}),
        "scenario_scores": {k: v.get("overall_score") for k, v in scenarios.items()},
        "explanation": ev.get("explanation", {}),
    }


def _make_product_response(run: dict[str, Any], field: dict[str, Any] | None, *, demo: bool = False, mode: str = "live") -> dict[str, Any]:
    evaluations = run.get("evaluations", [])
    if not evaluations:
        raise ValueError("No viable rotation strategies were produced")
    strategies = [_strategy_view(ev, i + 1) for i, ev in enumerate(evaluations[:8])]
    top = strategies[0]
    first_exp = evaluations[0].get("explanation", {})
    lineage = first_exp.get("data_lineage", [])
    remote_coverage = float((evaluations[0].get("indicators_by_scenario", {}).get("baseline", {}) or {}).get("values", {}).get("remote_observation_coverage_fraction", 0.0))
    evidence = _evidence_state(lineage, remote_coverage)
    baseline = evaluations[0].get("indicators_by_scenario", {}).get("baseline", {}).get("values", {})
    water_score = top["dimensions"].get("irrigation_demand", 0.0)
    drought_score = top["dimensions"].get("drought_risk", 0.0)
    soil_score = top["dimensions"].get("soil_health", 0.0)
    heat_score = top["dimensions"].get("heat_stress_risk", 0.0)
    field_ctx = _field_context(field, demo=demo)
    quality_text = {
        "high": "Strong multi-source evidence",
        "moderate": "Mixed evidence coverage",
        "limited": "Limited remote evidence; results rely more on modeled or synthetic inputs",
    }[evidence["quality"]]
    robustness = "high" if top["top1_probability"] >= 0.65 and top["rank_range"][1] <= 3 else "moderate" if top["top1_probability"] >= 0.35 else "limited"
    return {
        "run": {
            "id": run.get("run_id") or f"run_{uuid.uuid4().hex}",
            "engine_version": run.get("engine_version", "3.0.0"),
            "generated_at": run.get("generated_at"),
            "mode": mode,
            "status": "complete",
        },
        "field": field_ctx,
        "data_quality": {
            "label": quality_text,
            "level": evidence["quality"],
            "coverage_fraction": evidence["coverage_fraction"],
            "remote_observation_coverage": remote_coverage,
            "validation": run.get("validation", {}),
        },
        "field_snapshot": {
            "water_pressure": {"value": round(1.0 - water_score, 3), "label": "Water pressure", "interpretation": "Lower pressure means lower modeled irrigation demand relative to the configured scale."},
            "drought_resilience": {"value": drought_score, "label": "Drought resilience", "interpretation": "Based on modeled water stress and dry-spell exposure."},
            "soil_resilience": {"value": soil_score, "label": "Soil resilience", "interpretation": "Based on multi-year soil trajectory, residue, cover and pH suitability features."},
            "heat_resilience": {"value": heat_score, "label": "Heat resilience", "interpretation": "Based on simulated heat-stress exposure for the rotation."},
            "irrigation_mm": baseline.get("irrigation_mm"),
            "yield_kg_ha": baseline.get("climate_adjusted_yield_kg_ha"),
            "net_return_bdt_ha": baseline.get("net_return_bdt_ha"),
            "water_balance_error_mm": baseline.get("water_balance_error_mm"),
        },
        "priorities": run.get("objective_weights", DEFAULT_WEIGHTS),
        "strategies": strategies,
        "scenarios": [_scenario_meta(name) for name in run.get("scenarios", [])],
        "comparison": {
            "strategy_ids": [s["id"] for s in strategies[:4]],
            "headline_id": top["id"],
            "headline": f"{top['label']} is the highest risk-adjusted strategy in this run, but the result should be read with its evidence quality and trade-offs.",
            "tradeoffs": [
                {"label": "Water", "key": "water_mm", "unit": "mm/season", "lower_is_better": True},
                {"label": "Soil trajectory", "key": "soil_change_pct", "unit": "%", "lower_is_better": False},
                {"label": "Yield", "key": "yield_kg_ha", "unit": "kg/ha", "lower_is_better": False},
                {"label": "Net return", "key": "net_return_bdt_ha", "unit": "BDT/ha", "lower_is_better": False},
                {"label": "Labour", "key": "labour_days_ha", "unit": "days/ha", "lower_is_better": True},
            ],
        },
        "robustness": {
            "level": robustness,
            "top1_probability": top["top1_probability"],
            "rank_range": top["rank_range"],
            "score_range": top["score_range"],
            "uncertainty_type": top.get("explanation", {}).get("uncertainty_statement", "Input-parameter Monte Carlo"),
        },
        "explanation": {
            "headline": first_exp.get("headline"),
            "reasons": first_exp.get("top_dimensions", [])[:3],
            "caveats": first_exp.get("constraint_notes", []),
            "uncertainty_statement": first_exp.get("uncertainty_statement"),
        },
        "evidence": evidence,
        "provenance": run.get("dataset_registry", []),
        "limitations": run.get("scientific_notes", []),
        "validation": run.get("validation", {}),
        "system_capabilities": run.get("system_capabilities", []),
        "ablation": run.get("ablation", {}),
    }


def _run_engine(payload: dict[str, Any]) -> dict[str, Any]:
    priorities = priorities_from_ui(payload)
    field = payload.get("field") or {}
    farmer = field.setdefault("farmer", {})
    farmer.setdefault("water_available_mm_season", 900)
    farmer.setdefault("irrigation_reliability", 0.8)
    farmer.setdefault("budget_bdt_ha", 100000)
    farmer.setdefault("labour_available_person_days_ha", 120)
    result = run_v3(
        priorities=priorities,
        year=int(payload.get("year", 2026)),
        n_weight_samples=min(400, max(60, int(payload.get("n_weight_samples", 180)))),
        n_uncertainty_samples=min(120, max(20, int(payload.get("n_uncertainty_samples", 48)))),
        field_override=field,
    )
    data = _engine_run_to_dict(result)
    data["run_id"] = f"run_{uuid.uuid4().hex[:12]}"
    return data


def create_demo() -> dict[str, Any]:
    raw = _load_snapshot()
    raw["run_id"] = "demo_mymensingh_v3"
    with _LOCK:
        _RUNS[raw["run_id"]] = raw
    return _make_product_response(raw, None, demo=True, mode="demo_snapshot")


def create_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    raw = _run_engine(payload)
    with _LOCK:
        _RUNS[raw["run_id"]] = raw
    return _make_product_response(raw, payload.get("field"), demo=False, mode="live")


def get_analysis(run_id: str) -> dict[str, Any]:
    with _LOCK:
        raw = _RUNS.get(run_id)
    if raw is None and run_id == "demo_mymensingh_v3":
        raw = _load_snapshot()
        raw["run_id"] = run_id
    if raw is None:
        raise KeyError(run_id)
    return _make_product_response(raw, None, demo=run_id == "demo_mymensingh_v3", mode="demo_snapshot" if run_id == "demo_mymensingh_v3" else "live")


def get_strategy(run_id: str, strategy_id: str) -> dict[str, Any]:
    data = get_analysis(run_id)
    for strategy in data["strategies"]:
        if strategy["id"] == strategy_id:
            return strategy
    raise KeyError(strategy_id)


def get_evidence(run_id: str, evidence_id: str) -> dict[str, Any]:
    data = get_analysis(run_id)
    for item in data["evidence"]["items"]:
        if item["id"] == evidence_id:
            return item
    raise KeyError(evidence_id)


def what_if(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        base = get_analysis(run_id)
    except KeyError:
        # Serverless requests can land on different instances, so accept the
        # client-held field snapshot as the fallback source for what-if runs.
        base = None
    base_field = (base or {}).get("field") or payload.get("field")
    if not isinstance(base_field, dict) or not isinstance(base_field.get("location"), dict):
        raise KeyError(run_id)
    priorities = payload.get("priorities") or (base or {}).get("priorities") or DEFAULT_WEIGHTS
    field = {
        "field_id": base_field["id"],
        "lat": base_field["location"]["lat"],
        "lon": base_field["location"]["lon"],
        "area_ha": base_field["area_ha"],
        "land_type": base_field["land_type"],
        "previous_crop": base_field["previous_crop"],
        "farmer": base_field["constraints"],
    }
    scenario = payload.get("scenario")
    if scenario == "dry":
        field["farmer"]["water_available_mm_season"] = max(0.0, float(field["farmer"].get("water_available_mm_season", 900)) * 0.8)
    elif scenario == "reliability_low":
        field["farmer"]["irrigation_reliability"] = max(0.3, float(field["farmer"].get("irrigation_reliability", 0.8)) - 0.2)
    elif scenario == "labour_low":
        field["farmer"]["labour_available_person_days_ha"] = max(20.0, float(field["farmer"].get("labour_available_person_days_ha", 120)) * 0.7)
    return create_analysis({"field": field, "priorities": priorities, "year": int(payload.get("year", 2026)), "n_uncertainty_samples": 32, "n_weight_samples": 100})


def report(run_id: str) -> dict[str, Any]:
    return report_from_response(get_analysis(run_id))


def report_from_response(data: dict[str, Any]) -> dict[str, Any]:
    """Build a downloadable report from a client-held analysis response."""
    if not isinstance(data, dict) or not data.get("strategies"):
        raise ValueError("Analysis response is missing strategies")
    top = data["strategies"][0]
    return {
        "title": "FieldShift Decision Report",
        "generated_at": data["run"]["generated_at"],
        "field": data["field"],
        "evidence_quality": data["data_quality"],
        "priorities": data["priorities"],
        "primary_strategy": top,
        "alternatives": data["strategies"][1:4],
        "scenario_summary": [
            {
                "id": scenario["id"],
                "label": scenario["label"],
                "strategies": [
                    {"id": s["id"], "label": s["label"], "overall_score": s["scenario_scores"].get(scenario["id"])}
                    for s in data["strategies"][:4]
                ],
            }
            for scenario in data["scenarios"]
        ],
        "explanation": data["explanation"],
        "robustness": data["robustness"],
        "provenance": data["evidence"],
        "limitations": data["limitations"],
        "validation": data["validation"],
    }
