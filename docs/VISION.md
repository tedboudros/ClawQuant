# ClawQuant Vision

This document defines the long-term product intent so implementation details can evolve without losing core direction.

---

## Mission

Build a modular, AI-native trading copilot that helps a human trader make better decisions, learn over time, and stay in control.

---

## Product North Star

ClawQuant should feel like one consistent intelligence that:

1. Understands natural language requests.
2. Uses tools and plugins to take real actions.
3. Remembers context and improves from outcomes.
4. Stays modular so capabilities can be added without rewriting the core.

---

## Non-Negotiable Principles

### 1) Human-in-the-loop execution

- ClawQuant advises.
- The human owns execution authority by default.
- Safety and risk constraints stay deterministic where required.

### 2) Dual portfolio truth model

- Maintain two separate portfolios:
  - AI portfolio (what the system would do).
  - Human portfolio (what the user actually did).
- Compare them over time to measure divergence and decision quality.
- Use divergences as explicit learning inputs, not hidden heuristics.

### 3) Learning from disagreement

- Generate structured memories from AI-vs-human divergences.
- Persist and retrieve those memories as first-class context.
- Use learning loop outputs to improve future analysis behavior.

### 4) One central AI surface

- The same central AI should power:
  - direct chat conversations
  - scheduled `ai.run_prompt` tasks
- Behavior, tools, and system rules should remain consistent across triggers.

### 5) Modular architecture

- Core defines protocols and contracts.
- Plugins implement integrations, providers, and tools.
- Event bus remains the primary coordination mechanism.

### 6) Time-aware integrity

- Simulation and historical reasoning must enforce time visibility (`TimeContext`, `available_at`) to avoid lookahead bias.
- Backtesting and live behavior should converge toward parity as the simulator matures.

---

## Target Experience

When a user talks to ClawQuant, they should be able to:

1. Ask naturally (any language, normal phrasing).
2. Have the system act immediately when tools allow it.
3. Schedule recurring intelligence jobs with the same AI they already use.
4. Understand what changed, why it changed, and what was learned.

---

## Near-Term Direction

The implementation roadmap should continue converging toward:

1. Fully wired orchestrator -> risk -> delivery runtime path.
2. Stronger automated learning-loop orchestration (without losing transparency).
3. Simulator integration as a first-class workflow.
4. More plugin breadth without breaking the modular core.

