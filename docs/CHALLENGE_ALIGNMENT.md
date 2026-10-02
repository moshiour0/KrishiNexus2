# Field Shift challenge alignment

The challenge asks for an interactive decision-support tool combining NASA Earth observations, local soil information, crop characteristics, and farmer priorities to compare crop rotations for soil health and climate resilience.

## Implemented in the product

| Challenge need | Product implementation | Evidence shown to users |
|---|---|---|
| Explore crop rotations | Rotation generation, feasibility constraints, multi-indicator scoring, ranking, scenario comparison, and what-if reruns | Strategy cards, trade-offs, confidence, and caveats |
| Use NASA Earth observations | Vercel analysis requests NASA POWER daily weather by the selected coordinates; a source failure explicitly falls back to synthetic weather | Source status, date range, retrieval mode, and fallback are in the evidence trail |
| Include local soil information | Farmers can enter soil pH, organic carbon, and texture percentages; these values override the regional profile and affect the engine inputs | Farmer-entered values are identified by source and confidence; missing values use an explicitly labeled regional fallback |
| Represent crop characteristics | Versioned crop library contains seasons, crop coefficients, root depth, stress thresholds, yield/economic assumptions, and citations/review status | Assumptions and caveats remain part of the result |
| Reflect farmer priorities | Water, soil, income, yield, labour, and climate-risk presets are converted to engine weights | The UI shows active priorities and resulting strategy trade-offs |
| Address changing conditions | Baseline, NEX-GDDP-CMIP6 file inputs when supplied, and clearly labeled diagnostic stress scenarios are ranked | Scenario labels distinguish model data from diagnostic deltas |

## Additional safeguards

- The demo remains snapshot-based and works without a live data request.
- Live POWER requests use a seven-day cutoff for mixed-latency daily variables; future dates are generated as synthetic projections and labeled separately.
- Remote observation coverage is shown separately from POWER weather, so a live weather request is not confused with satellite field-observation coverage.
- A responsive installable web shell, uncertainty sampling, evidence provenance, and explicit fallback states are included.

## Limits that require real data or expert review

- The current crop and soil defaults are a Mymensingh, Bangladesh pilot. Selecting another location changes geospatial weather lookup but does not automatically provide a locally reviewed crop library or regional soil calibration.
- POWER data are daily and delayed, not an instantaneous real-time stream. NASA's reported typical latency is 2–3 days for meteorology and 5–7 days for solar parameters.
- GPM, SMAP, HLS, MODIS, and NEX-GDDP-CMIP6 are accepted through local data files; these products are not all fetched live by the web service.
- If no local soil values or supported soil source are supplied, the Mymensingh profile remains an estimate. Crop coefficients, yields, and prices still need local agronomic review.
- The diagnostic climate-delta paths are stress tests, not a substitute for multi-model climate projections. NEX-GDDP-CMIP6 data files can replace them when supplied.

This distinction prevents the demo from claiming locally validated recommendations where field data and regional review are absent.
