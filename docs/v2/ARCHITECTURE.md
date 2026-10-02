# Field Shift V2 architecture

## 1. Data layer

The engine treats data as typed observations with provenance. A feature can be:

- observed
- satellite-derived
- NASA model-derived
- farmer-entered
- literature-derived
- estimated
- synthetic

The source type and confidence travel with the run rather than disappearing after preprocessing.

## 2. NASA layer

### NASA POWER

Daily point data is requested at the actual field latitude/longitude for temperature, humidity, wind, solar radiation and precipitation. This removes the v0.1 hard-coded location dependency.

### GPM IMERG

Daily rainfall can override/augment the baseline precipitation stream when a GPM-derived time series is supplied.

### SMAP

Surface/root-zone moisture observations can constrain the root-zone state and provide an independent moisture signal.

### HLS

NDVI/EVI/NDMI observations provide a field-condition signal over the crop-active dates.

### MODIS ET

MOD16 ET provides an independent evapotranspiration signal that can be used as a cross-check and feature.

### NEX-GDDP-CMIP6

Future daily scenario files can be supplied to replace the diagnostic delta scenarios.

## 3. Agronomic simulation

The water model simulates daily crop demand using FAO-56 ET0 and the crop's stage-specific Kc curve. Rainfall is reduced by a runoff/infiltration heuristic; root-zone storage is tracked against total available water, and irrigation is applied subject to irrigation reliability. Rice adds standing-water losses for the configured standing-water period.

Heat stress is checked only inside the crop's configured sensitive phenological window. Water/flood/salinity stress factors are propagated into climate-adjusted yield before economic return is calculated.

## 4. Rotation generation

The engine performs a depth-first constrained sequence search over the crop library. It is not a fixed list of eight candidate rotations. The sequence length and turnaround rules are configuration, not code constants.

For large libraries, the search can be streamed rather than materialized all at once.

## 5. Decision dimensions

The default field pack uses:

1. soil health
2. nutrient balance
3. soil-water resilience
4. irrigation demand
5. drought risk
6. flood/waterlogging risk
7. heat-stress risk
8. yield potential
9. yield stability
10. economic return
11. operational feasibility
12. rotation diversity

Each dimension is a weighted set of measurable indicators. The definitions are YAML-configured so a new scientifically justified dimension can be added without editing the scoring code.

## 6. Robustness

A recommendation is never represented only by one weighted average. V2 also computes:

- scenario-specific scores
- maximum scenario regret
- Pareto membership
- priority-weight sensitivity
- uncertainty score envelope (P10/P50/P90)
- mean and high-percentile rank
- ablation tests

## 7. Explanation

Each evaluation carries the top decision dimensions, their supporting indicator values, scenario scores, baseline deltas and the dataset lineage used to generate the result.
