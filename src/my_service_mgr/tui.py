from __future__ import annotations

import curses
from typing import Any

from .manager import ServiceManager


def _draw_screen(stdscr: Any, manager: ServiceManager, services: list[dict[str, str]], selected: int, message: str) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    title = "my-service-mgr (arrows to select, Enter to toggle, q to quit)"
    stdscr.addnstr(0, 0, title, w - 1, curses.A_BOLD)

    start_row = 2
    max_rows = h - start_row - 2

    if max_rows < 1:
        stdscr.refresh()
        return

    offset = 0
    if selected >= max_rows:
        offset = selected - max_rows + 1

    visible = services[offset : offset + max_rows]

    for i, row in enumerate(visible):
        idx = offset + i
        unit_name = row["unit_name"]
        description = row.get("description", "")
        state = row["state"]
        enabled = row["enabled"]
        active = row["active"]

        col = 0
        width = max(0, w - 1)
        main_attr = curses.A_REVERSE if idx == selected else curses.A_NORMAL
        dim_attr = (curses.A_REVERSE if idx == selected else curses.A_NORMAL) | curses.A_DIM

        unit_name_str = unit_name
        if len(unit_name_str) > width:
            unit_name_str = unit_name_str[: max(0, width - 4)] + "..."

        stdscr.addnstr(start_row + i, col, unit_name_str, width - col, main_attr)
        col += min(len(unit_name_str), width - col) + 1  # +1 for spacing
        if col >= width:
            continue

        desc_str = description or ""
        remaining = width - col
        if len(desc_str) > remaining:
            desc_str = desc_str[: max(0, remaining - 4)] + "..."
        stdscr.addnstr(start_row + i, col, desc_str, width - col, dim_attr)
        col += min(len(desc_str), width - col)
        if col < width:
            # Keep the rest of the status info readable.
            status_str = f"  {state} enabled={enabled} active={active}"
            if len(status_str) > width - col:
                status_str = status_str[: max(0, width - col - 1)] + "..."
            stdscr.addnstr(start_row + i, col, status_str, width - col, main_attr)

    help_line = "Enter: enable/add if disabled, remove/disable if enabled"
    stdscr.addnstr(h - 2, 0, help_line[: w - 1], w - 1, curses.A_DIM)

    msg = message[: w - 1]
    stdscr.addnstr(h - 1, 0, msg, w - 1, curses.A_BOLD if "Error:" in msg else curses.A_NORMAL)
    stdscr.refresh()


def _toggle_selected(manager: ServiceManager, services: list[dict[str, str]], selected: int) -> str:
    row = services[selected]
    unit_name = row["unit_name"]
    enabled = row["enabled"]

    # Treat "enabled" as installed+enabled; everything else falls back to enable.
    try:
        if enabled == "enabled":
            manager.disable_by_unit_name(unit_name)
            return f"Disabled {unit_name}"
        else:
            manager.enable_by_unit_name(unit_name)
            return f"Enabled {unit_name}"
    except Exception as e:
        return f"Error: {e}"


def run_tui(manager: ServiceManager) -> None:
    services = manager.list_service_templates_with_status()
    if not services:
        raise RuntimeError("No *.service templates found in services directory.")

    def _curses_main(stdscr: Any) -> None:
        curses.curs_set(0)
        stdscr.keypad(True)
        selected = 0
        message = ""

        while True:
            _draw_screen(stdscr, manager, services, selected=selected, message=message)
            message = ""

            key = stdscr.getch()
            if key in (ord("q"), ord("Q")):
                break
            if key == curses.KEY_UP:
                selected = max(0, selected - 1)
            elif key == curses.KEY_DOWN:
                selected = min(len(services) - 1, selected + 1)
            elif key in (curses.KEY_ENTER, 10, 13):
                # Show a quick message while the operation runs.
                _draw_screen(stdscr, manager, services, selected=selected, message="Working...")
                stdscr.refresh()
                message = _toggle_selected(manager, services, selected)
                services = manager.list_service_templates_with_status()

    curses.wrapper(_curses_main)

