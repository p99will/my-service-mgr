from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .manager import ActionResult, ServiceManager
from .tui import run_tui


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="my-service-mgr", description="Manage systemd services from templates.")
    parser.add_argument(
        "--services-dir",
        type=Path,
        default=Path.cwd() / "services",
        help="Directory containing *.service templates (default: ./services)",
    )
    parser.add_argument(
        "--scripts-dir",
        type=Path,
        default=Path.cwd() / "scripts",
        help="Directory containing scripts referenced by the services (default: ./scripts)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen, but don't modify the system.")
    parser.add_argument("--mode", choices=["auto", "system", "user"], default="auto", help="Default template install scope.")
    parser.add_argument("--scope", choices=["user", "system"], default="user", help="Scope for existing-service actions.")
    parser.add_argument("--list", action="store_true", help="List available service templates and installed status.")
    parser.add_argument("--enable", metavar="SERVICE_UNIT", help="Enable/add a template-backed service unit.")
    parser.add_argument("--disable", metavar="SERVICE_UNIT", help="Disable/remove a template-backed service unit.")
    parser.add_argument("--list-existing", action="store_true", help="List existing services from systemd in the selected scope.")
    parser.add_argument("--all-existing", action="store_true", help="Include filtered low-level system services in existing-service listings.")
    parser.add_argument("--enable-existing", metavar="SERVICE_UNIT", help="Enable and start an existing service unit.")
    parser.add_argument("--disable-existing", metavar="SERVICE_UNIT", help="Disable and stop an existing service unit.")
    parser.add_argument("--start", metavar="SERVICE_UNIT", help="Start an existing service unit.")
    parser.add_argument("--stop", metavar="SERVICE_UNIT", help="Stop an existing service unit.")
    parser.add_argument("--restart", metavar="SERVICE_UNIT", help="Restart an existing service unit.")
    parser.add_argument("--status", metavar="SERVICE_UNIT", help="Show status for an existing service unit.")
    return parser


def _print_rows(rows: list[dict[str, str]], *, include_scope: bool) -> None:
    for row in rows:
        if include_scope:
            print(
                f"{row['unit_name']}\t{row['scope']}\t{row['source']}\t"
                f"{row['state']}\t{row['enabled']}\t{row['active']}"
            )
        else:
            print(f"{row['unit_name']}\t{row['state']}\t{row['enabled']}\t{row['active']}")


def _print_result(result: ActionResult) -> int:
    if result.ok:
        print(result.message)
        return 0
    print(result.message, file=sys.stderr)
    if result.error:
        print(result.error, file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        manager = ServiceManager(
            services_dir=args.services_dir,
            scripts_dir=args.scripts_dir,
            mode=args.mode,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        if args.list:
            _print_rows(manager.list_service_templates_with_status(), include_scope=False)
            return 0
        if args.list_existing:
            _print_rows(manager.list_existing_services(args.scope, filtered=not args.all_existing), include_scope=True)
            return 0
        if args.enable:
            return _print_result(manager.enable_by_unit_name(args.enable))
        if args.disable:
            return _print_result(manager.disable_by_unit_name(args.disable))
        if args.enable_existing:
            return _print_result(manager.enable_existing_unit(args.enable_existing, args.scope))
        if args.disable_existing:
            return _print_result(manager.disable_existing_unit(args.disable_existing, args.scope))
        if args.start:
            return _print_result(manager.start_existing_unit(args.start, args.scope))
        if args.stop:
            return _print_result(manager.stop_existing_unit(args.stop, args.scope))
        if args.restart:
            return _print_result(manager.restart_existing_unit(args.restart, args.scope))
        if args.status:
            return _print_result(manager.status_existing_unit(args.status, args.scope))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not sys.stdout.isatty():
        print(
            "No TTY detected. Use --list, --list-existing, or explicit action flags for non-interactive usage.",
            file=sys.stderr,
        )
        return 2

    run_tui(manager)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
