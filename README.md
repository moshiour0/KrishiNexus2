# FieldShift V3 — scientific decision-support engine

FieldShift V3 is the upgraded decision-support engine for NASA Space Apps 2026 “Field Shift: Adapting Farms with NASA Data”. V2 is retained for compatibility; the production path is now `fieldshift.v3`.

## V3 objective

V3 turns the original prototype into a reproducible, provenance-aware decision system with:

- absolute, auditable feature scales instead of candidate-set min/max normalization;
- input-parameter Monte Carlo uncertainty propagation instead of post-score jitter;
- conserved root-zone water accounting with SCS-CN runoff, gross/net irrigation, conveyance loss and deep drainage;
- unit-consistent soil nutrient stock conversion using bulk density and depth;
- a multi-year lightweight SOC trajectory proxy;
- budget, labour, water and farmer-avoidance constraints;
- real use of POWER, GPM, SMAP, HLS, MODIS and NEX-GDDP inputs when supplied;
- retry + cache + gap interpolation for NASA POWER;
- evidence-aware remote-observation scoring without silent 0.5/0 defaults;
- a FastAPI service, responsive web UI, Python package metadata, Docker image and CI definition;
- farmer-entered soil-test values that flow into the soil and rotation calculations, with explicit provenance;
- regression tests for the confirmed V2 bugs and physical invariants.

## Run locally

```bash
python -m pip install -e .
FIELD_SHIFT_LIVE_NASA=0 fieldshift-v3 --uncertainty-samples 64
```

The deterministic CI path disables live network access. For a live NASA POWER run:

```bash
FIELD_SHIFT_LIVE_NASA=1 fieldshift-v3
```

NASA POWER is queried through the official Daily API and cached under `data/v3/cache/` when network access is available.

## API + web app

```bash
python -m pip install -e '.[api]'
fieldshift-api
```

Open `http://localhost:8000` for the mobile-friendly demo UI.

Endpoints:

- `GET /health`
- `GET /api/v3/config`
- `GET /api/v3/demo`
- `POST /api/v3/run`

Example POST body:

```json
{
  "year": 2026,
  "n_weight_samples": 250,
  "n_uncertainty_samples": 48,
  "field": {
    "lat": 24.75,
    "lon": 90.41,
    "area_ha": 0.4,
    "farmer": {
      "irrigation_reliability": 0.8,
      "water_available_mm_season": 900
    }
  }
}
```

## Scientific model notes

### Water balance

For each crop and day the model tracks root-zone storage, effective rainfall, gross irrigation, effective irrigation, irrigation loss, runoff, deep drainage and final storage. A water-balance invariant is tested for every scenario.

SCS Curve Number is used for runoff. If no field curve number is provided, V3 estimates one from soil drainage/texture and records it as a modeled quantity. Paddy-specific percolation and seepage are explicit outflows rather than disappearing water.

SMAP root-zone observations, when available within ±7 days of sowing, are used to initialize root-zone water content; subsequent model-vs-SMAP residuals are reported separately.

### Nutrient balance

Soil concentrations in mg/kg are converted to kg/ha using bulk density and soil depth. Explicit availability/mineralization fractions are configuration parameters. Biological N fixation is also represented in kg N/ha. This is dimensionally consistent but remains a simplified nutrient budget until local field calibration is available.

### Soil carbon

V3 uses a lightweight two-pool trajectory proxy over an explicit multi-year horizon. It is intentionally identified as a proxy, not a calibrated RothC implementation.

### Decision scoring

Feature values are mapped to fixed physical/agronomic scales stored in `config/region_mymensingh_v3.yaml`. Scales do not depend on which candidates happen to be in a run, eliminating V2’s internal min/max rank-reversal mechanism.

Highly collinear V2 features were reduced: soil health no longer reuses disease-break value, nutrient balance no longer reuses legume fraction, yield potential no longer reuses yield factor, and yield stability now uses downside ratio + scenario CV + remote observations.

### Uncertainty

V3 samples crop yield/price, Kc, root depth, soil chemistry/physical properties and irrigation reliability, then reruns the indicator pipeline. Price/yield shocks share a configurable negative correlation and cost inflation is sampled as a common economic shock.

The reported `score_p10/p50/p90`, score standard deviation, top-1 probability and rank distribution are therefore based on input perturbation, not noise added after the score is calculated.

## NASA data roles

| Dataset | V3 role |
|---|---|
| NASA POWER | Weather driver for ET0 and water stress |
| NASA GPM IMERG | Replaces daily rainfall with satellite rainfall where supplied |
| NASA SMAP | Initial soil-moisture condition + model residual validation |
| NASA HLS | NDVI/NDMI observation evidence when available |
| NASA MODIS MOD16 | Model-vs-observed ET consistency |
| NASA NEX-GDDP-CMIP6 | Coordinate-matched daily files or optional server-side GEE multi-model monthly climate signals; diagnostic fallback stays clearly labeled |

## Optional SoilGrids integration

The V3 code includes an opt-in SoilGrids point adapter:

```bash
FIELD_SHIFT_SOILGRIDS=1 fieldshift-v3
```

When enabled, SoilGrids is used only when an explicit `data/v3/soil.json` is absent. The adapter marks values as model-derived, not field observations. ISRIC currently describes the REST API as beta and subject to downtime; the repository therefore does not silently depend on it for every run.

## Tests

```bash
FIELD_SHIFT_LIVE_NASA=0 python -m pytest -q
```

The V3 regression suite covers:

- rank-P90 correctness;
- absolute-score candidate-set invariance;
- NASA single-gap interpolation;
- water conservation;
- nutrient unit conversion;
- FAO-56 ET0 golden case;
- no silent remote 0.5 injection;
- parameter-level Monte Carlo dispersion;
- operational constraints;
- API health and demo route.

## V2 compatibility

The original V2 namespace and tests remain in place. New work should target `fieldshift.v3` and `run_v3.py`.

## Remaining evidence tasks

The codebase cannot manufacture local calibration data. Before field deployment, the remaining scientific evidence tasks are to calibrate crop coefficients/yield response against BBS/BRRI/BARI/farm observations, validate satellite residuals against local measurements, validate the SOC proxy against long-term field data, and replace the diagnostic climate deltas with an appropriate multi-GCM ensemble where available.

## Bangladesh data coverage and current integration boundary

The live weather request accepts a field coordinate anywhere in the NASA POWER service's global point coverage. The API stores a short-lived local cache, refreshes expired requests, and may use an explicitly marked stale cache if NASA is temporarily unavailable. Missing weather values are interpolated only below configured gap limits; larger gaps trigger the existing synthetic fallback and appear as unavailable in the evidence trail.

The crop and soil decision pack remains a Mymensingh pilot. A changed coordinate no longer inherits the Mymensingh soil profile: it uses field-entered soil values, a local `soil.json`, an explicitly enabled SoilGrids response, or a visibly incomplete profile. SoilGrids' REST endpoint is opt-in because ISRIC currently reports that the beta REST service is paused; see the [ISRIC service status and access notes](https://docs.isric.org/globaldata/soilgrids/).

SMAP, MODIS MOD16, and HLS vegetation indices now have an automatic NASA AppEEARS point-sampling connector. It discovers the currently offered collection/layers, submits one point task, resumes pending work on the next analysis, caches successful point samples for seven days, and reports missing or failed sources without filling them with invented satellite values. If a daily GPM IMERG product is available in the current AppEEARS catalog, the same connector discovers and samples it; otherwise GPM remains explicitly `not_configured` and POWER precipitation is the labeled fallback.

NASA NEX-GDDP-CMIP6 has two supported paths: a supplied daily CSV, or an optional authenticated Earth Engine connector. GEE summarizes the public `NASA/GDDP-CMIP6` collection at the selected field point, calculating equal-model monthly means for the historical period 1995–2014 and mid-century period 2041–2060 under SSP2-4.5 and SSP5-8.5. The differences/ratios are applied to a dated daily weather analogue so crop calendars remain aligned; this is a monthly climate-signal adjustment, **not a native daily future forecast**. The source reports retrieval/cache state and months whose rainfall signal could not be estimated. If GEE is unavailable, the explicitly labeled diagnostic scenarios remain non-NASA stress tests.

To enable Earth Engine, register an Earth Engine-enabled Google Cloud project, enable the Earth Engine API, and create a dedicated service account with the minimum required Earth Engine access. Set `FIELD_SHIFT_GEE_PROJECT` and the complete service-account JSON as the server-only Vercel secret `FIELD_SHIFT_GEE_SERVICE_ACCOUNT_JSON` for Preview and Production. Never expose this secret with a `NEXT_PUBLIC_`/browser variable or put it in the repository. The Python client initializes lazily; no Google credential is needed for the public NASA POWER/AppEEARS paths. The GEE point response is best-effort cached for seven days in the function cache; Vercel's temporary filesystem is not durable shared storage.

The curated source list, units, native cadence, quality handling, and explicit not-yet-integrated NASA candidates are in [`docs/v3/NASA_DATA_CATALOG.md`](docs/v3/NASA_DATA_CATALOG.md). “All NASA datasets” is not a finite agronomic scope; the product uses NASA observations and projections that bear directly on crop water, heat, vegetation, and soil-moisture decisions, and records source status instead of implying unavailable coverage.

To enable AppEEARS, set `FIELD_SHIFT_APPEEARS_USER` and `FIELD_SHIFT_APPEEARS_PASSWORD` as encrypted Vercel environment secrets for Preview and Production. These are your NASA Earthdata Login credentials; the server exchanges them for a short-lived AppEEARS token and never returns or logs that token. NASA Earthdata account access is required for point tasks. Successful samples currently use the Vercel function's cache directory, so add durable shared storage before treating this as unattended national ingestion. Review source-specific quality flags and run validation against Bangladesh field points before using satellite signals to change recommendation weights. The evidence panel and [Bangladesh readiness notes](docs/v3/BANGLADESH_DATA_READINESS.md) report what is connected in each deployment.

## V3.1 Product Experience

The V3 scientific engine now has a farmer-facing product layer following the FieldShift product architecture blueprint:

**Field → Evidence → Priorities → Strategies → Climate Lab → Decision Report**

Run the API with:

```bash
pip install -e '.[api]'
fieldshift-api
```

Open `http://localhost:8000` for the responsive web experience. Product endpoints live under `/api/analysis/*`; the legacy `/api/v3/*` endpoints remain available for compatibility.

## Vercel deployment

Import the GitHub repository with its root directory set to the repository root (the directory containing `vercel.json`, `api/`, `src/`, `config/`, and `data/`). Vercel serves the FastAPI app from `api/index.py`; `vercel.json` includes its runtime data and allows up to five minutes for analysis requests.

Live NASA POWER daily requests are attempted by default on Vercel, with an explicit synthetic-weather fallback if the upstream service is unavailable. These are daily, near-real-time inputs rather than an instantaneous feed; NASA reports typical latency of 2–3 days for meteorology and 5–7 days for solar parameters. Requests stop seven days behind the current date to avoid treating incomplete daily records as fresh; future weather in a multi-year analysis is labeled as a synthetic extension. Set `FIELD_SHIFT_LIVE_NASA=0` to force offline behavior. The POWER cache uses `/tmp/fieldshift_cache` on Vercel and may be recreated between serverless instances.

The field form accepts soil pH, soil organic carbon, and sand/silt/clay percentages from a farmer estimate or a soil-test report. Blank fields use the configured regional Mymensingh profile and are marked as estimated fallback evidence. If supplying texture, enter all three fractions; they must total approximately 100%.

After deployment, check `/health` and `/api/demo` on the deployment URL before running a new analysis.
