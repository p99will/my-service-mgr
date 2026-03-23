# my-service-mgr

Manage custom services and scripts on Linux (Pop!_OS).

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

