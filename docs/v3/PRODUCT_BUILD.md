# FieldShift V3.1 — Product Build

FieldShift V3.1 is the farmer-facing product layer built on the V3 scientific engine.

## Product flow

`Field → Evidence → Priorities → Strategies → Climate Lab → Decision Report`

## Product API

- `GET /api/demo` — reproducible Mymensingh demo snapshot
- `POST /api/field/preview` — field input validation/preview
- `POST /api/analysis/run` — run V3 analysis through the product contract
- `GET /api/analysis/{run_id}` — UI-ready analysis payload
- `GET /api/analysis/{run_id}/strategies`
- `GET /api/analysis/{run_id}/scenarios`
- `GET /api/analysis/{run_id}/evidence/{evidence_id}`
- `POST /api/analysis/{run_id}/what-if` — dry-water, reliability, and labour counterfactuals
- `GET /api/analysis/{run_id}/report` — report JSON

The legacy `/api/v3/*` endpoints remain available for V3 engine compatibility.

## UI characteristics

- Mobile-first responsive experience
- Field map with movable marker and simple boundary drawing
- Evidence/provenance drawer
- Farmer priority selection
- Rotation comparison cards
- Climate scenario lab
- Counterfactual what-if controls
- Decision report + JSON export + print path
- PWA shell caching for poor-connectivity environments
- Explicit evidence/fallback states; synthetic data is never silently represented as an observation

## Versioning

- Scientific engine: `3.0.0`
- Product/API layer: `3.1.0`

## Run locally

```bash
pip install -e '.[api]'
fieldshift-api
```

Then open `http://localhost:8000`.
