# FieldShift V3.1 Product Validation

Validation performed on the release candidate:

- **47 automated tests passed** (V2/V3 compatibility + product API tests).
- Product API flow passed: demo, field preview, analysis run, analysis retrieval, strategies, scenarios, evidence, report and what-if.
- FastAPI live server smoke test passed for `/health`, `/`, and `/api/demo`.
- Browser JavaScript syntax checked with Node.js: PASS.
- Product HTML feature-marker sanity check: PASS.
- Python source compilation: PASS.
- Setuptools wheel build: PASS.
- Wheel contains `index.html`, `manifest.json`, and `sw.js` static assets: PASS.
- Scientific V3 validation remains intact, including water-balance conservation and rank-p90 regression checks.

## Known demo limitation

The reproducible Mymensingh demo snapshot may contain synthetic/diagnostic fallback evidence when remote services are unavailable. The UI labels this explicitly rather than representing it as live observation. Live deployments should provide the configured NASA/remote datasets for an observation-rich evidence state.
