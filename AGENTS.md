# Repository Guidelines

## Project Structure & Module Organization
Core code lives in `src/my_service_mgr/`. Use `cli.py` for argument parsing and entrypoints, `tui.py` for the curses UI, and `manager.py` for systemd installation and status logic. Sample service templates live in `services/`, with matching executable scripts in `scripts/` using the same stem, for example `services/dummy-alpha.service` and `scripts/dummy-alpha.sh`. Treat `build/` and `src/*.egg-info` as generated artifacts, not hand-edited source.

## Build, Test, and Development Commands
Set up a local environment with `python3 -m venv .venv`, `source .venv/bin/activate`, and `python -m pip install -e .`. Run the TUI with `python3 -m my_service_mgr`. Use `python3 -m my_service_mgr --list` to inspect detected templates, and `python3 -m my_service_mgr --dry-run --enable dummy-alpha.service` to verify install behavior without changing the system. Build a distribution with `python -m build` only when you need packaging output.

## Coding Style & Naming Conventions
Target Python 3.10+ and follow the existing style: 4-space indentation, type hints on public functions, `pathlib.Path` over raw path strings, and small focused helpers. Keep modules and package names `snake_case`, classes `PascalCase`, and functions, variables, and CLI flags `snake_case` or kebab-case as appropriate. Match existing patterns such as frozen dataclasses for result objects and concise inline comments only where behavior is not obvious.

## Testing Guidelines
There is no dedicated automated test suite yet. For changes, add focused tests under a new `tests/` package when practical; otherwise verify manually with `--list`, `--dry-run`, and one interactive TUI pass in a real TTY. Prefer test names like `test_enable_by_unit_name_dry_run`. Do not require root for routine validation unless the change is specifically about system mode.

## Commit & Pull Request Guidelines
Recent commits use imperative, capitalized subjects such as `Improve service management...` and `Refactor TUI and CLI...`; keep that style and make the first line explain the user-visible change. Pull requests should summarize behavior changes, note Linux or systemd assumptions, list manual verification steps, and include terminal screenshots only when TUI output changed.

## Security & Configuration Tips
This project installs scripts and unit files, so avoid hard-coded machine-specific paths beyond the documented systemd locations. Keep the `__SCRIPT_PATH__` placeholder in service templates, and prefer `--mode user` or `--dry-run` while developing.
