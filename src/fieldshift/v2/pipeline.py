from __future__ import annotations

import copy
import datetime as dt
import json
import math
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .agronomy import yield_adjustment
from .explain import explain
from .indicators import compute_rotation_indicators
from .models import (
    CropV2, EngineRun, FarmerContext, FieldV2, IndicatorBundle, Provenance,
    Rotation, Scenario, SoilProfile, Evaluation,
)
from .nasa import power_daily, load_gpm_csv, load_hls_csv, load_modis_et_csv, load_nex_gddp_csv, load_smap_csv
from .provenance import dataset_record, now_iso
from .rotation import generate_rotations, schedule
from .scoring import DEFAULT_DIMENSIONS, dimension_scores, rank_options, validate_weights
from .synthetic import generate_weather
from .validation import structural_validation, ablation_analysis

ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT / "config"


DEFAULT_WEIGHTS = {
    "soil_health": 0.10,
    "nutrient_balance": 0.08,
    "soil_water_resilience": 0.10,
    "irrigation_demand": 0.10,
    "drought_risk": 0.10,
    "flood_waterlogging_risk": 0.07,
    "heat_stress_risk": 0.08,
    "yield_potential": 0.10,
    "yield_stability": 0.08,
    "economic_return": 0.10,
    "operational_feasibility": 0.05,
    "rotation_diversity": 0.04,
}


def load_config(path: Path | None = None) -> dict[str, Any]:
    path = path or CONFIG_DIR / "region_mymensingh_v2.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_crops(path: Path | None = None) -> dict[str, CropV2]:
    path = path or CONFIG_DIR / "crops_v2.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["crops"]
    out = {}
    for cid, c in raw.items():
        hs = c.get("heat_sensitive_stage", {"label": "mid", "start": 0, "end": c["duration_days"]})
        out[cid] = CropV2(
            crop_id=cid, display_name=c["display_name"], family=c["family"], seasons=tuple(c["seasons"]),
            sowing_window=tuple(c["sowing_window"]), duration_days=c["duration_days"], stage_days=tuple(c["stage_days"]),
            kc_ini=c["kc"]["ini"], kc_mid=c["kc"]["mid"], kc_end=c["kc"]["end"], root_depth_m=c["root_depth_m"],
            heat_sensitive_stage=(hs["label"], int(hs["start"]), int(hs["end"])), heat_threshold_c=c["heat_threshold_c"],
            drought_tolerance=c["drought_tolerance"], waterlogging_tolerance=c["waterlogging_tolerance"],
            salinity_tolerance=c["salinity_tolerance"], n_fixing=bool(c["n_fixing"]), residue_score=c["residue_score"],
            yield_kg_ha=c["yield_kg_ha"], price_bdt_kg=c["price_bdt_kg"], cost_bdt_ha=c["cost_bdt_ha"],
            labour_person_days_ha=c["labour_person_days_ha"], n_demand_kg_ha=c.get("n_demand_kg_ha", 0),
            p_demand_kg_ha=c.get("p_demand_kg_ha", 0), k_demand_kg_ha=c.get("k_demand_kg_ha", 0),
            family_break_value=c.get("family_break_value", 0.5), pH_range=tuple(c["pH_range"]),
            rice_paddy=bool(c.get("rice_paddy", False)), standing_water_days=float(c.get("standing_water_days", 0)),
            percolation_mm_day=float(c.get("percolation_mm_day", 0)), seepage_mm_day=float(c.get("seepage_mm_day", 0)),
            yield_stress_sens_water=float(c.get("yield_stress_sens_water", 1.0)),
            yield_stress_sens_heat=float(c.get("yield_stress_sens_heat", 1.0)),
            source_refs=tuple(c.get("source_refs", [])), review_status=c.get("review_status", "placeholder"),
        )
    return out


def build_field(cfg: dict[str, Any], priorities: dict[str, float]) -> FieldV2:
    f = cfg["field"]
    s = f.get("soil", {})
    farmer_cfg = f.get("farmer", {})
    soil = SoilProfile(**s)
    farmer = FarmerContext(priorities=priorities, **{k: v for k, v in farmer_cfg.items() if k != "priorities"})
    field = FieldV2(field_id=f["field_id"], lat=f["lat"], lon=f["lon"], area_ha=f["area_ha"],
                    elevation_m=f.get("elevation_m", 20), land_type=f.get("land_type", "medium highland"),
                    soil=soil, irrigation_source=f.get("irrigation_source", "unknown"), farmer=farmer,
                    previous_crop=f.get("previous_crop"))
    field.validate()
    return field


def _load_optional_remote(input_dir: Path, datasets: list[dict]) -> tuple:
    remote = []
    loaders = [
        ("gpm.csv", load_gpm_csv), ("smap.csv", load_smap_csv), ("hls.csv", load_hls_csv), ("modis_et.csv", load_modis_et_csv)
    ]
    for filename, loader in loaders:
        p = input_dir / filename
        if p.exists():
            try:
                r = loader(p)
                remote.extend(r)
                source = r[0].source if r else filename
                prov = r[0].provenance
                datasets.append(dataset_record(filename, prov, f"{len(r)} daily/observation rows"))
            except Exception as exc:
                datasets.append({"name": filename, "status": "error", "error": str(exc)})
    # Merge by date later; duplicate fields from distinct NASA products are preserved by max-value merge.
    return tuple(remote)


def _merge_remote(rows) -> tuple:
    from .models import RemoteDay
    by = {}
    for x in rows:
        prev = by.get(x.d)
        if prev is None:
            by[x.d] = x
            continue
        kw = {}
        for k in ("ndvi", "evi", "ndmi", "smap_surface_m3_m3", "smap_rootzone_m3_m3", "modis_et_mm", "gpm_rain_mm"):
            val = getattr(x, k) if getattr(x, k) is not None else getattr(prev, k)
            kw[k] = val
        by[x.d] = RemoteDay(x.d, source=f"{prev.source}+{x.source}", provenance=prev.provenance, **kw)
    return tuple(sorted(by.values(), key=lambda x: x.d))


def load_scenarios(field: FieldV2, year: int, input_dir: Path | None, datasets: list[dict]) -> list[Scenario]:
    input_dir = input_dir or (ROOT / "data" / "v2")
    input_dir.mkdir(parents=True, exist_ok=True)
    baseline = None
    nasa_mode = os.getenv("FIELD_SHIFT_LIVE_NASA", "auto").lower()
    nasa_ok = nasa_mode not in {"0", "false", "off", "no"}
    if nasa_ok:
        try:
            baseline = power_daily(field.lat, field.lon, dt.date(year, 1, 1), dt.date(year + 2, 12, 31))
            datasets.append(dataset_record("NASA POWER", baseline[0].provenance, f"{len(baseline)} daily records"))
        except Exception as exc:
            datasets.append({"name": "NASA POWER", "status": "unavailable", "error": str(exc)})
    if baseline is None:
        baseline = generate_weather(year, field.lat, field.lon, field.elevation_m, seed=42)
        baseline = baseline + generate_weather(year + 1, field.lat, field.lon, field.elevation_m, seed=43) + generate_weather(year + 2, field.lat, field.lon, field.elevation_m, seed=44)
        p = Provenance(source="Field Shift synthetic weather", source_type="synthetic", temporal_resolution="daily", confidence=0.25)
        datasets.append(dataset_record("Synthetic fallback weather", p, f"{len(baseline)} daily records", "fallback"))

    remote_rows = _load_optional_remote(input_dir, datasets)
    remote = _merge_remote(remote_rows)
    scenarios = [Scenario("baseline", "Observed/NASA weather when available; synthetic is used only as a runnable fallback.", tuple(baseline), remote, baseline[0].source, [baseline[0].provenance] if baseline[0].provenance else [])]

    for name, ssp in (("ssp245_midcentury", "ssp245"), ("ssp585_midcentury", "ssp585")):
        path = input_dir / f"{ssp}.csv"
        if path.exists():
            try:
                w = load_nex_gddp_csv(path, ssp)
                scenarios.append(Scenario(name, f"NASA NEX-GDDP-CMIP6 {ssp} daily scenario", w, remote, w[0].source, [w[0].provenance]))
                datasets.append(dataset_record(f"NEX-GDDP-CMIP6 {ssp}", w[0].provenance, f"{len(w)} daily records"))
                continue
            except Exception as exc:
                datasets.append({"name": f"NEX-GDDP-CMIP6 {ssp}", "status": "error", "error": str(exc)})
        # Engine-ready diagnostic scenario when a projection file isn't present.
        delta_t = 1.6 if ssp == "ssp245" else 2.6
        rain_mult = 0.97 if ssp == "ssp245" else 0.92
        w = tuple(type(x)(x.d, x.tmax_c + delta_t, x.tmin_c + delta_t, x.rh_mean_pct,
                           x.wind_2m_ms, x.solar_rad_mj_m2_day, x.rain_mm * rain_mult,
                           f"diagnostic-delta:{ssp}", x.provenance) for x in baseline)
        p = Provenance(source=f"Diagnostic delta scenario {ssp}", source_type="estimated", temporal_resolution="daily", confidence=0.35)
        scenarios.append(Scenario(name, f"Diagnostic warming/rainfall stress scenario; replace with NEX-GDDP-CMIP6 file when available.", w, remote, "diagnostic-delta", [p]))
        datasets.append(dataset_record(f"Diagnostic scenario {ssp}", p, f"{len(w)} daily records", "fallback"))
    return scenarios


def _unique_rotations(crops: dict[str, CropV2], cfg: dict[str, Any], field: FieldV2, year: int) -> tuple[list[Rotation], list[dict[str, str]]]:
    generated = []
    seen = set()
    search = cfg.get("search", {})
    max_crops = int(search.get("max_sequence_length", 3))
    preferred = set(field.farmer.preferred_crops)
    for r in generate_rotations(crops, max_crops=max_crops, start_year=year, turnaround_days=int(cfg.get("constraints", {}).get("turnaround_days", 7)), preferred=preferred):
        if r.crop_ids not in seen:
            seen.add(r.crop_ids)
            generated.append(r)
    baseline_ids = tuple(cfg.get("baseline_rotation", []))
    if baseline_ids and baseline_ids not in seen:
        r = Rotation("BASELINE", baseline_ids, "Current/baseline practice", "baseline")
        generated.insert(0, r)
        seen.add(baseline_ids)
    accepted, rejected = [], []
    for r in generated:
        sch = schedule(r, crops, year, int(cfg.get("constraints", {}).get("turnaround_days", 7)), int(cfg.get("constraints", {}).get("max_cycle_days", 430)))
        if sch is None:
            rejected.append({"rotation_id": r.rotation_id, "reason": "calendar infeasible"})
            continue
        ok, reason = _hard_constraints(r, crops, field, sch)
        if ok:
            accepted.append(r)
        else:
            rejected.append({"rotation_id": r.rotation_id, "reason": reason})
    return accepted, rejected


def _hard_constraints(r: Rotation, crops: dict[str, CropV2], field: FieldV2, schedule_tuple) -> tuple[bool, str]:
    if field.soil.ph is not None:
        for cid in r.crop_ids:
            c = crops[cid]
            if not (c.pH_range[0] <= field.soil.ph <= c.pH_range[1]):
                return False, f"{cid}: pH suitability constraint failed"
    if field.land_type.lower().find("low") >= 0:
        for cid in r.crop_ids:
            if crops[cid].waterlogging_tolerance < 0.35:
                return False, f"{cid}: lowland/waterlogging constraint failed"
    return True, ""


def _scenario_cv(indicators_by_scenario: dict[str, dict[str, float]]) -> float:
    vals = [x.get("climate_adjusted_yield_kg_ha", 0.0) for x in indicators_by_scenario.values()]
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    if m <= 0:
        return 1.0
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))
    return sd / m


def run_v2(priorities: dict[str, float] | None = None, *, config_path: Path | None = None,
           input_dir: Path | None = None, year: int = 2026,
           n_weight_samples: int = 500, n_uncertainty_samples: int = 300) -> EngineRun:
    cfg = load_config(config_path)
    priorities = priorities or DEFAULT_WEIGHTS.copy()
    dimensions = tuple(cfg.get("dimensions", DEFAULT_DIMENSIONS))
    dimension_definitions = cfg.get("dimension_definitions")
    validate_weights(priorities, dimensions)
    crops = load_crops()
    field = build_field(cfg, priorities)
    datasets: list[dict] = []
    if input_dir:
        field_geo = input_dir / "field.geojson"
        soil_json = input_dir / "soil.json"
        if field_geo.exists():
            try:
                data = json.loads(field_geo.read_text(encoding="utf-8"))
                coords = []
                geom = data.get("geometry", data.get("features", [{}])[0].get("geometry", {}))
                if geom.get("type") == "Polygon":
                    coords = [(float(y), float(x)) for x, y in geom.get("coordinates", [[]])[0]]
                elif geom.get("type") == "MultiPolygon":
                    coords = [(float(y), float(x)) for x, y in geom.get("coordinates", [[[]]])[0][0]]
                if coords:
                    field.polygon = coords
                    field.lat = sum(p[0] for p in coords) / len(coords)
                    field.lon = sum(p[1] for p in coords) / len(coords)
                    datasets.append({"name": "field.geojson", "source_type": "farmer", "status": "available", "confidence": 0.95, "coverage": "field polygon centroid + boundary"})
            except Exception as exc:
                datasets.append({"name": "field.geojson", "status": "error", "error": str(exc)})
        if soil_json.exists():
            try:
                raw_soil = json.loads(soil_json.read_text(encoding="utf-8"))
                field.soil = SoilProfile(**raw_soil)
                datasets.append({"name": "soil.json", "source_type": "observed", "status": "available", "confidence": 0.95, "coverage": "field soil profile"})
            except Exception as exc:
                datasets.append({"name": "soil.json", "status": "error", "error": str(exc)})
    scenarios = load_scenarios(field, year, input_dir, datasets)
    rotations, rejected = _unique_rotations(crops, cfg, field, year)
    indicator_matrix: dict[str, dict[str, list[float]]] = {s.name: {} for s in scenarios}
    bundles: dict[str, dict[str, IndicatorBundle]] = {s.name: {} for s in scenarios}
    schedules = {}
    for r in rotations:
        sch = schedule(r, crops, year, int(cfg.get("constraints", {}).get("turnaround_days", 7)), int(cfg.get("constraints", {}).get("max_cycle_days", 430)))
        if sch is None:
            continue
        schedules[r.rotation_id] = sch
        for s in scenarios:
            values, _ = compute_rotation_indicators(r, sch, crops, s, field)
            bundles[s.name][r.rotation_id] = IndicatorBundle(r.rotation_id, s.name, values, {})
    # Cross-scenario indicators need scenario context (not one scenario in isolation).
    for rid in schedules:
        by_s = {s: bundles[s][rid].values for s in bundles}
        cv = _scenario_cv(by_s)
        for s in bundles:
            bundles[s][rid].values["scenario_yield_cv"] = cv
            # The current rotation's soil/economic inputs are not scenario-specific in reality,
            # but climate-adjusted production is; the scenario-specific net return is retained.
    for s in scenarios:
        arr = [bundles[s.name][rid].values for rid in schedules]
        ds = dimension_scores(arr, dimensions, dimension_definitions)
        indicator_matrix[s.name] = ds
    option_ids = list(schedules.keys())
    ranked = rank_options(option_ids, indicator_matrix, priorities, n_weight_samples, n_uncertainty_samples)
    ordered = ranked["ranked_ids"]

    # Baseline values for explanation.
    baseline_id = "BASELINE" if "BASELINE" in schedules else None
    baseline_values = bundles["baseline"][baseline_id].values if baseline_id else None
    evaluations = []
    for oid in ordered:
        scores = ranked["results"][oid]
        scenario_scores = {}
        for s in scenarios:
            dim = {d: indicator_matrix[s.name][d][option_ids.index(oid)] for d in dimensions}
            overall = sum(dim[d] * priorities[d] for d in dimensions)
            scenario_scores[s.name] = __import__("fieldshift.v2.models", fromlist=["ScenarioScore"]).ScenarioScore(s.name, dim, overall)
        robustness = __import__("fieldshift.v2.models", fromlist=["RobustnessResult"]).RobustnessResult(
            score_mean=scores["mean_score"], score_p10=scores["score_p10"], score_p50=scores["score_p50"],
            score_p90=scores["score_p90"], top1_probability=scores["top1_probability"], rank_mean=scores["rank_mean"],
            rank_p90=scores["rank_p90"], regret_max=scores["max_regret"], pareto_optimal=scores["pareto_optimal"], sensitivity={},
        )
        dim_mean = scores["dimension_scores"]
        ev = explain(next(r.label for r in rotations if r.rotation_id == oid), dim_mean,
                     bundles["baseline"][oid].values if "baseline" in bundles and oid in bundles["baseline"] else bundles[scenarios[0].name][oid].values,
                     baseline_values, scores["scenario_scores"], datasets)
        evaluations.append(Evaluation(next(r for r in rotations if r.rotation_id == oid), schedules[oid],
                                      {s: bundles[s][oid] for s in bundles}, scenario_scores, robustness, ev))
    validation = structural_validation(evaluations, dimensions)
    ablation = ablation_analysis(evaluations, priorities, "BASELINE") if evaluations else {}
    capabilities = [
        "NASA POWER daily weather ingestion by actual field latitude/longitude",
        "NASA GPM IMERG / SMAP / HLS / MODIS local-file ingestion adapters",
        "NASA NEX-GDDP-CMIP6 scenario ingestion adapter with diagnostic fallback",
        "FAO-56 Penman-Monteith ET0 and crop-stage Kc water physics",
        "root-zone water balance with texture/field-capacity/depletion logic",
        "paddy-specific standing-water/percolation/seepage terms",
        "phenology-aware heat-stress and climate-adjusted yield response",
        "soil nutrient/SOC/rotation proxy indicators",
        "automatic calendar-constrained rotation generation",
        "12-dimension configurable multi-objective scoring",
        "Pareto front, scenario regret and priority sensitivity",
        "parameter-level uncertainty envelope and rank stability",
        "ablation tests, provenance registry and evidence-grounded explanations",
    ]
    return EngineRun(
        engine_version="2.0.0",
        generated_at=now_iso(), field_id=field.field_id, objective_weights=priorities,
        scenarios=[s.name for s in scenarios], evaluations=evaluations, rejected=rejected,
        dataset_registry=datasets, validation=validation, ablation=ablation, system_capabilities=capabilities,
    )


def save_run(run: EngineRun, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(run), indent=2, default=str), encoding="utf-8")
