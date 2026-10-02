"""NASA AppEEARS point-sampling connector for satellite time-series evidence.

The connector is opt-in because NASA Earthdata credentials are required. It
discovers current AppEEARS product/layer versions at runtime so a retired
collection does not silently become a source of fabricated data.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import math
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, TypedDict

from .models import Provenance, RemoteDay
from .provenance import now_iso

APPEEARS_API = "https://appeears.earthdatacloud.nasa.gov/api/"
_TASK_LOCKS_GUARD = threading.Lock()
_TASK_LOCKS: dict[str, threading.Lock] = {}


class AppEEARSDataError(RuntimeError):
    """Raised when AppEEARS cannot provide an authenticated point sample."""


@dataclass(frozen=True)
class LayerSelection:
    source_key: str
    source_name: str
    product: str
    layer: str
    target: str
    resolution: str | None
    temporal_resolution: str | None


@dataclass(frozen=True)
class AppEEARSResult:
    remote: tuple[RemoteDay, ...]
    datasets: tuple[dict[str, Any], ...]


class SourceDefinition(TypedDict):
    key: str
    name: str
    product_ids: tuple[str, ...]
    layers: dict[str, tuple[str, ...]]
    source_type: str
    citation: str


SOURCE_DEFINITIONS: tuple[SourceDefinition, ...] = (
    {
        "key": "smap",
        "name": "NASA SMAP",
        "product_ids": ("SPL4SMGP.008", "SPL3SMP_E.006", "SPL3SMP.009"),
        "layers": {
            "smap_surface_m3_m3": ("sm_surface", "surface_soil_moisture"),
            "smap_rootzone_m3_m3": ("sm_rootzone", "rootzone_soil_moisture"),
            "smap_qa": ("retrieval_qual_flag",),
        },
        "source_type": "satellite",
        "citation": "https://nsidc.org/data/spl4smgp/versions/8",
    },
    {
        "key": "modis_et",
        "name": "NASA MODIS MOD16",
        "product_ids": ("MOD16A2GF.061", "MOD16A2.061"),
        "layers": {
            "modis_et_mm": ("ET_500m", "ET"),
            "modis_et_qc": ("ET_QC_500m",),
        },
        "source_type": "satellite",
        "citation": "https://doi.org/10.5067/MODIS/MOD16A2GF.061",
    },
    {
        "key": "hls_vi",
        "name": "NASA HLS",
        "product_ids": (),
        "layers": {
            "ndvi": ("NDVI",),
            "evi": ("EVI",),
            "ndmi": ("NDMI",),
            "hls_qa": ("QA", "Fmask"),
        },
        "source_type": "satellite",
        "citation": "https://doi.org/10.5067/HLS/HLSL30_VI.002",
    },
    {
        "key": "gpm",
        "name": "NASA GPM IMERG",
        "product_ids": (),
        "layers": {"gpm_rain_mm": ("precipitationCal", "precipitation", "precip")},
        "source_type": "satellite",
        "citation": "https://doi.org/10.5067/GPM/IMERGDF/DAY/07",
    },
)


def credentials_configured() -> bool:
    return bool(os.getenv("FIELD_SHIFT_APPEEARS_USER") and os.getenv("FIELD_SHIFT_APPEEARS_PASSWORD"))


def _safe_json_request(
    path: str,
    *,
    method: str = "GET",
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: int = 25,
) -> Any:
    headers = {"User-Agent": "FieldShift/3.1 NASA AppEEARS connector"}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if auth:
        basic = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode("ascii")
        headers["Authorization"] = f"Basic {basic}"
        headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8"
        body = b"grant_type=client_credentials"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{APPEEARS_API}{path.lstrip('/')}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        # Do not include request headers or credential-bearing request data in errors.
        detail = exc.read(512).decode("utf-8", "replace")
        raise AppEEARSDataError(f"AppEEARS returned HTTP {exc.code}: {detail[:300]}") from exc
    except Exception as exc:
        raise AppEEARSDataError(f"AppEEARS request failed: {type(exc).__name__}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppEEARSDataError("AppEEARS returned an invalid JSON response") from exc


def _download(path: str, token: str, timeout: int = 40) -> bytes:
    request = urllib.request.Request(
        f"{APPEEARS_API}{path.lstrip('/')}",
        headers={"Authorization": f"Bearer {token}", "User-Agent": "FieldShift/3.1 NASA AppEEARS connector"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as exc:
        raise AppEEARSDataError(f"AppEEARS file download failed: {type(exc).__name__}") from exc


def _product_matches(definition: SourceDefinition, product: dict[str, Any]) -> bool:
    product_id = str(product.get("ProductAndVersion", ""))
    if not product.get("Available", True) or product.get("Deleted", False):
        return False
    if product_id in definition["product_ids"]:
        return True
    lower_id = product_id.lower()
    description = str(product.get("Description", "")).lower()
    product_name = str(product.get("Product", "")).lower()
    if definition["key"] == "hls_vi":
        return "hls" in lower_id and ("_vi" in lower_id or "vegetation indices" in description)
    if definition["key"] == "gpm":
        return ("gpm" in lower_id or "imerg" in lower_id or "imerg" in product_name) and (
            "df" in lower_id or "daily" in description.lower()
        )
    return False


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _first_layer(layers: dict[str, Any], aliases: tuple[str, ...]) -> str | None:
    by_norm = {_norm(name): name for name in layers}
    for alias in aliases:
        exact = by_norm.get(_norm(alias))
        if exact:
            return exact
    return None


def discover_layers(token: str, timeout: int = 25) -> tuple[LayerSelection, ...]:
    products = _safe_json_request("product", token=token, timeout=timeout)
    if not isinstance(products, list):
        raise AppEEARSDataError("AppEEARS product catalog has an unexpected format")
    selected: list[LayerSelection] = []
    for definition in SOURCE_DEFINITIONS:
        candidates = [p for p in products if isinstance(p, dict) and _product_matches(definition, p)]
        # Prefer an exact supported product in the configured order. The API
        # catalog order is not a reliable indication of collection priority.
        priorities = {product_id: index for index, product_id in enumerate(definition["product_ids"])}
        candidates.sort(key=lambda p: priorities.get(str(p.get("ProductAndVersion", "")), len(priorities)))
        for product in candidates:
            product_id = str(product.get("ProductAndVersion", ""))
            layer_map = _safe_json_request(f"product/{urllib.parse.quote(product_id, safe='.')}", token=token, timeout=timeout)
            if not isinstance(layer_map, dict):
                continue
            found = []
            for target, aliases in definition["layers"].items():
                layer_name = _first_layer(layer_map, aliases)
                if layer_name:
                    found.append(LayerSelection(
                        source_key=definition["key"], source_name=definition["name"], product=product_id,
                        layer=layer_name, target=target,
                        resolution=product.get("Resolution"),
                        temporal_resolution=product.get("TemporalGranularity"),
                    ))
            targets = {x.target for x in found}
            if definition["key"] == "smap" and found:
                is_l4 = product_id.startswith("SPL4SMGP")
                has_rootzone = "smap_rootzone_m3_m3" in targets
                has_l3_quality = "smap_qa" in targets and product_id.startswith("SPL3")
                if has_rootzone or (is_l4 and "smap_surface_m3_m3" in targets) or has_l3_quality:
                    selected.extend(found)
                    break
                continue
            if definition["key"] == "modis_et" and found:
                if {"modis_et_mm", "modis_et_qc"}.issubset(targets):
                    selected.extend(found)
                    break
                continue
            selected.extend(found)
            if found and definition["key"] == "gpm" and "gpm_rain_mm" in targets:
                break
            if found and definition["key"] == "hls_vi" and {"ndvi", "evi"}.issubset(targets):
                break
    return tuple(selected)


def _cache_key(lat: float, lon: float, start: date, end: date) -> str:
    raw = f"{lat:.5f}|{lon:.5f}|{start.isoformat()}|{end.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _task_name(cache_key: str) -> str:
    """Keep the legacy stable name so already queued AppEEARS jobs are reused."""
    return f"fieldshift-{cache_key}"


def _task_is_reusable(task: dict[str, Any]) -> bool:
    """Reuse active tasks and unexpired bundles; avoid resubmitting failed jobs forever."""
    status = str(task.get("status", "")).lower()
    if status in {"pending", "processing"}:
        return True
    if status in {"error", "failed", "cancelled"}:
        return os.getenv("FIELD_SHIFT_APPEEARS_RETRY_FAILED", "").lower() not in {"1", "true", "yes"}
    expires_on = task.get("expires_on")
    if expires_on:
        try:
            expiry = datetime.fromisoformat(str(expires_on))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            return expiry > datetime.now(UTC)
        except ValueError:
            return False
    created = task.get("created")
    if created:
        try:
            created_at = datetime.fromisoformat(str(created))
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            return (datetime.now(UTC) - created_at).total_seconds() <= 30 * 86400
        except ValueError:
            return False
    return status == "done"


def _find_recent_task(
    token: str, task_name: str, selections: tuple[LayerSelection, ...], *, timeout: int,
) -> dict[str, Any] | None:
    """Find this AppEEARS request in the account task list after serverless cache loss.

    Vercel function files are not durable across instances. The AppEEARS task
    list is the authoritative fallback that prevents each analysis from creating
    another queued job and notification for the same field request.
    """
    limit = max(1, min(200, int(os.getenv("FIELD_SHIFT_APPEEARS_TASK_SCAN_LIMIT", "100"))))
    pages = max(1, min(10, int(os.getenv("FIELD_SHIFT_APPEEARS_TASK_SCAN_PAGES", "3"))))
    for page in range(pages):
        offset = page * limit
        tasks = _safe_json_request(
            f"task?task_type=point&limit={limit}&offset={offset}", token=token, timeout=timeout,
        )
        if not isinstance(tasks, list):
            raise AppEEARSDataError("AppEEARS task list returned an unexpected format")
        for task in tasks:
            if not isinstance(task, dict) or task.get("task_name") != task_name or not _task_is_reusable(task):
                continue
            params = task.get("params")
            existing_layers = params.get("layers") if isinstance(params, dict) else None
            if isinstance(existing_layers, list):
                requested = sorted((item.product, item.layer) for item in selections)
                available = sorted(
                    (str(item.get("product", "")), str(item.get("layer", "")))
                    for item in existing_layers if isinstance(item, dict)
                )
                if available and available != requested:
                    continue
            return task
        if len(tasks) < limit:
            break
    return None


def _task_lock(task_name: str) -> threading.Lock:
    """Serialize same-process submissions for one field request."""
    with _TASK_LOCKS_GUARD:
        return _TASK_LOCKS.setdefault(task_name, threading.Lock())


def _cache_paths(cache_dir: Path, key: str) -> tuple[Path, Path]:
    return cache_dir / f"appeears_{key}.json", cache_dir / f"appeears_{key}.pending.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            json.dump(payload, handle)
            tmp = Path(handle.name)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass


def _read_cache(path: Path, ttl: int) -> tuple[tuple[RemoteDay, ...] | None, float | None, dict[str, Any]]:
    try:
        age = max(0.0, time.time() - path.stat().st_mtime)
        if age > ttl:
            return None, age, {}
        envelope = json.loads(path.read_text(encoding="utf-8"))
        rows = envelope.get("remote", []) if isinstance(envelope, dict) else envelope
        out = []
        for row in rows:
            row["d"] = date.fromisoformat(row["d"])
            if row.get("provenance"):
                row["provenance"] = Provenance(**row["provenance"])
            out.append(RemoteDay(**row))
        statuses = envelope.get("dataset_statuses", {}) if isinstance(envelope, dict) else {}
        return tuple(out), age, statuses if isinstance(statuses, dict) else {}
    except (OSError, ValueError, TypeError, KeyError):
        return None, None, {}


def _date_value(value: str) -> date | None:
    clean = value.strip()
    try:
        return date.fromisoformat(clean)
    except (ValueError, TypeError):
        pass
    try:
        if len(clean) == 8 and clean.isdigit():
            return date(int(clean[:4]), int(clean[4:6]), int(clean[6:8]))
        month, day, year = clean.split("/")
        return date(int(year), int(month), int(day))
    except (ValueError, TypeError):
        pass
    return None


def _number(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if (
        not math.isfinite(number)
        or number in {-9999.0, -999.0, -32768.0, 32767.0, 32768.0, 65535.0}
        or 32761.0 <= number <= 32766.0
    ):
        return None
    return number


def _field_value(row: dict[str, str], layer: str) -> float | None:
    layer_key = _norm(layer)
    for name, value in row.items():
        name_key = _norm(name)
        if name_key == layer_key or name_key.endswith(layer_key):
            return _number(value)
    return None


def _quality_details(source_key: str, selections: tuple[LayerSelection, ...]) -> tuple[str, str]:
    selected = [x for x in selections if x.source_key == source_key]
    targets = {x.target for x in selected}
    if source_key == "modis_et":
        if "modis_et_qc" in targets:
            return "applied", "MOD16 ET_QC_500m was decoded; only observations with MODLAND_QC=0 were retained."
        return "unavailable", "The AppEEARS catalog did not expose ET_QC_500m; MOD16 ET observations are excluded."
    if source_key == "hls_vi":
        if "hls_qa" in targets:
            return "applied", "HLS QA was decoded; cloud, cloud-adjacent, shadow, snow/ice, water, and highest-aerosol pixels were excluded."
        return "provider_masked", "HLS VI processing masks cloud and cloud-shadow pixels; no separate HLS QA layer was returned to filter water, snow, or aerosol flags."
    if source_key == "smap":
        if "smap_qa" in targets and any(x.product.startswith("SPL3") for x in selected):
            return "applied", "SMAP retrieval_qual_flag was applied to L3 retrievals; only documented recommended-quality flags 0 or 8 were retained."
        if any(x.product.startswith("SPL4SMGP") for x in selected):
            return "product_level", "SPL4SMGP is an assimilated L4 geophysical estimate and does not provide the L2/L3 retrieval_qual_flag in the sampled fields. Values are not described as retrieval-flag filtered."
        return "unavailable", "A supported SMAP quality flag was not exposed; SMAP L3 moisture observations are excluded."
    if source_key == "gpm":
        return "product_level", "IMERG Final calibrated precipitation was selected; no separate AppEEARS pixel QA flag was applied."
    return "not_reported", "No product-specific quality handling is configured."


def _hls_clear(qa: float) -> bool:
    value = int(qa)
    # HLS QA bits 1-5 flag cloud, adjacency, shadow, snow/ice, and water;
    # bits 6-7 encode aerosol optical thickness, with 3 representing high AOT.
    return value >= 0 and (value & 0b00111110) == 0 and ((value >> 6) & 0b11) != 3


def _records_from_csv_files(
    files: list[tuple[str, bytes]], selections: tuple[LayerSelection, ...], retrieval_date: str,
    start: date, end: date,
) -> tuple[RemoteDay, ...]:
    grouped: dict[date, dict[str, list[float]]] = {}
    modis_period_days: dict[date, int] = {}
    for file_name, raw in files:
        if not file_name.lower().endswith(".csv"):
            continue
        try:
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            for row in reader:
                raw_date = row.get("Date") or row.get("date") or row.get("Day")
                day = _date_value(raw_date or "")
                if day is None or day < start or day > end:
                    continue
                row_values: dict[str, float] = {}
                for selection in selections:
                    product_key = _norm(selection.product)
                    file_key = _norm(file_name)
                    # AppEEARS creates a per-product file; when filenames omit the
                    # collection, a unique layer name remains a sufficient match.
                    layer_columns = [c for c in row if _norm(c) == _norm(selection.layer) or _norm(c).endswith(_norm(selection.layer))]
                    if not layer_columns:
                        continue
                    if product_key not in file_key and len(layer_columns) > 1:
                        continue
                    value = _field_value(row, selection.layer)
                    if value is None:
                        continue
                    row_values[selection.target] = value
                smap_is_l3 = any(x.source_key == "smap" and x.product.startswith("SPL3") for x in selections)
                if smap_is_l3:
                    smap_qa = row_values.get("smap_qa")
                    if smap_qa is None or int(smap_qa) not in {0, 8}:
                        row_values.pop("smap_surface_m3_m3", None)
                        row_values.pop("smap_rootzone_m3_m3", None)
                modis_selected = any(x.source_key == "modis_et" and x.target == "modis_et_mm" for x in selections)
                if modis_selected:
                    qc = row_values.get("modis_et_qc")
                    et = row_values.get("modis_et_mm")
                    # MODLAND_QC is bits 0-1 of ET_QC_500m. Missing QA must not
                    # silently turn a low-quality ET estimate into trusted evidence.
                    if et is not None and qc is not None and (int(qc) & 0b11) == 0:
                        row_values["modis_et_mm"] = et / 8.0
                        modis_period_days[day] = 8
                    else:
                        row_values.pop("modis_et_mm", None)
                if any(x.source_key == "hls_vi" for x in selections):
                    hls_values = {k: v for k, v in row_values.items() if k in {"ndvi", "evi", "ndmi"}}
                    if "hls_qa" in row_values and not _hls_clear(row_values["hls_qa"]):
                        for key in hls_values:
                            row_values.pop(key, None)
                    # Without the separate QA field, HLS VI cloud/shadow masking is
                    # still provider-applied; ancillary water/snow/aerosol checks are disclosed.
                values = grouped.setdefault(day, {})
                for target, value in row_values.items():
                    if target.endswith(("_qa", "_qc")):
                        continue
                    values.setdefault(target, []).append(value)
        except (UnicodeDecodeError, csv.Error):
            continue
    output: list[RemoteDay] = []
    for day, fields in sorted(grouped.items()):
        averages = {key: sum(vals) / len(vals) for key, vals in fields.items() if vals}
        if not averages:
            continue
        source_names = sorted({x.source_name for x in selections if x.target in fields})
        resolutions = sorted({x.resolution for x in selections if x.target in fields and x.resolution})
        provenance = Provenance(
            source="NASA AppEEARS point sample: " + ", ".join(source_names),
            source_type="satellite",
            retrieval_date=retrieval_date,
            spatial_resolution="mixed native pixels: " + ", ".join(resolutions) if resolutions else "native product pixels",
            temporal_resolution="product native interval",
            citation="https://appeears.earthdatacloud.nasa.gov/api/",
            confidence=0.80,
        )
        output.append(RemoteDay(
            d=day, source=provenance.source, provenance=provenance,
            modis_et_period_days=modis_period_days.get(day, 1), **averages,
        ))
    return tuple(output)


def _source_statuses(selections: tuple[LayerSelection, ...], status: str, coverage: str | None = None) -> list[dict[str, Any]]:
    records = []
    for definition in SOURCE_DEFINITIONS:
        found = [x for x in selections if x.source_key == definition["key"]]
        if not found:
            records.append({
                "name": definition["name"], "source_type": "satellite", "status": "not_configured",
                "coverage": coverage or "No matching supported product/layer is currently available from the AppEEARS catalog.",
                "setup_hint": "Check the current NASA AppEEARS product catalog and configure an Earthdata Login account for point sampling.",
            })
            continue
        records.append({
            "name": definition["name"], "source_type": "satellite", "status": status,
            "coverage": "; ".join(f"{x.product}/{x.layer} ({x.resolution or 'native'}, {x.temporal_resolution or 'native cadence'})" for x in found),
            "citation": definition["citation"],
        })
    return records


def appeears_point_timeseries(
    lat: float,
    lon: float,
    start: date,
    end: date,
    *,
    cache_dir: str | Path,
    timeout: int = 25,
    max_wait_seconds: int | None = None,
) -> AppEEARSResult:
    """Fetch available satellite point data using an Earthdata-authenticated task.

    Credentials are read only from server-side environment variables. The short
    lived AppEEARS token and job state are never returned in API responses.
    """
    if not credentials_configured():
        return AppEEARSResult((), tuple(_source_statuses((), "not_configured", "Earthdata credentials are not set in the Vercel server environment.")))
    if not -90 <= lat <= 90 or not -180 <= lon <= 180 or start > end:
        raise ValueError("invalid coordinate or date range for AppEEARS")
    max_days = max(30, min(730, int(os.getenv("FIELD_SHIFT_APPEEARS_MAX_DAYS", "366"))))
    if (end - start).days + 1 > max_days:
        start = date.fromordinal(end.toordinal() - max_days + 1)
    user = os.environ["FIELD_SHIFT_APPEEARS_USER"]
    password = os.environ["FIELD_SHIFT_APPEEARS_PASSWORD"]
    cache_root = Path(cache_dir)
    cache_key = _cache_key(lat, lon, start, end)
    cache_path, pending_path = _cache_paths(cache_root, cache_key)
    cache_ttl = max(60, int(os.getenv("FIELD_SHIFT_APPEEARS_CACHE_TTL_SECONDS", "604800")))
    cached, cache_age, cached_statuses = _read_cache(cache_path, cache_ttl)
    if cached is not None:
        cached_fields = {name for row in cached for name in ("smap_surface_m3_m3", "smap_rootzone_m3_m3", "modis_et_mm", "ndvi", "evi", "ndmi", "gpm_rain_mm") if getattr(row, name) is not None}
        cache_statuses = []
        for definition in SOURCE_DEFINITIONS:
            targets = {
                target for target in definition["layers"]
                if not target.endswith(("_qa", "_qc"))
            }
            if cached_fields & targets:
                stored = cached_statuses.get(definition["name"], {})
                cache_statuses.append({
                    "name": definition["name"], "source_type": "satellite", "status": "available",
                    "coverage": f"Cached NASA AppEEARS observations; {int(cache_age or 0)} seconds old.",
                    "retrieval_mode": "cache",
                    "quality_status": stored.get("quality_status", "legacy_unverified"),
                    "quality_note": stored.get("quality_note", "This older cache predates the current QA audit; product-specific filtering cannot be confirmed."),
                    "citation": definition["citation"],
                })
            else:
                cache_statuses.append({
                    "name": definition["name"], "source_type": "satellite", "status": "not_configured",
                    "coverage": "No observation from this source is present in the cached point sample.",
                })
        return AppEEARSResult(cached, tuple(cache_statuses))

    token_response = _safe_json_request("login", method="POST", auth=(user, password), timeout=timeout)
    token = token_response.get("token") if isinstance(token_response, dict) else None
    if not token:
        raise AppEEARSDataError("AppEEARS login did not return a bearer token; check the configured Earthdata credentials.")
    selections = discover_layers(token, timeout=timeout)
    if not selections:
        return AppEEARSResult((), tuple(_source_statuses(selections, "not_configured", "No supported SMAP, MODIS ET, HLS vegetation-index, or daily GPM layer was exposed by the current AppEEARS product catalog.")))
    task_name = _task_name(cache_key)
    task_id = ""
    with _task_lock(task_name):
        if pending_path.exists():
            try:
                pending = json.loads(pending_path.read_text(encoding="utf-8"))
                pending_name = pending.get("task_name")
                created = float(pending.get("created", 0))
                if (pending_name in (None, task_name)) and time.time() - created <= 7 * 86400:
                    task_id = str(pending["task_id"])
                else:
                    pending_path.unlink(missing_ok=True)
            except (OSError, ValueError, KeyError, TypeError):
                task_id = ""
        if not task_id:
            existing = _find_recent_task(token, task_name, selections, timeout=timeout)
            if existing is not None:
                task_id = str(existing.get("task_id", ""))
                if task_id:
                    _write_json(pending_path, {"task_id": task_id, "task_name": task_name, "created": time.time()})
        if not task_id:
            task_payload = {
                "task_type": "point",
                "task_name": task_name,
                "params": {
                    "dates": [{"startDate": start.strftime("%m-%d-%Y"), "endDate": end.strftime("%m-%d-%Y")}],
                    "layers": [{"product": x.product, "layer": x.layer} for x in selections],
                    "coordinates": [{"id": "field", "latitude": lat, "longitude": lon, "category": "field"}],
                },
            }
            task_response = _safe_json_request("task", method="POST", token=token, payload=task_payload, timeout=timeout)
            task_id = str(task_response.get("task_id", "")) if isinstance(task_response, dict) else ""
            if not task_id:
                raise AppEEARSDataError("AppEEARS did not return a task identifier.")
            _write_json(pending_path, {"task_id": task_id, "task_name": task_name, "created": time.time()})

    wait_seconds = max_wait_seconds if max_wait_seconds is not None else int(os.getenv("FIELD_SHIFT_APPEEARS_WAIT_SECONDS", "50"))
    wait_seconds = max(0, min(240, wait_seconds))
    deadline = time.monotonic() + wait_seconds
    task_status = "pending"
    while True:
        task = _safe_json_request(f"task/{urllib.parse.quote(task_id, safe='-')}", token=token, timeout=timeout)
        task_status = str(task.get("status", "unknown")).lower() if isinstance(task, dict) else "unknown"
        if task_status in {"done", "error", "failed", "cancelled"}:
            break
        if time.monotonic() >= deadline:
            return AppEEARSResult((), tuple(_source_statuses(selections, "pending", f"AppEEARS point-sample task is {task_status}; it will be resumed on the next analysis.")))
        time.sleep(min(5, max(1, deadline - time.monotonic())))
    if task_status != "done":
        pending_path.unlink(missing_ok=True)
        return AppEEARSResult((), tuple(_source_statuses(selections, "unavailable", f"AppEEARS task ended with status {task_status}; the analysis uses its existing clearly labelled fallback.")))

    bundle = _safe_json_request(f"bundle/{urllib.parse.quote(task_id, safe='-')}", token=token, timeout=timeout)
    bundle_files = bundle.get("files", []) if isinstance(bundle, dict) else []
    csv_files: list[tuple[str, bytes]] = []
    for item in bundle_files:
        if not isinstance(item, dict) or str(item.get("file_type", "")).lower() != "csv":
            continue
        file_id = str(item.get("file_id", ""))
        if file_id:
            csv_files.append((str(item.get("file_name", "")), _download(f"bundle/{task_id}/{urllib.parse.quote(file_id, safe='-')}", token)))
    retrieval_date = now_iso()
    remote = _records_from_csv_files(csv_files, selections, retrieval_date, start, end)
    pending_path.unlink(missing_ok=True)
    if remote:
        statuses = _source_statuses(
            selections,
            "available",
            f"{len(remote)} dated point-sample observations; native product dates are retained.",
        )
        for record in statuses:
            matched_definition = next((x for x in SOURCE_DEFINITIONS if x["name"] == record["name"]), None)
            if matched_definition is not None:
                record["quality_status"], record["quality_note"] = _quality_details(matched_definition["key"], selections)
        quality_metadata = {
            record["name"]: {"quality_status": record.get("quality_status"), "quality_note": record.get("quality_note")}
            for record in statuses
        }
        _write_json(cache_path, {"remote": [
            {**asdict(row), "d": row.d.isoformat(), "provenance": asdict(row.provenance) if row.provenance else None}
            for row in remote
        ], "dataset_statuses": quality_metadata})
        for record in statuses:
            matched_definition = next((x for x in SOURCE_DEFINITIONS if x["name"] == record["name"]), None)
            targets = {
                x.target for x in selections
                if matched_definition is not None and x.source_key == matched_definition["key"]
                and not (x.target.endswith("_qa") or x.target.endswith("_qc"))
            }
            if targets and not any(getattr(row, target) is not None for row in remote for target in targets):
                record["status"] = "unavailable"
                record["coverage"] = "The point sample contained no usable dated observations for this product; no values were imputed."
        return AppEEARSResult(remote, tuple(statuses))
    return AppEEARSResult((), tuple(_source_statuses(selections, "unavailable", "The completed AppEEARS task returned no usable dated pixel values; no satellite values were imputed.")))
