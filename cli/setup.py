"""Interactive setup wizard -- guides the user through configuration.

Uses questionary for arrow-key navigation, checkboxes, and text input.
Fully dynamic: auto-discovers plugins via PLUGIN_META. Adding a new
plugin file automatically makes it appear in the wizard.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import questionary
import yaml
from dotenv import dotenv_values
from questionary import Choice

from cli.banner import print_banner
from cli.config_gen import generate_config
from cli.scanner import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    ConfigField,
    PluginInfo,
    discover_plugins,
)

# Questionary style
STYLE = questionary.Style([
    ("qmark", "fg:cyan bold"),
    ("question", "fg:white bold"),
    ("answer", "fg:green"),
    ("pointer", "fg:cyan bold"),
    ("highlighted", "fg:cyan bold"),
    ("selected", "fg:green"),
    ("instruction", "fg:gray italic"),
])


def run_setup(home_dir: Path | None = None) -> None:
    """Run the full interactive setup wizard."""
    print_banner()
    print("  Welcome to ClawQuant setup!\n")

    # Step 1: Home directory
    if home_dir is None:
        default_home = str(Path.home() / ".clawquant")
        home_str = questionary.text(
            "Where should ClawQuant store its data?",
            default=default_home,
            style=STYLE,
        ).ask()
        if home_str is None:
            _abort()
        home_dir = Path(home_str).expanduser()

    # Step 2: Discover all available plugins
    all_plugins = discover_plugins()
    existing_values = _load_existing_plugin_values(home_dir, all_plugins)
    existing_enabled = _load_existing_enabled_plugins(home_dir)

    # Step 3: Let user select plugins by category
    enabled_plugins: list[PluginInfo] = []
    plugin_values: dict[str, dict[str, Any]] = {}

    # Categories that require user selection (checkbox)
    selectable = ["ai_provider", "market_data", "integration"]
    # Categories enabled by default (agents, risk rules, task handlers)
    auto_enabled = ["agent", "risk_rule", "task_handler"]

    for category in CATEGORY_ORDER:
        plugins = all_plugins.get(category, [])
        if not plugins:
            continue

        if category in selectable:
            selected = _select_plugins(
                category,
                plugins,
                existing_enabled.get(category, set()),
            )
            enabled_plugins.extend(selected)
        elif category in auto_enabled:
            # Auto-enable, but still let user configure
            enabled_plugins.extend(plugins)

    # Step 4: Configure each selected plugin
    print()
    for plugin in enabled_plugins:
        if not plugin.has_config:
            continue
        values = _configure_plugin(plugin, existing_values.get(plugin.name, {}))
        if values is not None:
            plugin_values[plugin.name] = values

    # Step 5: Generate config files
    print()
    print("  Writing configuration...")
    config_path, env_path = generate_config(
        home_dir=home_dir,
        enabled_plugins=enabled_plugins,
        plugin_values=plugin_values,
    )

    # Step 6: Install extra pip dependencies if any
    extra_deps = set()
    for plugin in enabled_plugins:
        extra_deps.update(plugin.pip_dependencies)
    if extra_deps:
        print(f"  Installing plugin dependencies: {', '.join(extra_deps)}")
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", *extra_deps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # Done
    print()
    print(f"  Config:   {config_path}")
    print(f"  Secrets:  {env_path}")
    print()
    print("  ClawQuant is ready! Run:")
    print("    clawquant start")
    print()


def run_plugin_setup(plugin_name: str) -> None:
    """Configure a single plugin interactively."""
    from cli.scanner import get_plugin

    plugin = get_plugin(plugin_name)
    if not plugin:
        print(f"  Unknown plugin: {plugin_name}")
        print(f"  Run 'clawquant plugin list' to see available plugins.")
        sys.exit(1)

    if not plugin.has_config:
        print(f"  {plugin.display_name} has no configuration options.")
        return

    print_banner()
    print(f"  Configuring: {plugin.display_name}\n")

    values = _configure_plugin(plugin)
    if values:
        print(f"\n  Configuration for {plugin.display_name}:")
        for k, v in values.items():
            display_v = "********" if any(f.key == k and f.type == "secret" for f in plugin.config_fields) else v
            print(f"    {k}: {display_v}")
        print(f"\n  Run 'clawquant config' to apply changes to your configuration.\n")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _select_plugins(
    category: str,
    plugins: list[PluginInfo],
    existing_enabled_names: set[str] | None = None,
) -> list[PluginInfo]:
    """Show a checkbox list for selecting plugins in a category."""
    label = CATEGORY_LABELS.get(category, category)
    required = category == "ai_provider"
    existing_enabled_names = existing_enabled_names or set()

    choices = [
        Choice(
            title=p.choice_label,
            value=p,
            checked=(
                p.name in existing_enabled_names
                or (category == "market_data" and not existing_enabled_names)
            ),
        )
        for p in plugins
    ]

    while True:
        selected = questionary.checkbox(
            f"Select {label}:",
            choices=choices,
            style=STYLE,
            instruction=(
                "(use SPACE to select, ENTER to confirm)"
                + (" (leave empty to keep current)" if required and existing_enabled_names else "")
            ),
        ).ask()

        if selected is None:
            _abort()

        if required and not selected:
            if existing_enabled_names:
                return [p for p in plugins if p.name in existing_enabled_names]
            print("  Please select at least one. Use SPACE to toggle selection, then ENTER.")
            continue

        return selected  # type: ignore[return-value]


def _configure_plugin(plugin: PluginInfo, existing: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Walk through a plugin's config fields and collect values."""
    if not plugin.config_fields:
        return {}
    existing = existing or {}

    # Show setup instructions if present
    instructions = plugin.setup_instructions.strip()
    if instructions:
        print(f"\n  --- {plugin.display_name} Setup ---")
        for line in instructions.split("\n"):
            print(f"  {line}")
        print()

    missing_required = [
        field for field in plugin.config_fields
        if field.required and not _has_value(existing.get(field.key))
    ]
    can_skip = len(missing_required) == 0

    action = questionary.select(
        f"{plugin.display_name}:",
        choices=[
            Choice("Configure now", value="configure"),
            Choice("Skip (keep current values)", value="skip"),
        ],
        default="skip" if can_skip else "configure",
        style=STYLE,
    ).ask()
    if action is None:
        _abort()
    if action == "skip":
        if not can_skip:
            names = ", ".join(f.key for f in missing_required)
            print(f"  Can't skip {plugin.display_name}. Missing required fields: {names}")
        else:
            return existing

    values: dict[str, Any] = {}

    for field in plugin.config_fields:
        current = existing.get(field.key)
        value = _prompt_field(field, plugin.display_name, current=current)
        if value is None and _has_value(current):
            value = current
        if value is not None:
            values[field.key] = value

    return values


def _prompt_field(field: ConfigField, plugin_name: str, current: Any = None) -> Any:
    """Prompt for a single config field based on its type."""
    label = field.label
    if field.description:
        label = f"{field.label} ({field.description})"

    default = current if _has_value(current) else field.default

    match field.type:
        case "secret":
            value = questionary.password(
                f"{field.label}{' (leave blank to keep current)' if _has_value(current) else ''}:",
                style=STYLE,
            ).ask()
            if value is None:
                _abort()
            if value == "" and _has_value(current):
                return None
            return value

        case "choice":
            value = questionary.select(
                f"{field.label}:",
                choices=field.choices,
                default=default,
                style=STYLE,
            ).ask()
            if value is None:
                _abort()
            return value

        case "boolean":
            value = questionary.confirm(
                f"{field.label}?",
                default=bool(default) if default is not None else True,
                style=STYLE,
            ).ask()
            if value is None:
                _abort()
            return value

        case "number":
            default_str = str(default) if default is not None else ""
            value = questionary.text(
                f"{field.label}:",
                default=default_str,
                style=STYLE,
            ).ask()
            if value is None:
                _abort()
            try:
                num = float(value)
                return int(num) if num == int(num) else num
            except ValueError:
                return default

        case "list":
            default_str = ", ".join(default) if isinstance(default, list) else str(default or "")
            value = questionary.text(
                f"{field.label} (comma-separated):",
                default=default_str,
                style=STYLE,
            ).ask()
            if value is None:
                _abort()
            return [item.strip() for item in value.split(",") if item.strip()]

        case _:  # string
            default_str = str(default) if default is not None else ""
            value = questionary.text(
                f"{field.label}:",
                default=default_str,
                style=STYLE,
            ).ask()
            if value is None:
                _abort()
            return value


def _abort() -> None:
    """User pressed Ctrl+C or cancelled."""
    print("\n  Setup cancelled.\n")
    sys.exit(0)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, list):
        return len(value) > 0
    return True


def _load_existing_plugin_values(
    home_dir: Path,
    all_plugins: dict[str, list[PluginInfo]],
) -> dict[str, dict[str, Any]]:
    """Load existing config/env and map values per plugin."""
    config_path = home_dir / "config.yaml"
    env_path = home_dir / ".env"

    config: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

    env = dotenv_values(env_path) if env_path.exists() else {}

    by_name: dict[str, PluginInfo] = {
        p.name: p
        for plugins in all_plugins.values()
        for p in plugins
    }

    out: dict[str, dict[str, Any]] = {}
    for name, plugin in by_name.items():
        vals = _read_plugin_values_from_config(config, plugin)
        # Resolve secret placeholders from .env
        for field in plugin.config_fields:
            if field.type == "secret" and field.env_var:
                env_val = env.get(field.env_var)
                if env_val:
                    vals[field.key] = env_val
        out[name] = vals
    return out


def _read_plugin_values_from_config(config: dict[str, Any], plugin: PluginInfo) -> dict[str, Any]:
    """Extract existing values for a plugin from config.yaml shape."""
    values: dict[str, Any] = {}
    category = plugin.category

    if category == "ai_provider":
        values = (((config.get("ai") or {}).get("providers") or {}).get(plugin.name) or {}).copy()
    elif category == "market_data":
        values = (((config.get("market_data") or {}).get("providers") or {}).get(plugin.name) or {}).copy()
    elif category == "integration":
        integ = ((config.get("integrations") or {}).get(plugin.name) or {}).copy()
        channels = integ.get("channels") or []
        if channels and isinstance(channels, list):
            first = channels[0] or {}
            for key in ("chat_id", "direction"):
                if key in first:
                    integ[key] = first[key]
        values = integ
    elif category == "risk_rule":
        values = (((config.get("risk") or {}).get("rules") or {}).get(plugin.name) or {}).copy()
    elif category == "task_handler":
        values = (((config.get("scheduler") or {}).get("handlers") or {}).get(plugin.name) or {}).copy()
    elif category == "agent":
        values = (((config.get("ai") or {}).get("agents") or {}).get(plugin.name) or {}).copy()

    # Strip generic keys that are not direct field values
    values.pop("enabled", None)
    values.pop("channels", None)
    return values


def _load_existing_enabled_plugins(home_dir: Path) -> dict[str, set[str]]:
    """Load currently enabled plugin names by selectable category."""
    config_path = home_dir / "config.yaml"
    config: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

    out: dict[str, set[str]] = {
        "ai_provider": set(),
        "market_data": set(),
        "integration": set(),
    }

    ai_providers = ((config.get("ai") or {}).get("providers") or {})
    for name, cfg in ai_providers.items():
        if not isinstance(cfg, dict) or cfg.get("enabled", True):
            out["ai_provider"].add(name)

    md_providers = ((config.get("market_data") or {}).get("providers") or {})
    for name, cfg in md_providers.items():
        if not isinstance(cfg, dict) or cfg.get("enabled", True):
            out["market_data"].add(name)

    integrations = config.get("integrations") or {}
    for name, cfg in integrations.items():
        if not isinstance(cfg, dict) or cfg.get("enabled", True):
            out["integration"].add(name)

    return out
