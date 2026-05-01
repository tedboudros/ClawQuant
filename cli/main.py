"""ClawQuant CLI -- the `clawquant` command.

Usage:
    clawquant setup              Full interactive setup wizard
    clawquant start              Start the server (foreground)
    clawquant start -d           Start the server in the background
    clawquant stop               Stop a background server
    clawquant logs               Follow server log output in realtime
    clawquant status             Show system status
    clawquant update             Pull latest code from GitHub
    clawquant config             Re-run the configuration wizard
    clawquant plugin list        List all available plugins
    clawquant plugin <name>      Configure a specific plugin
    clawquant plugin enable <n>  Enable a plugin
    clawquant plugin disable <n> Disable a plugin
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

LOG_FILENAME = "clawquant.log"
PID_FILENAME = "clawquant.pid"
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def get_home_dir() -> Path:
    """Get the ClawQuant home directory."""
    return Path(os.environ.get("CLAWQUANT_HOME", Path.home() / ".clawquant")).expanduser()


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _load_update_preferences(config_path: Path) -> tuple[bool, str]:
    """Read updates.auto_update and updates.install_commit from config.yaml."""
    import yaml

    if not config_path.exists():
        return False, ""
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        return False, ""

    updates = config.get("updates")
    if not isinstance(updates, dict):
        return False, ""

    auto_update = _as_bool(updates.get("auto_update"), False)
    install_commit = str(updates.get("install_commit", "") or "").strip()
    return auto_update, install_commit


def _current_repo_commit(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _save_install_commit(config_path: Path, commit_hash: str) -> None:
    if not commit_hash or not config_path.exists():
        return

    import yaml

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        return

    updates = config.get("updates")
    if not isinstance(updates, dict):
        updates = {}
        config["updates"] = updates
    updates["install_commit"] = commit_hash

    try:
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except Exception:
        return


def _run_repo_update(
    repo_root: Path,
    refresh_dependencies: bool = True,
    config_path: Path | None = None,
) -> bool:
    """Pull latest code and optionally refresh dependencies."""
    if not (repo_root / ".git").exists():
        print(f"  Not a git checkout: {repo_root}")
        print("  Reinstall with the one-line installer, or update manually.")
        return False

    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("  git is not installed or not available on PATH.")
        return False

    if result.returncode != 0:
        print("  Update failed.")
        err = (result.stderr or result.stdout).strip()
        if err:
            print(f"  {err}")
        print("  Resolve local git conflicts/changes, then retry.")
        return False

    out = result.stdout.strip()
    if out:
        print(out)
    else:
        print("  Updated repository.")

    commit_hash = _current_repo_commit(repo_root)
    if config_path is not None and commit_hash:
        _save_install_commit(config_path, commit_hash)
        print(f"  Recorded install commit: {commit_hash[:12]}")

    if not refresh_dependencies:
        return True

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--trusted-host", "pypi.org",
             "--trusted-host", "pypi.python.org",
             "--trusted-host", "files.pythonhosted.org",
             "-r", "requirements.txt"],
            cwd=repo_root,
        )
        print("  Dependencies refreshed.")
    except subprocess.CalledProcessError:
        print("  Repository updated, but dependency refresh failed.")
        print("  Run: pip install -r requirements.txt")
        return False
    return True


def _run_git(repo_root: Path, args: list[str], timeout_seconds: float = 6.0) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except Exception:
        return None


def _count_commits_behind_upstream(repo_root: Path) -> int | None:
    """Return how many commits local HEAD is behind upstream; None if unknown."""
    if not (repo_root / ".git").exists():
        return None

    # Must have an upstream configured for the current branch.
    upstream = _run_git(
        repo_root,
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        timeout_seconds=3.0,
    )
    if upstream is None or upstream.returncode != 0:
        return None

    # Refresh remote tracking refs best-effort; failures are treated as unknown.
    fetched = _run_git(repo_root, ["fetch", "--quiet"], timeout_seconds=8.0)
    if fetched is None or fetched.returncode != 0:
        return None

    counts = _run_git(repo_root, ["rev-list", "--left-right", "--count", "HEAD...@{u}"], timeout_seconds=3.0)
    if counts is None or counts.returncode != 0:
        return None

    raw = counts.stdout.strip()
    if not raw:
        return None

    # Output format: "<ahead>\t<behind>"
    parts = raw.replace("\t", " ").split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def _pid_file_path() -> Path:
    return get_home_dir() / PID_FILENAME


def _log_file_path() -> Path:
    return get_home_dir() / LOG_FILENAME


def _read_pid() -> int | None:
    """Read PID from file and verify the process is still alive."""
    pf = _pid_file_path()
    if not pf.exists():
        return None
    try:
        pid = int(pf.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ProcessLookupError, ValueError, OSError):
        pf.unlink(missing_ok=True)
        return None


def _load_logging_settings(config_path: Path) -> tuple[str, int, int]:
    """Read (level, max_bytes, backup_count) from config.yaml's logging section.

    Falls back to sensible defaults if the file is missing or malformed.
    Avoids importing the full Pydantic model so the CLI stays light.
    """
    level = "INFO"
    max_bytes = 10 * 1024 * 1024
    backup_count = 5
    try:
        import yaml
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        log_section = data.get("logging") or {}
        level = str(log_section.get("level", level))
        max_bytes = int(log_section.get("max_bytes", max_bytes))
        backup_count = int(log_section.get("backup_count", backup_count))
    except Exception:
        pass
    return level, max_bytes, backup_count


def _rotate_log_file(log_file: Path, max_bytes: int, backup_count: int) -> None:
    """Size-based pre-start rotation, mirroring RotatingFileHandler semantics.

    Daemon mode redirects stdout/stderr directly into ``log_file``, so Python's
    RotatingFileHandler can't manage rollover for us. We do it once at start.
    """
    try:
        if max_bytes <= 0 or backup_count <= 0:
            return
        if not log_file.exists() or log_file.stat().st_size < max_bytes:
            return
        # Drop the oldest, then shift each backup up by one.
        oldest = log_file.with_suffix(log_file.suffix + f".{backup_count}")
        if oldest.exists():
            oldest.unlink()
        for i in range(backup_count - 1, 0, -1):
            src = log_file.with_suffix(log_file.suffix + f".{i}")
            dst = log_file.with_suffix(log_file.suffix + f".{i + 1}")
            if src.exists():
                src.rename(dst)
        log_file.rename(log_file.with_suffix(log_file.suffix + ".1"))
    except Exception as exc:
        print(f"  Warning: could not rotate {log_file}: {exc}")


def _start_background(config_path: Path, log_level: str | None = None) -> None:
    """Re-launch ClawQuant as a detached background process."""
    log_file = _log_file_path()
    pid_file = _pid_file_path()

    existing = _read_pid()
    if existing is not None:
        print(f"  ClawQuant is already running (PID {existing}).")
        print("  Use 'clawquant logs' to view output, or 'clawquant stop' first.")
        sys.exit(1)

    repo_root = _repo_root()
    cmd = [sys.executable, "-m", "cli.main", "start"]
    if log_level:
        cmd.extend(["--log-level", log_level])

    log_file.parent.mkdir(parents=True, exist_ok=True)

    config_level, max_bytes, backup_count = _load_logging_settings(config_path)
    _rotate_log_file(log_file, max_bytes, backup_count)

    effective_level = (log_level or config_level).upper()

    # Tell the subprocess that stdout/stderr are already being captured to the
    # log file, so it shouldn't also attach a Python RotatingFileHandler (which
    # would cause every log record to appear twice in the file).
    child_env = os.environ.copy()
    child_env["CLAWQUANT_DAEMON"] = "1"

    with open(log_file, "a") as lf:
        lf.write(f"\n{'=' * 60}\n")
        lf.write(
            f"ClawQuant starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
            f"(log level: {effective_level})\n"
        )
        lf.write(f"{'=' * 60}\n")
        lf.flush()

        proc = subprocess.Popen(
            cmd,
            cwd=repo_root,
            stdout=lf,
            stderr=lf,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=child_env,
        )

    pid_file.write_text(str(proc.pid))

    print(f"  ClawQuant started in background (PID {proc.pid}).")
    print(f"  Logs: {log_file}")
    print("  Run 'clawquant logs' to follow output.")
    print("  Run 'clawquant stop' to stop the server.")


def cmd_setup(args: argparse.Namespace) -> None:
    """Run the interactive setup wizard."""
    from cli.setup import run_setup
    home = get_home_dir() if not args.home else Path(args.home).expanduser()
    run_setup(home_dir=home)


def cmd_start(args: argparse.Namespace) -> None:
    """Start the ClawQuant server."""
    config_path = get_home_dir() / "config.yaml"
    if not config_path.exists():
        print("  No configuration found. Run 'clawquant setup' first.")
        sys.exit(1)

    log_level = getattr(args, "log_level", None)

    if getattr(args, "daemon", False):
        _start_background(config_path, log_level=log_level)
        return

    auto_update, install_commit = _load_update_preferences(config_path)
    repo_root = _repo_root()

    # Keep recorded install commit aligned with local HEAD.
    current_commit = _current_repo_commit(repo_root)
    if current_commit and current_commit != install_commit:
        _save_install_commit(config_path, current_commit)

    if auto_update:
        print("  Auto-update is enabled. Checking for updates...")
        _run_repo_update(repo_root, refresh_dependencies=True, config_path=config_path)
    else:
        behind = _count_commits_behind_upstream(repo_root)
        if behind and behind > 0:
            noun = "commit" if behind == 1 else "commits"
            print(f"  Auto-update is disabled. {behind} new {noun} available. Run 'clawquant update'.")

    from main import run, setup_logging
    # Provisional logging; `run()` reconfigures using config + CLI override.
    setup_logging(log_level or "INFO")

    # When launched by `_start_background`, stdout/stderr are already being
    # captured to clawquant.log. Skip the Python file handler in that case to
    # avoid duplicate records.
    launched_by_daemon = os.environ.get("CLAWQUANT_DAEMON") == "1"

    try:
        asyncio.run(run(
            config_path=str(config_path),
            cli_log_level=log_level,
            log_to_file=not launched_by_daemon,
        ))
    except KeyboardInterrupt:
        pass
    finally:
        _pid_file_path().unlink(missing_ok=True)


def cmd_stop(args: argparse.Namespace) -> None:
    """Stop a background ClawQuant server."""
    pid = _read_pid()
    if pid is None:
        print("  ClawQuant is not running (no active PID found).")
        return

    print(f"  Stopping ClawQuant (PID {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
        else:
            print("  Process did not stop gracefully, forcing...")
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    except ProcessLookupError:
        pass

    _pid_file_path().unlink(missing_ok=True)
    print("  ClawQuant stopped.")


def cmd_logs(args: argparse.Namespace) -> None:
    """Follow ClawQuant log output in realtime."""
    log_file = _log_file_path()

    if not log_file.exists():
        print("  No log file found. Start ClawQuant first:")
        print("    clawquant start -d")
        sys.exit(1)

    n = getattr(args, "lines", 50)
    follow = not getattr(args, "no_follow", False)

    cmd = ["tail", "-n", str(n)]
    if follow:
        cmd.append("-f")
    cmd.append(str(log_file))

    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass


def cmd_status(args: argparse.Namespace) -> None:
    """Show system status."""
    from cli.banner import print_banner
    print_banner()

    home = get_home_dir()
    config_path = home / "config.yaml"

    print(f"  Home:     {home}")
    print(f"  Config:   {config_path} ({'exists' if config_path.exists() else 'NOT FOUND'})")
    print(f"  Database: {home / 'db.sqlite'} ({'exists' if (home / 'db.sqlite').exists() else 'NOT FOUND'})")
    print()

    # Count state files
    dirs = {
        "Signals": home / "signals",
        "Positions (AI)": home / "positions" / "ai",
        "Positions (Human)": home / "positions" / "human",
        "Memories": home / "memories",
        "Tasks": home / "tasks",
        "Memos": home / "memos",
        "Event logs": home / "events",
    }

    for label, path in dirs.items():
        if path.exists():
            count = len(list(path.glob("*.json")) + list(path.glob("*.jsonl")) + list(path.glob("*.md")))
            if count:
                print(f"  {label}: {count} files")

    # Show discovered plugins
    print()
    from cli.scanner import discover_plugins, CATEGORY_LABELS
    plugins = discover_plugins()
    for cat, items in plugins.items():
        names = ", ".join(p.display_name for p in items)
        print(f"  {CATEGORY_LABELS.get(cat, cat)}: {names}")

    print()


def cmd_config(args: argparse.Namespace) -> None:
    """Re-run the configuration wizard."""
    from cli.setup import run_setup
    run_setup(home_dir=get_home_dir())


def cmd_update(args: argparse.Namespace) -> None:
    """Update local installation from GitHub using git pull."""
    config_path = get_home_dir() / "config.yaml"
    _run_repo_update(_repo_root(), refresh_dependencies=True, config_path=config_path)


def cmd_plugin(args: argparse.Namespace) -> None:
    """Plugin management commands."""
    action = args.plugin_action

    if action == "list":
        _plugin_list()
    elif action == "enable":
        _plugin_toggle(args.plugin_name, enable=True)
    elif action == "disable":
        _plugin_toggle(args.plugin_name, enable=False)
    else:
        # Treat as plugin name to configure
        from cli.setup import run_plugin_setup
        run_plugin_setup(action)


def _plugin_list() -> None:
    """List all available plugins."""
    from cli.scanner import discover_plugins, CATEGORY_LABELS

    plugins = discover_plugins()
    print()
    for cat, items in plugins.items():
        print(f"  {CATEGORY_LABELS.get(cat, cat)}:")
        for p in items:
            deps = f" [requires: {', '.join(p.pip_dependencies)}]" if p.pip_dependencies else ""
            fields = f" ({len(p.config_fields)} config fields)" if p.config_fields else ""
            print(f"    {p.name:20s} {p.display_name}{fields}{deps}")
        print()


def _plugin_toggle(name: str | None, enable: bool) -> None:
    """Enable or disable a plugin in config.yaml."""
    if not name:
        print("  Usage: clawquant plugin enable <name>")
        return

    import yaml
    home = get_home_dir()
    config_path = home / "config.yaml"

    if not config_path.exists():
        print("  No config file. Run 'clawquant setup' first.")
        return

    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    def _enable_flag(entry: object) -> bool:
        if isinstance(entry, dict):
            entry["enabled"] = enable
            return True
        return False

    found = False

    # integrations.<name>
    integrations = config.get("integrations")
    if isinstance(integrations, dict) and name in integrations:
        found = _enable_flag(integrations.get(name)) or found

    # ai.providers.<name>
    ai = config.get("ai")
    if isinstance(ai, dict):
        providers = ai.get("providers")
        if isinstance(providers, dict) and name in providers:
            found = _enable_flag(providers.get(name)) or found

        agents = ai.get("agents")
        if isinstance(agents, dict) and name in agents:
            found = _enable_flag(agents.get(name)) or found

    # market_data.providers.<name>
    market_data = config.get("market_data")
    if isinstance(market_data, dict):
        providers = market_data.get("providers")
        if isinstance(providers, dict) and name in providers:
            found = _enable_flag(providers.get(name)) or found

    # risk.rules.<name>
    risk = config.get("risk")
    if isinstance(risk, dict):
        rules = risk.get("rules")
        if isinstance(rules, dict) and name in rules:
            found = _enable_flag(rules.get(name)) or found

    # scheduler.handlers.<name>
    scheduler = config.get("scheduler")
    if isinstance(scheduler, dict):
        handlers = scheduler.get("handlers")
        if isinstance(handlers, dict) and name in handlers:
            found = _enable_flag(handlers.get(name)) or found

    if found:
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        action = "Enabled" if enable else "Disabled"
        print(f"  {action}: {name}")
    else:
        if enable:
            from cli.setup import enable_plugin_with_setup
            if enable_plugin_with_setup(name, home):
                return
        print(f"  Plugin '{name}' not found in config. Run 'clawquant config' to set it up.")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="clawquant",
        description="ClawQuant -- Lightweight trading advisory system",
    )
    parser.add_argument("--home", type=str, default=None, help="ClawQuant home directory")

    sub = parser.add_subparsers(dest="command")

    # setup
    sub.add_parser("setup", help="Run the interactive setup wizard")

    # start
    start_parser = sub.add_parser("start", help="Start the ClawQuant server")
    start_parser.add_argument(
        "-d", "--daemon",
        action="store_true",
        default=False,
        help="Run the server in the background",
    )
    start_parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        choices=VALID_LOG_LEVELS,
        help=(
            "Override the log level (default: from config.yaml's logging.level "
            "or INFO). Use DEBUG to capture verbose logs in clawquant.log."
        ),
    )

    # stop
    sub.add_parser("stop", help="Stop a background ClawQuant server")

    # logs
    logs_parser = sub.add_parser("logs", help="Follow server log output in realtime")
    logs_parser.add_argument(
        "-n", "--lines",
        type=int,
        default=50,
        help="Number of lines to show initially (default: 50)",
    )
    logs_parser.add_argument(
        "--no-follow",
        action="store_true",
        default=False,
        help="Print log lines and exit (don't follow)",
    )

    # status
    sub.add_parser("status", help="Show system status")

    # update
    sub.add_parser("update", help="Pull latest code from GitHub and refresh dependencies")

    # config
    sub.add_parser("config", help="Re-run the configuration wizard")

    # plugin
    plugin_parser = sub.add_parser("plugin", help="Plugin management")
    plugin_parser.add_argument(
        "plugin_action",
        type=str,
        help="list | enable | disable | <plugin-name>",
    )
    plugin_parser.add_argument(
        "plugin_name",
        type=str,
        nargs="?",
        default=None,
        help="Plugin name (for enable/disable)",
    )

    return parser


def main() -> None:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    commands = {
        "setup": cmd_setup,
        "start": cmd_start,
        "stop": cmd_stop,
        "logs": cmd_logs,
        "status": cmd_status,
        "update": cmd_update,
        "config": cmd_config,
        "plugin": cmd_plugin,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
