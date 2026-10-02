# FieldShift V3 — World-Class Product & Frontend Architecture Blueprint

**Status:** Architecture freeze / pre-implementation
**Scope:** Farmer-facing web application + judge/demo experience + trust/evidence layer
**Backend assumption:** FieldShift V3 engine and FastAPI API remain the scientific execution layer
**Primary goal:** Turn the V3 scientific engine into a decision-support product that a farmer can understand and a NASA Space Apps judge can verify in minutes.

---

## 1. Product North Star

FieldShift should not feel like a crop-ranking dashboard.

It should feel like a **field decision cockpit**:

> **See my field → understand current conditions → state my priorities → explore rotation strategies → stress-test them against climate/water conditions → understand the trade-offs → choose an action plan → retain the evidence trail.**

The UI must make the chain visible:

**NASA observations + local soil + crop traits + farmer constraints + climate scenarios**
→ **simulation**
→ **trade-offs**
→ **robustness / uncertainty**
→ **farmer decision**

The product should communicate *evidence before recommendation* and *trade-offs before a single score*.

---

## 2. Design Principles

### 2.1 Evidence-first
Every important number must answer:
- Where did this come from?
- When was it retrieved?
- Is it satellite, observed, modeled, farmer-provided, estimated, or synthetic?
- How confident are we?

### 2.2 Decision-first, not data-first
The farmer does not need to understand every model variable. The interface progressively reveals technical detail.

**Default:** simple explanation.
**Expand:** evidence and assumptions.
**Expert mode:** model diagnostics and full provenance.

### 2.3 No false precision
Never present a synthetic fallback as if it were an observation. Never use a score such as `0.817` as the primary visual message. Prefer ranges, trends, confidence language, and concrete units.

### 2.4 Show trade-offs
A strategy that saves water may reduce expected return. A rotation that improves soil may require more labour. The interface should expose those trade-offs rather than hide them inside one composite score.

### 2.5 Scenario-native
Climate adaptation is not a page at the end. Every major comparison can be viewed under:
- current/reference conditions
- dry-season stress
- heat stress
- heavy-rain/flood stress
- future climate scenario(s) when evidence is available

### 2.6 Mobile-first, judge-ready
The farmer experience must work at approximately 375px width first. The desktop version should become a richer analytical workspace, not a different product.

### 2.7 Progressive disclosure
Do not put map + 13 dimensions + charts + provenance + controls on one screen. Reveal complexity as the user asks for it.

### 2.8 Accessible by default
Large touch targets, readable type, high contrast, icon + text labels, no color-only encoding, keyboard support, screen-reader semantics, and plain-language explanations.

---

# 3. Experience Architecture

## 3.1 Primary user journeys

### Journey A — Farmer / guided mode

`Welcome`
→ `Find or define field`
→ `Field health snapshot`
→ `Farmer priorities`
→ `Rotation explorer`
→ `Climate stress test`
→ `Compare strategies`
→ `Decision summary`
→ `Save / export / share`

### Journey B — Judge / demo mode

`Demo field`
→ `Evidence appears`
→ `3–5 rotations`
→ `Change farmer priority`
→ `Stress-test climate`
→ `Inspect provenance`
→ `Open methodology`

The judge journey must reach the “aha” moment in under 90 seconds.

### Journey C — Agronomist / expert mode

`Field`
→ `Data quality`
→ `Model assumptions`
→ `Dimension breakdown`
→ `Scenario comparison`
→ `Uncertainty / sensitivity`
→ `Evidence lineage`
→ `Export technical report`

---

# 4. Information Architecture

```text
FieldShift
│
├── Home
│   ├── Start a field analysis
│   ├── Load demo field
│   └── How FieldShift works
│
├── Field workspace
│   ├── Field map
│   ├── Field profile
│   ├── Soil evidence
│   ├── NASA evidence
│   └── Data quality
│
├── Farmer priorities
│   ├── Water
│   ├── Soil health
│   ├── Income
│   ├── Yield stability
│   ├── Labour
│   └── Risk tolerance
│
├── Rotation Explorer
│   ├── Recommended strategies
│   ├── Trade-off cards
│   ├── Rotation timeline
│   ├── Dimension evidence
│   └── Strategy comparison
│
├── Climate Lab
│   ├── Baseline
│   ├── Hotter / drier stress
│   ├── Heavy-rain stress
│   ├── CMIP6 scenarios
│   └── Strategy robustness
│
├── Decision Report
│   ├── Selected strategy
│   ├── Why it fits
│   ├── What could change the result
│   ├── Action checklist
│   └── Evidence / provenance
│
└── Methodology
    ├── NASA datasets
    ├── Scientific model
    ├── Uncertainty
    ├── Limitations
    └── Citations
```

---

# 5. Screen Blueprint

## Screen 01 — Landing / Home

### Purpose
Immediately communicate what FieldShift does without looking like a generic sustainability site.

### Hero
**Headline:**
> Plan your next crop rotation for the field you actually farm.

**Subheadline:**
> FieldShift combines NASA Earth observations, local soil conditions, crop characteristics, and your priorities to explore resilient rotation strategies.

Primary CTA:
**Analyze my field**

Secondary CTA:
**Explore a NASA-powered demo**

### Hero visual
A real interactive field map / satellite-style visual, not a stock farm photograph.

Overlay three compact evidence chips:
- NASA weather
- Soil condition
- Crop strategy

### Trust strip
NASA Earth observations · Local soil data · Transparent assumptions · Uncertainty-aware results

---

## Screen 02 — Field Setup

### Layout
**Mobile:** stacked stepper.
**Desktop:** left input panel + right map.

### Step 1: Locate field
- Search location
- Latitude / longitude fallback
- Map click
- Polygon drawing for exact field boundary

### Step 2: Confirm field
Show:
- field area
- land type
- elevation
- likely climate zone

### Step 3: Soil
Three data states:

**Observed / uploaded**

**Remote / external estimate**

**Demo/default**

Never mix them silently.

Each soil field gets a provenance badge.

### Step 4: Farm constraints
- irrigation availability
- irrigation reliability
- labour availability
- budget
- market access
- previous crop

### Data-quality banner
Example:

> **Field confidence: Moderate**
> Soil depth was estimated; NASA weather evidence is available. Add a soil sample to improve the analysis.

---

# 6. Screen 03 — Field Health Snapshot

This is the first “NASA moment”.

Do not dump raw NASA variables.

Present four large indicators:

### Water
`Seasonal water pressure`

### Heat
`Heat-stress exposure`

### Soil
`Soil resilience potential`

### Vegetation
`Recent vegetation condition`

Each card contains:
- current interpretation
- small sparkline
- evidence badge
- “Why?” link

Example:

> **Water pressure: High**
> Recent rainfall is below the reference pattern while simulated crop demand remains high.
>
> `NASA POWER` · `GPM IMERG`

### “See evidence” drawer
Shows the raw series, observation dates, source and coverage.

---

# 7. Screen 04 — Farmer Priorities

This is a critical interaction.

Do not use abstract weight sliders as the only control.

Start with six plain-language priorities:

```text
What matters most for this field?

[ Save water ]
[ Protect soil ]
[ Keep income stable ]
[ Protect yield ]
[ Reduce labour ]
[ Reduce climate risk ]
```

Then convert selections into weights behind the scenes.

### Advanced mode
Expose explicit weight controls only when the user chooses “Custom priorities”.

### Live preview
As priorities change:

> “Your priorities now favour water-efficient rotations. Strategies that require heavy irrigation move down.”

This establishes causality instead of making rankings feel arbitrary.

---

# 8. Screen 05 — Rotation Explorer

This is the core product screen.

## Header

**Your field can be approached in several ways**

Subheader:
> Compare strategies instead of relying on a single score.

### Strategy cards
Each card contains:

**Rotation timeline**

`Rice → Lentil → Rice`

**Four headline measures**
- Water required
- Soil effect
- Yield stability
- Net return

**Robustness**

> Stable across 3 of 4 tested conditions

**Evidence state**

> High / Moderate / Limited evidence

### Do not make “score” the hero
Use the score only as a secondary analytical metric.

### Card action
**Compare strategy**

---

# 9. Strategy Comparison

Desktop layout:

```text
                 Strategy A    Strategy B    Strategy C
----------------------------------------------------------
Water demand        ███           ██            ████
Soil health         ████          ███           ███
Yield stability     ███           ████          ██
Income stability    ████          ███           ███
Labour              ██            ████          ███
Climate resilience  ████          ███           ████
```

Mobile:
Use a horizontal comparison rail with sticky strategy names.

### Required visualization
A **trade-off radar should NOT be the primary visualization**. Prefer horizontal bars because they remain interpretable on mobile and are easier to compare accurately.

### “What changes if I prioritize water?”
Provide an explicit priority toggle that re-runs the ranking and highlights only the changed dimensions.

---

# 10. Screen 06 — Climate Lab

This is the differentiating feature.

## Scenario selector

```text
Climate Lab

● Current reference
○ Hotter
○ Drier
○ Heavy rainfall
○ Future climate
```

### Main chart
For every selected rotation:

`performance → scenario`

Show:
- water requirement
- water stress
- yield ratio
- flood/waterlogging exposure
- economic outcome

### Robustness message
Avoid:

> “Rotation A wins.”

Prefer:

> **This strategy remains relatively stable across the tested scenarios.**

Then show the actual measurements.

### Scenario provenance
Each scenario gets a badge:

**Observed / NASA-derived**
**CMIP6**
**Diagnostic stress test**
**Synthetic fallback**

This is crucial for scientific honesty.

---

# 11. Screen 07 — “Why this strategy?”

The explanation engine becomes a visual reasoning system.

## Structure

### The headline
> **This strategy fits your priorities because it reduces irrigation pressure while maintaining relatively stable yield under the tested conditions.**

### Three strongest reasons
1. Lower water requirement
2. Better drought tolerance
3. More favourable nutrient balance

### Three caveats
1. Higher labour requirement
2. Sensitive to market price changes
3. Soil observation coverage is incomplete

### Counterfactual panel

> **What could change this result?**

Example:

> If irrigation reliability falls below ~50%, Strategy B becomes more competitive.

This is much more useful than a static score explanation.

---

# 12. Screen 08 — Evidence Drawer

Every recommendation must be inspectable.

### Evidence hierarchy

```text
RESULT
│
├── Dimension
│   ├── Feature
│   │   ├── Value
│   │   ├── Unit
│   │   ├── Source
│   │   ├── Retrieval date
│   │   └── Confidence
│   │
│   └── Model transformation
│
└── Assumption
```

### Example

**Irrigation demand**

`742 mm / season`

Source chain:

`NASA POWER rainfall`
→ `FAO-56 ET0`
→ `crop Kc`
→ `soil water balance`
→ `simulated irrigation`

The user can expand every step.

---

# 13. Screen 09 — Decision Report

This is the product output that can leave the app.

## Report structure

### Field
Map + location + field size

### Farmer objective
Priorities and constraints

### Recommended strategy set
Not merely one winner; show a primary strategy plus alternatives and trade-offs.

### Expected outcomes
- Water requirement
- Water stress
- Yield range
- Soil trajectory
- Economic range
- Labour requirement

### Climate robustness
Scenario table

### Confidence / evidence quality
Explicit data limitations

### Action checklist
Example:

`Before sowing`
`During season`
`After harvest`

### Methodology
Collapsed by default; fully expandable.

### Provenance
Machine-readable and human-readable.

---

# 14. Visual Design System

## 14.1 Brand character

The visual language should communicate:

**scientific + agricultural + calm + trustworthy + modern**

Avoid:
- generic SaaS gradients
- excessive glassmorphism
- cartoon farm illustrations
- “AI magic” aesthetics
- dense government-dashboard styling

## 14.2 Color semantics

Use semantic color roles, not decorative colors:

- Soil / organic matter
- Water
- Climate heat
- Risk
- Evidence / provenance
- Positive / stable
- Warning / uncertainty

The exact palette should be defined as design tokens and tested for WCAG contrast.

## 14.3 Typography

Use one highly legible UI family with:
- large mobile body text
- strong numerical hierarchy
- tabular numerals for metrics
- clear Bengali fallback font stack

## 14.4 Shape language

Rounded cards, but not excessive pill UI.

Cards should communicate hierarchy:
- primary decision card
- evidence card
- scenario card
- data-quality card

---

# 15. Component Architecture

```text
<AppShell>
  <TopBar />
  <RouteTransition />
  <Workspace>
    <FieldContextBar />
    <Page />
  </Workspace>
  <EvidenceDrawer />
  <ScenarioDrawer />
  <Help / Glossary />
</AppShell>
```

### Core components

```text
FieldMap
FieldBoundaryEditor
EvidenceBadge
DataQualityBadge
PrioritySelector
PriorityWeightEditor
MetricCard
TrendSparkline
ScenarioSelector
RotationTimeline
StrategyCard
StrategyCompareTable
TradeoffChart
RobustnessBadge
UncertaintyBand
DimensionBreakdown
WhyPanel
CounterfactualPanel
ProvenanceDrawer
MethodologyPanel
ReportPreview
ExportButton
```

Components must be data-driven and reusable. No page should contain bespoke chart markup for a single metric.

---

# 16. Frontend State Architecture

Separate state into four domains.

## A. Field state

```ts
field.location
field.boundary
field.soil
field.constraints
field.previousCrop
```

## B. Preference state

```ts
priorities
riskTolerance
selectedStrategies
activeScenario
viewMode
```

## C. Analysis state

```ts
runId
status
results
validation
provenance
uncertainty
```

## D. UI state

```ts
drawerOpen
selectedEvidence
expandedCards
compareMode
mobileSheet
```

Do not put all of these into one global mutable object.

---

# 17. Frontend ↔ API Contract

The current V3 `/api/v3/run` endpoint is a good engine bridge but is too raw for a production UI.

Introduce a **presentation API / BFF layer**.

```text
Browser
   ↓
Product API / BFF
   ↓
FieldShift V3 Engine
   ↓
NASA / soil / crop / scenario adapters
```

The BFF should return UI-ready structures rather than forcing the browser to understand engine internals.

## Example response shape

```json
{
  "run": {
    "id": "run_...",
    "engine_version": "3.x",
    "status": "complete"
  },
  "field": {},
  "data_quality": {},
  "evidence": {},
  "strategies": [],
  "scenarios": [],
  "comparison": {},
  "explanation": {},
  "provenance": [],
  "limitations": []
}
```

### Why this matters
The UI should not know that the backend uses dataclasses such as `RobustnessResult` or `IndicatorBundle`. Those are scientific domain objects, not presentation contracts.

---

# 18. API Endpoints for the Product Layer

Recommended surface:

```text
GET  /api/health
GET  /api/field/context
POST /api/field/preview
POST /api/analysis/run
GET  /api/analysis/{run_id}
GET  /api/analysis/{run_id}/strategies
GET  /api/analysis/{run_id}/strategies/{strategy_id}
GET  /api/analysis/{run_id}/scenarios
GET  /api/analysis/{run_id}/evidence/{evidence_id}
POST /api/analysis/{run_id}/what-if
GET  /api/analysis/{run_id}/report
```

Long-running analysis should support an asynchronous job model even if the first demo executes synchronously.

```text
queued → running → evidence_ready → simulation_ready → complete
```

---

# 19. Data Visualization Standards

## Use
- horizontal comparison bars
- line charts for time-series evidence
- uncertainty bands
- scenario slope charts
- field map layers
- small multiples for scenario comparison
- calendar/timeline views for rotations

## Avoid
- 3D charts
- gauges for scientific quantities
- pie charts for trade-offs
- unexplained radar charts
- color-only risk scales

Every chart gets:
- title
- unit
- time period
- source/evidence badge
- tooltip definition
- plain-language takeaway

---

# 20. Map Architecture

The map is a working analytical surface, not decoration.

### Layers

```text
Base map
├── Field boundary
├── Soil / land information
├── Rainfall evidence
├── Vegetation evidence
├── Soil moisture evidence
├── Water-risk overlay
└── Scenario comparison
```

### Interaction

Tap field → field summary

Tap evidence layer → source + timestamp + confidence

Toggle scenario → visual delta, not just a new static map

### Mobile
Use a bottom sheet for layer details.

---

# 21. Evidence & Provenance UX

Every data point can carry:

```text
SOURCE
NASA POWER

TYPE
Observed / modeled / satellite / synthetic

WHEN
2026-...

COVERAGE
...

CONFIDENCE
0.82

USED FOR
ET0 / water balance

LIMITATION
...
```

The UI should make provenance human-readable first and machine-readable second.

---

# 22. Uncertainty UX

Do not show uncertainty as an academic appendix.

Primary language:

> **How stable is this result?**

Then show:

- expected score / outcome range
- top-1 probability where scientifically meaningful
- rank stability
- main sensitivity drivers
- data-quality caveats

Example:

> **Moderately robust**
> The relative ordering changes under some plausible input assumptions.

Avoid language like “95% guaranteed”.

---

# 23. Performance Architecture

Target budgets:

### Initial load
- mobile LCP: < 2.5s on a realistic mid-range device/network
- interactive shell: < 3s

### Interaction
- local UI response: < 100ms where practical
- map layer toggle: < 200ms when data already loaded

### Analysis
For heavy runs:
- show explicit progress
- stream phase status if possible
- never freeze the UI

### Caching
Cache:
- field evidence
- static crop metadata
- common NASA snapshots
- completed analysis runs

Do not silently reuse stale evidence. Surface retrieval dates.

---

# 24. Offline / Poor-Connectivity Strategy

The target audience may have weak connectivity.

Minimum viable offline model:

```text
Install / open app
    ↓
Cached field profile
    ↓
Cached crop metadata
    ↓
Cached last analysis
    ↓
Queue edits
    ↓
Sync when online
```

Offline mode must clearly label stale data.

The user should never mistake “cached” for “live”.

---

# 25. Accessibility / Localization

### Localization architecture
Use message keys, not hard-coded strings.

First locales:
- English
- Bangla

Design every screen for text expansion.

### Accessibility minimum
- WCAG-oriented contrast
- keyboard navigation
- semantic headings
- ARIA only where necessary
- 44px+ touch targets
- focus states
- reduced-motion mode
- no meaning conveyed by color alone
- readable charts with textual summaries

---

# 26. Trust & Safety UX

The system is decision support, not a guarantee engine.

Every recommendation view contains a quiet but visible boundary:

> FieldShift models possible outcomes from available evidence. It does not guarantee yield, profit, or field performance.

More importantly, uncertainty and missing evidence should be shown **before** the user acts, not buried in methodology.

---

# 27. Demo Mode Architecture

A dedicated **Demo Mode** should exist so the judging experience never depends on unreliable live external services.

```text
Demo field
   ↓
Frozen evidence snapshot
   ↓
Deterministic analysis
   ↓
Full UI
```

A small label should say:

> Demo snapshot — reproducible evidence package

Live mode remains available separately.

This gives us the best of both worlds:
- reproducible judging
- real NASA-capable architecture

---

# 28. Judge “Aha” Sequence

The first 60–90 seconds should deliberately reveal capability in this order:

### 1. Field
“Here is the farmer’s actual field.”

### 2. NASA evidence
“Here is what NASA observations tell us about water, vegetation and climate.”

### 3. Preferences
“The farmer chooses what matters.”

### 4. Strategies
“FieldShift generates several rotation strategies.”

### 5. Trade-offs
“They are not identical; each solves a different problem.”

### 6. Climate Lab
“What happens when conditions get hotter, drier or wetter?”

### 7. Evidence
“Here is exactly why the system reached this conclusion.”

### 8. Action
“Here is the decision report the farmer can actually use.”

---

# 29. Technical Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                       FIELD SHIFT WEB                       │
│                                                             │
│  Design System                                              │
│  Routing / State / Accessibility / i18n                     │
│                                                             │
│  Field Workspace | Rotation Explorer | Climate Lab | Report │
└──────────────────────────────┬──────────────────────────────┘
                               │
                        Product API / BFF
                               │
        ┌──────────────────────┼───────────────────────┐
        │                      │                       │
   Field Services       Analysis Services       Evidence Services
        │                      │                       │
        │                FieldShift V3               │
        │                 Engine                     │
        │           ┌──────────┼─────────┐           │
        │           │          │         │           │
        │        Water       Soil     Scoring      Provenance
        │        Model      Model     + MC         + Registry
        │                      │                       │
        └──────────────┬───────┴───────────────┬───────┘
                       │                       │
                 NASA / Remote            Local / Farmer
                    Evidence                Inputs
```

The scientific engine remains isolated from UI concerns.

---

# 30. Suggested Repository Layout

```text
fieldshift_v3/
├── apps/
│   └── web/
│       ├── app/
│       ├── components/
│       ├── features/
│       │   ├── field/
│       │   ├── priorities/
│       │   ├── rotations/
│       │   ├── scenarios/
│       │   ├── evidence/
│       │   └── reports/
│       ├── lib/
│       ├── styles/
│       ├── public/
│       └── tests/
│
├── services/
│   └── product_api/
│
├── src/
│   └── fieldshift/
│       ├── v3/
│       ├── engine/
│       └── api/
│
├── config/
├── data/
├── docs/
│   ├── product/
│   ├── science/
│   └── demo/
└── tests/
```

The frontend should be a first-class application, not an HTML file embedded inside the Python API.

---

# 31. Quality Gates Before Calling the UI “World-Class”

## Product
- A first-time user understands the product within 15 seconds.
- A judge can reach the core differentiation within 90 seconds.
- A farmer can complete a basic analysis without reading documentation.

## Scientific trust
- Every major result has provenance.
- Synthetic / estimated / satellite / observed states are visually distinct.
- Missing evidence never appears as unexplained neutral data.
- Uncertainty is visible at the decision point.

## UX
- Mobile layout works at ~375px.
- Desktop workspace supports side-by-side comparison.
- No chart requires a legend-only interpretation.
- No critical interaction depends on hover.

## Engineering
- UI has typed API contracts.
- Component tests cover critical states.
- End-to-end tests cover the main journey.
- Demo mode is deterministic.
- Accessibility is part of CI.
- Performance budgets are measurable.

---

# 32. Implementation Sequence

## Phase A — Foundation
1. Create first-class web app shell.
2. Establish design tokens and typography.
3. Build routing and state architecture.
4. Build API/BFF contracts.
5. Add deterministic demo dataset.

## Phase B — Core Experience
6. Field map + field profile.
7. Data-quality / evidence layer.
8. Priority selection.
9. Rotation explorer.
10. Strategy comparison.

## Phase C — Differentiation
11. Climate Lab.
12. Uncertainty / robustness visuals.
13. Explainability / counterfactuals.
14. Provenance drawer.
15. Decision report.

## Phase D — Product polish
16. Offline cache.
17. Bangla localization.
18. Accessibility hardening.
19. Mobile performance.
20. Judge demo mode.

## Phase E — Submission
21. Final flagship field.
22. Reproducible demo snapshot.
23. 2–3 minute demo video.
24. Technical architecture page.
25. NASA dataset / methodology page.

---

# 33. What We Should NOT Build Yet

Do not spend the next sprint on:

- accounts / social login
- elaborate farmer profiles
- chatbots
- AI-generated agronomy prose without evidence links
- notification systems
- complex admin dashboards
- dozens of extra crop types before the experience is polished
- decorative 3D farm maps

The objective is one extremely coherent decision experience before broadening scope.

---

# 34. The First Build Slice

The first implementation slice should be exactly this:

```text
HOME
  ↓
FIELD SETUP
  ↓
FIELD HEALTH SNAPSHOT
  ↓
PRIORITIES
  ↓
ROTATION EXPLORER
  ↓
COMPARE
  ↓
CLIMATE LAB
  ↓
WHY THIS STRATEGY?
  ↓
DECISION REPORT
```

Use one Mymensingh rice-based flagship field and a fixed reproducible evidence snapshot for the first complete vertical slice.

Do not implement every possible feature in parallel.

---

# 35. Final Architecture Decision

**FieldShift V3 should become a frontend-led decision platform, not a frontend skin over the existing API.**

The architectural boundary is:

> **Scientific engine decides what can be computed.**
>
> **Product API decides what the application needs.**
>
> **Frontend decides how humans understand and act on it.**

The visible experience should therefore optimize for:

**Trust → Understanding → Comparison → Scenario reasoning → Action**

not:

**Input → Score → Ranking**

That distinction is the core of the next version.
