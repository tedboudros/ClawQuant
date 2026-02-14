# Architectural Decisions

Key decisions and tradeoffs, with runtime status notes.

## How to Read This File

Each ADR includes:
- **Decision**: what we chose
- **Rationale**: why
- **Status**:
  - `Current` = wired in today
  - `Partial` = implemented modules exist but not default live path
  - `Target-state` = planned / documented direction

---

## ADR-1: File-First State + SQLite Indexes

**Decision**
Persist domain state as files (JSON/JSONL/Markdown) and use SQLite for indexed queries.

**Rationale**
- State remains human-inspectable and easy to back up.
- SQLite adds fast lookup for market data and memory retrieval without external infra.

**Status**: `Current`

---

## ADR-2: Minimal Core Dependencies

**Decision**
Keep the core dependency set small (`pydantic`, `pyyaml`, `python-dotenv`, `aiohttp`, `httpx`, `questionary`) and rely on stdlib for the rest.

**Rationale**
- Simpler installs and fewer supply-chain/version risks.
- Plugin dependencies are optional and installed only when needed.

**Status**: `Current`

---

## ADR-3: Protocol-Based Core (8 Protocols)

**Decision**
Define extension boundaries via protocols (`EventBus`, `MarketDataProvider`, `InputAdapter`, `OutputAdapter`, `LLMProvider`, `AIAgent`, `RiskRule`, `TaskHandler`).

**Rationale**
- Core logic depends on contracts, not concrete plugin classes.
- New integrations/providers can be swapped without rewriting core modules.

**Status**: `Current`

---

## ADR-4: Self-Describing Plugins via `PLUGIN_META`

**Decision**
Each plugin declares metadata (`PLUGIN_META`) consumed by scanner/setup flows.

**Rationale**
- Zero central registry file.
- CLI setup can discover config fields/dependencies dynamically.
- `plugin enable` can walk users through missing config for that specific plugin.

**Status**: `Current`

---

## ADR-5: AI-First Interaction Model (Tool Calling)

**Decision**
User-facing interaction is handled by `engine/interface.py` via LLM tool calling, not regex command parsing.

**Rationale**
- Supports natural language and multilingual interaction.
- Centralizes behavior in one conversational controller.
- Reduces brittle parser logic.

**Status**: `Current`

**Important runtime details**
- Built-in tool set is not the old fixed 12-tool list; current built-ins include task-handler discovery (`list_task_handlers`) and deletion by name (`delete_task_by_name`).
- Plugin tools are added dynamically at runtime (`get_tools` + `call_tool`).

---

## ADR-6: Act-First Tool Loop with Multi-Round Execution

**Decision**
Tool-capable requests should execute tools in-turn before final response, with multi-round loop support.

**Rationale**
- Avoids deferred “I will do it” responses when actions can be performed now.
- Supports chained workflows (lookup -> refine -> action -> final answer).

**Status**: `Current`

**Runtime behavior**
- Max tool rounds: `25`.
- On limit hit, interface inserts an internal max-rounds message and asks for user confirmation in a new turn.

---

## ADR-7: File-Backed Async Scheduler

**Decision**
Run a lightweight asyncio scheduler that scans JSON task files and dispatches handlers.

**Rationale**
- Tasks are simple to inspect/edit/delete on disk.
- No external queue/service required.
- Works well with AI-created tasks.

**Status**: `Current`

---

## ADR-8: Reuse the Same Central AI for Scheduled Runs

**Decision**
`ai.run_prompt` invokes the same AI interface used by Telegram/Discord conversations.

**Rationale**
- Consistent tools, prompts, and behavior across chat and cron triggers.
- Avoids drift between “chat AI” and “scheduled AI”.

**Status**: `Current`

**Runtime behavior**
Scheduled runs inject context as:
1. system prompt
2. last 10 channel messages
3. scheduled prompt

---

## ADR-9: Event Bus + Generic Output Dispatch

**Decision**
Use `integration.output` events as the universal outbound channel, with centralized dispatching in `OutputDispatcher`.

**Rationale**
- Keeps integrations transport-only.
- Decouples message producers from specific adapters.
- Enables adapter filtering (`adapter`, `channel_id`) without branching everywhere.

**Status**: `Current`

---

## ADR-10: Deterministic Risk Engine Separate from LLM

**Decision**
Risk validation belongs in deterministic rules, not in LLM judgment.

**Rationale**
- Enforces hard limits predictably.
- Prevents hallucinated risk overrides.

**Status**: `Partial`

**Status note**
- `risk/engine.py` and risk-rule plugins exist.
- In the current default runtime path, risk rules are loaded but the full orchestrator -> risk gating event pipeline is not wired as the primary live flow.

---

## ADR-11: Dual Portfolios + Memory Learning

**Decision**
Maintain AI and human portfolios and derive structured memories from divergences.

**Rationale**
- Separates model-vs-user behavior for analysis.
- Creates inspectable learning artifacts instead of opaque fine-tuning.

**Status**: `Current` for storage and comparison handler, `Partial` for fully automated loop orchestration.

**Status note**
- `comparison.weekly` handler is implemented.
- Auto-scheduling from config is not currently automatic; tasks must be created explicitly.

---

## ADR-12: TimeContext for Simulation Integrity

**Decision**
Use `TimeContext` and `available_at` filtering to prevent lookahead bias.

**Rationale**
- Same conceptual model for production and simulation contexts.
- Explicit temporal visibility controls.

**Status**: `Partial`

**Status note**
- Models and simulator modules exist.
- Simulator is not yet exposed as a first-class CLI/server workflow and is not production-validated end-to-end.

---

## ADR-13: Human-In-The-Loop Execution

**Decision**
System is advisory by default; no automatic broker execution path in core runtime.

**Rationale**
- Safety and control.
- Lower operational/regulatory risk.

**Status**: `Current`

---

## Runtime Caveats (Important)

- `server.py` currently has no `/chat` endpoint.
- `run_analysis` tool currently publishes an event (`integration.input`) but default runtime does not wire a live orchestrator subscriber to complete that path.
- `scheduler.default_tasks` and `learning.comparison_schedule` are parsed config values but not auto-materialized into tasks at startup.
- Legacy examples mentioning integrations/providers not present in `plugins/` (email/webhook/custom loader/CoinGecko/etc.) should be treated as target-state references.
