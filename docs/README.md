# ClawQuant Documentation

**A lightweight, event-driven LLM trading advisory system.**

This docs set now separates:
- what is **currently implemented and wired** in runtime, and
- what is **target-state / coming soon**.

---

## Documentation Index

| Document | Description |
|----------|-------------|
| [VISION.md](VISION.md) | Product north star and non-negotiable principles |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Runtime architecture (chat-first) + target-state sections |
| [DATA_MODELS.md](DATA_MODELS.md) | Core models, file/SQLite mappings, conversation history storage |
| [FLOWS.md](FLOWS.md) | Current production flows (Telegram/Discord + tools + scheduler) and planned flows |
| [LEARNING_LOOP.md](LEARNING_LOOP.md) | Dual-portfolio divergence system and scheduling status |
| [SIMULATOR.md](SIMULATOR.md) | Simulator module status, capabilities, and current limitations |
| [CONFIGURATION.md](CONFIGURATION.md) | Current setup/config reference (Telegram/Discord/Yahoo/OpenAI/Anthropic/OpenRouter) |
| [TECH_DECISIONS.md](TECH_DECISIONS.md) | ADRs with runtime status caveats |

---

## Status Snapshot

### Implemented and Wired
- Telegram + Discord bidirectional integrations
- AI interface with multi-step tool-calling loop
- Built-in tools for portfolio/trade/tasks/memories/signals/analysis trigger
- Plugin-defined tools (`get_tools` / `call_tool`) including `get_news` and `web_search`
- Scheduler with task handlers: `ai.run_prompt`, `news.briefing`, `notifications.send`, `comparison.weekly`
- Event-bus output dispatch through `integration.output`
- SQLite conversation persistence and first-turn onboarding directive persistence

### Coming Soon / Not Fully Wired
- Full orchestrator->risk->signal-delivery live pipeline wiring
- Email/webhook/custom scraper integrations described in old examples
- Additional market providers in old examples (e.g., CoinGecko)
- Auto-created default recurring tasks from config on startup
- Simulator exposed via CLI/server and validation-tested in production workflows

---

## Runtime Defaults

- Python: 3.11+
- Core deps: `pydantic`, `pyyaml`, `python-dotenv`, `aiohttp`, `httpx`, `questionary`
- Home dir: `~/.clawquant`
- Core storage: files + SQLite (`db.sqlite`)
