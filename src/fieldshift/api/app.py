from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fieldshift.api.product import (
    create_analysis,
    create_demo,
    get_analysis,
    get_evidence,
    get_strategy,
    report,
    report_from_response,
    what_if,
)
from fieldshift.v3.pipeline import DEFAULT_WEIGHTS, run_v3

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install FieldShift API dependencies with `pip install .[api]`.") from exc

APP_ROOT = Path(__file__).resolve().parent
app = FastAPI(
    title="FieldShift V3 Product API",
    version="3.1.0",
    description="Farmer-facing evidence-aware crop rotation decision support",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = APP_ROOT / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


def _jsonable(run) -> dict[str, Any]:
    return json.loads(json.dumps(asdict(run), default=str))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine": "3.0.0", "product": "3.1.0"}


@app.get("/api/v3/config")
def config() -> dict[str, dict[str, float]]:
    return {"default_weights": DEFAULT_WEIGHTS}


@app.get("/api/v3/demo")
def demo() -> dict[str, Any]:
    try:
        run_result = run_v3(n_weight_samples=80, n_uncertainty_samples=24)
        return _jsonable(run_result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/v3/run")
def run(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    priorities = payload.get("priorities")
    field_override = payload.get("field")
    year = int(payload.get("year", 2026))
    n_weight = min(1000, max(20, int(payload.get("n_weight_samples", 250))))
    n_uncertainty = min(300, max(8, int(payload.get("n_uncertainty_samples", 48))))
    try:
        run_result = run_v3(
            priorities=priorities,
            year=year,
            n_weight_samples=n_weight,
            n_uncertainty_samples=n_uncertainty,
            field_override=field_override,
        )
        return _jsonable(run_result)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/demo")
def product_demo() -> dict[str, Any]:
    try:
        return create_demo()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/field/preview")
def field_preview(payload: dict[str, Any]) -> dict[str, Any]:
    field = payload.get("field", payload)
    soil = field.get("soil") or {}
    lat = float(field.get("lat", 24.75))
    lon = float(field.get("lon", 90.41))
    pilot = abs(lat - 24.75) <= 0.15 and abs(lon - 90.41) <= 0.15
    return {
        "field": {
            "location": {"lat": lat, "lon": lon},
            "area_ha": float(field.get("area_ha", 0.4)),
            "soil_source": field.get("soil_data_source", "farmer-reported") if soil else "mymensingh-pilot-estimate" if pilot else "not-provided",
            "soil_inputs_provided": sorted(soil.keys()),
            "locally_validated": pilot,
        },
        "warnings": [] if pilot else ["Crop and soil recommendations outside the Mymensingh pilot are not locally validated."],
        "status": "ready",
    }


@app.post("/api/analysis/run")
def analysis_run(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return create_analysis(payload or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/analysis/{run_id}")
def analysis_get(run_id: str) -> dict[str, Any]:
    try:
        return get_analysis(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown analysis: {run_id}") from exc


@app.get("/api/analysis/{run_id}/strategies")
def analysis_strategies(run_id: str) -> dict[str, Any]:
    data = analysis_get(run_id)
    return {"strategies": data["strategies"]}


@app.get("/api/analysis/{run_id}/strategies/{strategy_id}")
def analysis_strategy(run_id: str, strategy_id: str) -> dict[str, Any]:
    try:
        return get_strategy(run_id, strategy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown strategy") from exc


@app.get("/api/analysis/{run_id}/scenarios")
def analysis_scenarios(run_id: str) -> dict[str, Any]:
    data = analysis_get(run_id)
    return {"scenarios": data["scenarios"], "strategies": data["strategies"]}


@app.get("/api/analysis/{run_id}/evidence/{evidence_id}")
def analysis_evidence(run_id: str, evidence_id: str) -> dict[str, Any]:
    try:
        return get_evidence(run_id, evidence_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown evidence item") from exc


@app.post("/api/analysis/{run_id}/what-if")
def analysis_what_if(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return what_if(run_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown analysis") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/analysis/{run_id}/report")
def analysis_report(run_id: str) -> dict[str, Any]:
    try:
        return report(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown analysis") from exc


@app.post("/api/analysis/{run_id}/report")
def analysis_report_from_client(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("run", {}).get("id") != run_id:
        raise HTTPException(status_code=400, detail="Report data does not match the requested analysis")
    try:
        return report_from_response(data)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (APP_ROOT / "static" / "index.html").read_text(encoding="utf-8")
