# V3 response to the V2 deep audit

## Confirmed bugs

| Audit item | V3 status | Implementation |
|---|---|---|
| B1 rank_p90 | FIXED | rank samples are the source of rank_p90; score percentiles are only used for score p10/p50/p90 |
| B2 rotation duplicate/dead traversal | FIXED | preferred-first ordering without duplicate traversal or impossible branch |
| B3 POWER single missing value | FIXED | per-parameter gap interpolation + retry + disk cache; irrecoverable parameters still fail explicitly |
| B4 irrigation water disappearance | FIXED | gross irrigation, effective irrigation, reliability loss, runoff, drainage, storage and balance invariant |
| B5 nutrient unit mismatch | FIXED | mg/kg -> kg/ha conversion using bulk density and soil depth, with explicit availability fractions |
| B6 silent remote 0.5 injection | FIXED | missing remote values are omitted from indicator bundles; scoring renormalizes available feature weights |

## Science upgrades

| Audit item | V3 status | Notes |
|---|---|---|
| S1 parameter uncertainty | FIXED at engine level | true input Monte Carlo over crop, soil, Kc, root depth, economic and irrigation parameters |
| S2 min-max rank reversal | FIXED | absolute scales are stored in the V3 config |
| S3 dimension collinearity | ADDRESSED | duplicated features were removed from several dimensions; still suitable for future covariance analysis |
| S4 static soil health | ADDRESSED | explicit multi-year two-pool SOC trajectory proxy |
| S5 narrow rotation space | PARTLY ADDRESSED | max sequence is configurable and multi-year calendar windows are supported; intercropping remains a future model extension |
| S6 synthetic weather | ADDRESSED | year-specific anomalies, persistence, heat events and dry spells added; still synthetic |
| S7 water simplifications | SUBSTANTIALLY ADDRESSED | SCS-CN, drainage, paddy outflow, SMAP initialization, conservation checks; dual-Kc/groundwater still future work |
| S8 no calibration | NOT SOLVED BY CODE | golden ET0 test + physics invariants added; real yield/soil calibration requires observations |
| S9 NASA usage | ADDRESSED | POWER drives weather, GPM rainfall, SMAP initialization/validation, HLS stability evidence, MODIS ET consistency, NEX scenarios |
| S10 economics | ADDRESSED | price-yield correlation proxy, sampled cost inflation, risk tolerance, budget/labour/water constraints |

## Engineering/product gaps

| Audit item | V3 status |
|---|---|
| E1 product/API/UI | FIXED |
| E2 packaging/reproducibility | FIXED: pyproject + pinned API lockfile + Docker |
| E3 CI/lint/type tooling | CONFIGURED: GitHub Actions + ruff + mypy; local network was unavailable for installing ruff in this environment |
| E4 observability/data resilience | ADDRESSED: structured dataset registry, explicit fallback, NASA retry/cache; full production telemetry remains deployment-specific |
| E5 hard-coded locale | PARTLY ADDRESSED: units/currency config and API field overrides added; full i18n/offline PWA remains future work |
| E6 data access | ADDRESSED: GeoJSON FeatureCollection support + optional SoilGrids adapter |
| E7 tests | FIXED at regression/invariant level: 45 tests pass |

## Evidence boundary

V3 is materially more rigorous than V2, but no software change can create missing local calibration evidence. The repository therefore deliberately keeps local crop coefficients, long-term SOC calibration and multi-GCM validation as explicit evidence tasks.
