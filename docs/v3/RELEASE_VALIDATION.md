# FieldShift V3 — Release Validation

## Build identity

- Version: `3.0.0`
- V2 compatibility: retained under `fieldshift.v2`
- V3 production namespace: `fieldshift.v3`

## Validation executed in the release environment

### Test suite

```text
45 passed in 3.36s
```

The suite covers both the original V2 tests and the V3 regression/invariant suite.

### Compile check

```text
python -m compileall -q src tests tests_v2 tests_v3
PASS
```

### Installed-package CLI smoke test

The package was installed in editable mode with the existing local build toolchain (`--no-build-isolation --no-deps`) and the `fieldshift-v3` entrypoint executed successfully:

```text
FieldShift V3 3.0.0: 13 accepted rotations; validation=True
```

### API smoke test

- `GET /` → HTTP 200, bundled HTML returned
- `GET /health` → HTTP 200, engine `3.0.0`
- `GET /api/v3/config` → HTTP 200, 13 objective dimensions
- `GET /api/v3/demo` → HTTP 200, structural validation `True`, 13 evaluations

### Wheel/package-content check

A wheel was built successfully without network access and verified to contain:

- `fieldshift/v3/cli.py`
- `fieldshift/api/static/index.html`
- package metadata for `fieldshift 3.0.0`

### Deterministic test mode

CI tests set `FIELD_SHIFT_LIVE_NASA=0` so the test suite never depends on external network availability. NASA live ingestion remains available explicitly through `FIELD_SHIFT_LIVE_NASA=1`.

### Local-tool limitation

The release environment could not install `ruff` or `mypy` from the package index because external DNS/network access was unavailable. Their configuration and CI commands are present in `.github/workflows/ci.yml`, but the commands were not claimed as locally executed checks.

## Scientific validation observed in the smoke run

- Water-balance residual: approximately `1.25e-12 mm` in the generated V3 demo run.
- FAO-56 ET0 golden case is covered by regression testing.
- `rank_p90` is computed from rank samples, separate from score percentiles.
- Parameter uncertainty is propagated by rerunning the model with perturbed inputs rather than adding noise to final scores.

## Evidence boundary

The release does **not** claim that local agronomic calibration has been completed. The remaining external-evidence tasks are local yield validation, long-term SOC calibration, field validation of satellite residuals, and replacement of diagnostic climate deltas with a suitable multi-GCM ensemble.
