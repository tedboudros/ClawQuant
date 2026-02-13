# ClawQuant Documentation

**A lightweight, event-driven macro/LLM trading advisory system.**

ClawQuant ingests macro, political, rates, and market data across any asset class (stocks, crypto, ETFs, commodities, forex), processes it through AI agents, and delivers actionable trade signals to a human trader. The system learns from disagreements between the AI and the human over time.

Runs on minimal hardware. 6 pip dependencies. State is files on disk. One-line installer and interactive CLI.

---

## Documentation Index

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Core architecture: 7 components, file-based state, lightweight design |
| [DATA_MODELS.md](DATA_MODELS.md) | All data models: how they serialize to JSON/Markdown/SQLite, with on-disk examples |
| [FLOWS.md](FLOWS.md) | Event flows: the golden path, full email-to-sell lifecycle, divergence scenarios, simulation runs |
| [LEARNING_LOOP.md](LEARNING_LOOP.md) | Dual portfolio system: how AI and human teach each other through structured memories |
| [SIMULATOR.md](SIMULATOR.md) | Backtesting: TimeContext, event replay, model benchmarking, walk-forward validation |
| [CONFIGURATION.md](CONFIGURATION.md) | Full config reference: config.yaml, .env, custom scrapers |
| [TECH_DECISIONS.md](TECH_DECISIONS.md) | Architectural decisions: file-based storage, minimal deps, every major design choice with rationale |

---

## Quick Summary

### What It Does
- Monitors data sources (market data, email, news, custom scrapers)
- AI agents analyze catalysts and produce investment memos (saved as Markdown)
- Risk engine gates signals with deterministic rules (zero AI involvement)
- Delivers signals to the human via integrations (Telegram, email, etc.)
- Tracks two portfolios: what the AI would do vs. what the human actually does
- Learns from divergences via structured memories

### What It Doesn't Do
- Execute trades automatically (human-in-the-loop)
- Require PostgreSQL, Redis, Docker, or any external services
- Use more than ~100MB RAM

### The 7 Core Components
1. **Event Bus** -- In-process async pub/sub + JSONL audit log
2. **Integration Layer** -- Bidirectional plugins (Telegram, email, scrapers, webhooks)
3. **Data Layer** -- Files on disk + SQLite for indexed queries
4. **Scheduler** -- Simple asyncio loop reading task JSON files
5. **AI Engine** -- Multi-agent orchestrator + conversational interface
6. **Risk Engine** -- Deterministic rules, dual portfolio tracker
7. **Simulator** -- Same pipeline in sandbox mode with TimeContext filtering

### Design Principles
- **Fully abstracted core**: 8 protocols define every extension point. The core defines WHAT, plugins define HOW. Swap any market data source, LLM provider, integration, or risk rule without touching the core.
- **Self-describing plugins (PLUGIN_META)**: Every plugin file declares a `PLUGIN_META` dict at module level (name, category, dependencies, config fields). The CLI auto-discovers plugins by scanning the `plugins/` directory -- adding a new plugin is just adding a file with `PLUGIN_META`.
- **File-based state**: Memos are Markdown. Positions are JSON. Logs are JSONL. All inspectable, greppable, `cat`-able.
- **Minimal dependencies**: 6 core pip packages + Python stdlib
- **CLI-first**: One-line installer (`install.sh`), interactive setup wizard (`clawquant setup`), all management via the `clawquant` command.
- **Runs on a potato**: Single async Python process, ~100MB RAM, no Docker
- **Plugin-based**: Core is a lightweight HTTP server. Everything else is a plugin.
- **Human-in-the-loop**: AI advises, human trades
- **Dual portfolio**: AI paper + human actual, learning from divergences
- **Zero lookahead**: TimeContext filters all data queries for simulation integrity

### Tech Stack

| | Technology |
|-|------------|
| Language | Python 3.12+ |
| Server | aiohttp (lightweight async) |
| HTTP Client | httpx (LLM APIs, data fetching) |
| Storage | Files (JSON, Markdown, JSONL) + SQLite (stdlib) |
| Validation | Pydantic v2 |
| Config | YAML + .env |
| CLI | questionary (interactive setup wizard) |
| Total core LOC | ~3,000+ lines |
