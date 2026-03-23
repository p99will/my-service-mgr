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

## Project layout
- `src/my_service_mgr/`: Python package code
- `scripts/`: helper scripts you want to keep in-repo
- `services/`: future service unit templates / artifacts

## Usage

From the repo root, run the arrow-based TUI (requires a TTY):
```bash
python3 -m my_service_mgr
```

Non-interactive helpers:
```bash
python3 -m my_service_mgr --list
python3 -m my_service_mgr --enable dummy-alpha.service
python3 -m my_service_mgr --disable dummy-alpha.service
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
- You can force it with `--mode system` (requires `sudo`) or `--mode user`.

