# my-service-mgr

Manage custom services and scripts on Linux (Pop!_OS).

## License

MIT (see `LICENSE`).

## Install (editable)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

## Verify the package

```bash
python -c "import my_service_mgr; print(my_service_mgr.__version__)"
```

## Helper scripts

```bash
./build.sh
./uninstall.sh
```

- `./build.sh`: creates `.venv` if needed, upgrades `pip`, and installs the app in editable mode
- `./uninstall.sh`: uninstalls `my-service-mgr` from the current Python environment
- `./build.sh` also configures `git` to use the repo's `.githooks/` directory

## Versioning

- The app version is stored in `pyproject.toml` and the source fallback in `src/my_service_mgr/__init__.py`.
- A repo `pre-push` hook bumps the patch version, creates a commit, and tags it as `vX.Y.Z`.
- Because `pre-push` runs after Git has decided what refs to send, the hook stops that push after creating the version commit and tag.
- After it bumps the version, rerun:

```bash
git push --follow-tags
```

## Project layout
- `src/my_service_mgr/`: Python package code
- `scripts/`: helper scripts you want to keep in-repo
- `services/`: future service unit templates / artifacts

## Usage

From the repo root, run the arrow-based TUI (requires a TTY):
```bash
python3 -m my_service_mgr
```

The TUI has three views:
- `1` Templates: install/remove services from `services/` and `scripts/`
- `2` Personal Services: manage existing user units
- `3` System Services: browse existing system units

System services are read-only in the TUI until you press `!` to unlock actions for the session.
When a system action needs elevation, the app invokes `sudo` and may prompt for your password in the terminal.
Useful TUI controls:
- `Enter` or `Space`: enable/disable the selected service
- `S`: start or stop the selected existing service
- `R`: restart the selected existing service
- `D`: show details for the selected service
- `/`: search the current view by service name or description
- `C`: clear the active search
- `T`: sort by status
- `E`: sort by enabled state
- `F`: toggle the system-service list between `all` and `curated`

The System view now defaults to `all`, so disabled inactive services remain discoverable after you toggle them off.

Non-interactive helpers:
```bash
python3 -m my_service_mgr --list
python3 -m my_service_mgr --enable dummy-alpha.service
python3 -m my_service_mgr --disable dummy-alpha.service
python3 -m my_service_mgr --list-existing --scope user
python3 -m my_service_mgr --status ssh --scope system
python3 -m my_service_mgr --restart pipewire --scope user
python3 -m my_service_mgr --disable-existing nginx --scope system
```

Service template convention:
- Put `*.service` files in `services/`.
- Put the executable script in `scripts/` with the same stem name:
  - `services/dummy-alpha.service` -> `scripts/dummy-alpha.sh` (or `scripts/dummy-alpha`)
- In the `.service` template, include the placeholder `__SCRIPT_PATH__` (it will be replaced with the installed script path).

Dry-run mode (prints what it would do):
```bash
python3 -m my_service_mgr --dry-run --enable dummy-alpha.service
```

Logs:
- The app writes detailed action logs (including systemctl stdout/stderr on failure) to:
  - `~/.local/state/my-service-mgr/logs/my-service-mgr.log`
  - If that path is not writable, it falls back to `./my-service-mgr.log`.

System vs user mode:
- By default (`--mode auto`), root installs to system units; non-root installs to user units.
- You can force it with `--mode system` or `--mode user`.
- Existing-service commands use `--scope user|system`.
- System listings are filtered to common `.service` units by default; pass `--all-existing` to show the full `systemctl list-unit-files` output for the chosen scope.
- System mutations automatically call `sudo` when needed so you can authenticate in-place instead of rerunning the command manually.
