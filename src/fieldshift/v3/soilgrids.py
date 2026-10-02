from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from .models import Provenance, SoilProfile

SOILGRIDS_QUERY = "https://rest.isric.org/soilgrids/v2.0/properties/query"


class SoilGridsError(RuntimeError):
    pass


def query_soilgrids(lat: float, lon: float, *, timeout: int = 15) -> SoilProfile:
    """Fetch a point profile from SoilGrids v2 REST API.

    The adapter is opt-in because ISRIC currently labels the REST service beta/subject to downtime.
    Values are marked as model-derived rather than field observations.
    """
    params = [
        ("lon", f"{lon:.6f}"), ("lat", f"{lat:.6f}"),
        ("property", "bdod"), ("property", "soc"), ("property", "phh2o"),
        ("property", "nitrogen"), ("property", "sand"), ("property", "silt"), ("property", "clay"), ("property", "cec"), ("property", "wv003"), ("property", "wv1500"),
        ("depth", "0-5cm"), ("depth", "5-15cm"), ("depth", "15-30cm"), ("depth", "30-60cm"), ("depth", "60-100cm"),
        ("depth", "100-200cm"), ("value", "mean"),
    ]
    url = SOILGRIDS_QUERY + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"User-Agent": "FieldShift-V3/3.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise SoilGridsError(f"SoilGrids request failed: {exc}") from exc

    layers = payload.get("properties", {}).get("layers", [])
    data: dict[str, float] = {}
    for layer in layers:
        name = layer.get("name")
        depths = layer.get("depths") or []
        vals = []
        for depth in depths:
            values = depth.get("values", {})
            value = values.get("mean")
            if value is not None:
                vals.append(float(value))
        if vals:
            data[name] = sum(vals) / len(vals)

    def prov(name: str) -> Provenance:
        return Provenance(
            source=f"ISRIC SoilGrids 2.0 ({name})", source_type="modeled", retrieval_date=datetime.now(UTC).isoformat(),
            spatial_resolution="SoilGrids grid", temporal_resolution="static model product",
            citation="https://docs.isric.org/globaldata/soilgrids/", confidence=0.75,
        )

    # SoilGrids mapped-unit conventions are documented by ISRIC.
    bd = data.get("bdod")
    soc = data.get("soc")
    ph = data.get("phh2o")
    nitrogen = data.get("nitrogen")
    cec = data.get("cec")
    fc = data.get("wv003")
    wp = data.get("wv1500")
    sand = data.get("sand")
    silt = data.get("silt")
    clay = data.get("clay")
    prov_map = {name: prov(name) for name in data}
    return SoilProfile(
        bulk_density_g_cm3=bd / 100 if bd is not None else None,
        soc_pct=soc / 100 if soc is not None else None,
        ph=ph / 10 if ph is not None else None,
        total_n_mgkg=nitrogen * 10 if nitrogen is not None else None,
        cec_cmolkg=cec / 10 if cec is not None else None,
        sand_pct=sand / 10 if sand is not None else None,
        silt_pct=silt / 10 if silt is not None else None,
        clay_pct=clay / 10 if clay is not None else None,
        soil_depth_m=2.0,
        field_capacity_v_v=fc / 1000 if fc is not None else None,
        wilting_point_v_v=wp / 1000 if wp is not None else None,
        provenance=prov_map,
    )
