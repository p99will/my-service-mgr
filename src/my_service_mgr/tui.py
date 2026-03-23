from __future__ import annotations

import curses
from typing import Any

from .manager import ServiceManager


def _truncate_ascii(s: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(s) <= max_len:
        return s
    if max_len <= 3:
        return s[:max_len]
    return s[: max_len - 3] + "..."


def _draw_screen(stdscr: Any, manager: ServiceManager, services: list[dict[str, str]], selected: int, message: str) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    title = "my-service-mgr (arrows select, Space/Enter toggle, q quit)"
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

    # Simple table layout (fixed columns + truncation).
    # Keep status at a fixed right edge to align rows.
    status_width = 9
    checkbox_width = 4  # "[x]"
    name_width = 26
    inner_width = max(0, w - 1)
    status_draw_width = min(status_width, inner_width)
    status_start_x = max(0, inner_width - status_draw_width)
    name_start_x = checkbox_width + 1
    max_name_width = max(0, status_start_x - name_start_x - 1)  # 1 for space between name/desc
    name_draw_width = min(name_width, max_name_width)
    desc_start_x = name_start_x + name_draw_width + 1
    desc_draw_width = max(0, status_start_x - desc_start_x)

    for i, row in enumerate(visible):
        idx = offset + i
        unit_name = row["unit_name"]
        description = row.get("description", "") or ""
        enabled = row.get("enabled", "disabled")

        is_enabled = enabled == "enabled"
        checkbox_str = "[x]" if is_enabled else "[ ]"
        status_str = "enabled" if is_enabled else ("disabled" if enabled != "unknown" else "unknown")

        main_attr = curses.A_REVERSE if idx == selected else curses.A_NORMAL
        dim_attr = (curses.A_REVERSE if idx == selected else curses.A_NORMAL) | curses.A_DIM

        row_y = start_row + i
        stdscr.addnstr(row_y, 0, checkbox_str, checkbox_width, main_attr)

        if name_draw_width > 0:
            name_str = _truncate_ascii(unit_name, name_draw_width)
            stdscr.addnstr(row_y, name_start_x, name_str.ljust(name_draw_width), name_draw_width, main_attr)

        if desc_draw_width > 0:
            desc_str = _truncate_ascii(description, desc_draw_width)
            stdscr.addnstr(row_y, desc_start_x, desc_str, desc_draw_width, dim_attr)

        if status_draw_width > 0:
            status_text = _truncate_ascii(status_str, status_draw_width).rjust(status_draw_width)
            stdscr.addnstr(row_y, status_start_x, status_text, status_draw_width, main_attr)

    help_line = "Space/Enter: toggle enabled checkbox  q: quit"
    stdscr.addnstr(h - 2, 0, _truncate_ascii(help_line, w - 1), w - 1, curses.A_DIM)

    msg = message[: w - 1]
    stdscr.addnstr(h - 1, 0, msg, w - 1, curses.A_BOLD if "Error:" in msg else curses.A_NORMAL)
    stdscr.refresh()


def _toggle_selected(manager: ServiceManager, services: list[dict[str, str]], selected: int) -> str:
    row = services[selected]
    unit_name = row["unit_name"]
    try:
        enabled = row.get("enabled", "disabled")
        is_enabled = enabled == "enabled"
        if is_enabled:
            result = manager.disable_by_unit_name(unit_name)
        else:
            result = manager.enable_by_unit_name(unit_name)
        return result.message
    except Exception as e:
        return f"Error: {e}"


def run_tui(manager: ServiceManager) -> None:
    services = manager.list_service_templates_with_status()
    if not services:
        raise RuntimeError("No *.service templates found in services directory.")

    def _curses_main(stdscr: Any) -> None:
        nonlocal services
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
            elif key in (curses.KEY_ENTER, 10, 13, ord(" ")):
                # Show a quick message while the operation runs.
                _draw_screen(stdscr, manager, services, selected=selected, message="Working...")
                stdscr.refresh()
                message = _toggle_selected(manager, services, selected)
                services = manager.list_service_templates_with_status()
                if services:
                    selected = min(selected, len(services) - 1)

    curses.wrapper(_curses_main)

