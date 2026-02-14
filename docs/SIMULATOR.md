# Simulator

## Status

**Current state: prototype module exists, but not yet wired into CLI/server workflows and not yet validated as production-ready.**

What this means today:
- `simulator/engine.py`, `simulator/metrics.py`, and `simulator/mocks.py` exist.
- There is no `clawquant simulate ...` command yet.
- There is no server endpoint for simulation execution.
- No repo test suite currently verifies simulator end-to-end behavior.

Treat simulator functionality as **coming soon** from an operational perspective.

---

## What Exists in Code

### Core class
- `SimulationEngine.run_simulation(config)` executes a sandbox run.
- Uses `TimeContext` for historical visibility control.
- Uses `MockOutputAdapter` so no real notifications are sent.

### Models
- `SimulationConfig`
- `PerformanceMetrics`
- `SimulationRun`

### Output artifacts
- Results written under `~/.clawquant/simulations/<run_id>/results.json`
- Captured mock signal files in simulator output directories

---

## Implemented Flow (Module-Level)

1. Build `SimulationRun` and mark started.
2. Create sandbox store/bus/portfolio/memory components.
3. Register mock output adapter.
4. Load historical market data for simulation range.
5. Generate synthetic daily schedule events.
6. Run orchestrator analysis in simulation `TimeContext`.
7. Collect trades, calculate metrics, and write results.

---

## Known Gaps / Coming Soon

- CLI integration (`clawquant simulate ...`)
- HTTP/API integration for simulation runs
- Automated regression tests and benchmark harness
- Runtime integration with production plugin loading profiles
- Explicit walk-forward/regime/survivorship tooling in first-class commands

---

## Practical Guidance

If you use simulator code right now, treat it as internal/dev tooling:
- verify outputs manually
- pin datasets and configs explicitly
- avoid relying on it as a validated production benchmark pipeline until CLI/test coverage lands
