# FieldShift V3 architecture

```text
field / farmer / local soil
        +
NASA POWER / GPM / SMAP / HLS / MODIS / NEX-GDDP
        |
        v
provenance + cache + source registry
        |
        v
calendar-constrained rotation search
        |
        v
FAO-56 ET0 -> crop Kc -> SCS-CN runoff -> root-zone water balance
        |
        +--> yield/stress
        +--> nutrient/SOC trajectory
        +--> economics + operations
        +--> remote observation consistency
        |
        v
fixed physical/agronomic feature scales
        |
        +--> scenario scoring
        +--> Pareto/regret
        +--> input-parameter Monte Carlo
        |
        v
risk-adjusted ranking + evidence explanation
        |
        +--> JSON CLI
        +--> FastAPI
        +--> responsive web UI
```

The V3 kernel is intentionally a set of deterministic pure-ish transformations around explicit inputs so that tests can assert conservation and monotonicity properties.
