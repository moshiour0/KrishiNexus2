# V2 changelog

## v2.0.0

### Engine architecture
- Added an independent `fieldshift.v2` engine so v0.1 compatibility remains intact.
- Replaced fixed five-criterion scoring with config-driven decision dimensions.
- Added arbitrary dimension definitions through YAML, with per-feature weights and direction.
- Added provenance-aware typed models.

### NASA / Earth observation
- Added live NASA POWER Daily API adapter using the actual field coordinate.
- Added local ingestion adapters for GPM IMERG, SMAP, HLS and MODIS ET time series.
- Added NEX-GDDP-CMIP6 scenario loader.
- Added automatic live-NASA attempt with explicit fallback states.

### Agronomy / water
- Added root-zone water balance.
- Added texture/field-capacity/wilting-point storage logic.
- Added irrigation reliability.
- Added runoff/infiltration treatment instead of a fixed 80% rainfall multiplier.
- Added paddy standing-water, seepage and percolation terms.
- Added crop-specific root depth use.
- Added phenology-specific heat-sensitive windows.
- Added climate/water/heat/flood/salinity yield response.

### Rotation optimization
- Added depth-first automatic rotation generation.
- Baseline/current practice remains explicitly visible.
- Calendar and soil/land constraints are applied before simulation.
- Sequence length is configurable rather than hard-coded to eight rotations.

### Robust decision support
- Added 12 default decision dimensions.
- Added scenario scoring, Pareto analysis and max-regret.
- Added weight sensitivity.
- Added uncertainty score envelopes.
- Added ablation analysis.
- Added structured explanation and data lineage.

### Testing
- Retained all 19 v0.1 tests.
- Added 12 V2 tests covering dynamic dimensions, NASA adapter behavior, calendar rollover, baseline visibility, provenance and engine validation.
