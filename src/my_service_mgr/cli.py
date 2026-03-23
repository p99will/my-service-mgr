from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .manager import ServiceManager
from .tui import run_tui


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="my-service-mgr", description="Manage systemd services from templates.")
    p.add_argument(
        "--services-dir",
        type=Path,
        default=Path.cwd() / "services",
        help="Directory containing *.service templates (default: ./services)",
    )
    p.add_argument(
        "--scripts-dir",
        type=Path,
        default=Path.cwd() / "scripts",
        help="Directory containing scripts referenced by the services (default: ./scripts)",
    )
    p.add_argument("--dry-run", action="store_true", help="Show what would happen, but don't modify the system.")
    p.add_argument("--mode", choices=["auto", "system", "user"], default="auto", help="Select systemd unit installation mode.")
    p.add_argument("--list", action="store_true", help="List available service templates and installed status.")
    p.add_argument("--enable", metavar="SERVICE_UNIT", help="Enable/add a service unit non-interactively.")
    p.add_argument("--disable", metavar="SERVICE_UNIT", help="Disable/remove a service unit non-interactively.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        manager = ServiceManager(
            services_dir=args.services_dir,
            scripts_dir=args.scripts_dir,
            mode=args.mode,
            dry_run=args.dry_run,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.list:
        rows = manager.list_service_templates_with_status()
        for row in rows:
            # Keep this output stable for scripting.
            print(f"{row['unit_name']}\t{row['state']}\t{row['enabled']}\t{row['active']}")
        return 0

    if args.enable:
        try:
            result = manager.enable_by_unit_name(args.enable)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        if result.ok:
            print(result.message)
            return 0
        print(result.message, file=sys.stderr)
        if result.error:
            print(result.error, file=sys.stderr)
        return 1

    if args.disable:
        try:
            result = manager.disable_by_unit_name(args.disable)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        if result.ok:
            print(result.message)
            return 0
        print(result.message, file=sys.stderr)
        if result.error:
            print(result.error, file=sys.stderr)
        return 1

    if not sys.stdout.isatty():
        print("No TTY detected. Use --list / --enable / --disable for non-interactive usage.", file=sys.stderr)
        return 2

    run_tui(manager)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
