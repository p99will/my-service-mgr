from __future__ import annotations

import curses
from typing import Any

from .manager import ActionResult, ServiceManager


VIEW_TEMPLATES = "templates"
VIEW_USER = "user"
VIEW_SYSTEM = "system"
VIEWS = [VIEW_TEMPLATES, VIEW_USER, VIEW_SYSTEM]
VIEW_TITLES = {
    VIEW_TEMPLATES: "Templates",
    VIEW_USER: "Personal Services",
    VIEW_SYSTEM: "System Services",
}
SYSTEM_FILTER_ALL = "all"
SYSTEM_FILTER_CURATED = "curated"
SORT_NONE = "default"
SORT_STATUS = "status"
SORT_ENABLED = "enabled"
SORT_LABELS = {
    SORT_NONE: "default",
    SORT_STATUS: "status",
    SORT_ENABLED: "enabled",
}
COLOR_ENABLED = 1
COLOR_DISABLED = 2
COLOR_ACTIVE = 3
COLOR_INACTIVE = 4
COLOR_UNKNOWN = 5


def _truncate_ascii(text: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3] + "..."


def _view_index(view: str) -> int:
    return VIEWS.index(view)


def _enabled_sort_rank(value: str) -> tuple[int, str]:
    order = {
        "enabled": 0,
        "static": 1,
        "disabled": 2,
        "masked": 3,
        "unknown": 4,
    }
    return (order.get(value, 5), value)


def _status_sort_rank(value: str) -> tuple[int, str]:
    order = {
        "active": 0,
        "activating": 1,
        "reloading": 2,
        "failed": 3,
        "inactive": 4,
        "deactivating": 5,
        "unknown": 6,
    }
    return (order.get(value, 7), value)


def _sort_services(services: list[dict[str, str]], sort_mode: str) -> list[dict[str, str]]:
    indexed = list(enumerate(services))
    if sort_mode == SORT_STATUS:
        indexed.sort(key=lambda item: (_status_sort_rank(item[1].get("active", "unknown")), item[1]["unit_name"], item[0]))
    elif sort_mode == SORT_ENABLED:
        indexed.sort(key=lambda item: (_enabled_sort_rank(item[1].get("enabled", "unknown")), item[1]["unit_name"], item[0]))
    return [row for _, row in indexed]


def _system_row_filter_label(system_filter_mode: str) -> str:
    return "all" if system_filter_mode == SYSTEM_FILTER_ALL else "curated"


def _load_services(manager: ServiceManager, view: str, sort_mode: str, system_filter_mode: str) -> list[dict[str, str]]:
    if view == VIEW_TEMPLATES:
        services = manager.list_service_templates_with_status()
    elif view == VIEW_USER:
        services = manager.list_existing_services("user", filtered=False)
    else:
        services = manager.list_existing_services("system", filtered=system_filter_mode == SYSTEM_FILTER_CURATED)
    return _sort_services(services, sort_mode)


def _color_for_enabled(value: str) -> int:
    if value == "enabled":
        return COLOR_ENABLED
    if value in {"disabled", "masked"}:
        return COLOR_DISABLED
    return COLOR_UNKNOWN


def _color_for_active(value: str) -> int:
    if value == "active":
        return COLOR_ACTIVE
    if value in {"inactive", "deactivating"}:
        return COLOR_INACTIVE
    if value == "failed":
        return COLOR_DISABLED
    return COLOR_UNKNOWN


def _compose_attr(base_attr: int, color_pair: int) -> int:
    return base_attr | curses.color_pair(color_pair)


def _init_colors() -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(COLOR_ENABLED, curses.COLOR_GREEN, -1)
    curses.init_pair(COLOR_DISABLED, curses.COLOR_RED, -1)
    curses.init_pair(COLOR_ACTIVE, curses.COLOR_GREEN, -1)
    curses.init_pair(COLOR_INACTIVE, curses.COLOR_YELLOW, -1)
    curses.init_pair(COLOR_UNKNOWN, curses.COLOR_CYAN, -1)


def _visible_capacity(height: int) -> int:
    start_row = 5
    return max(0, height - start_row - 2)


def _adjust_offset_for_selection(selected: int, offset: int, max_rows: int, total_rows: int) -> int:
    if max_rows <= 0 or total_rows <= max_rows:
        return 0
    if selected < offset:
        return selected
    if selected >= offset + max_rows:
        return selected - max_rows + 1
    max_offset = max(0, total_rows - max_rows)
    return min(offset, max_offset)


def _restore_selection(services: list[dict[str, str]], current_unit_name: str | None, fallback_index: int) -> int:
    if not services:
        return 0
    if current_unit_name:
        for idx, service in enumerate(services):
            if service["unit_name"] == current_unit_name:
                return idx
    return min(max(0, fallback_index), len(services) - 1)


def _draw_screen(
    stdscr: Any,
    view: str,
    services: list[dict[str, str]],
    selected: int,
    offset: int,
    message: str,
    sort_mode: str,
    system_filter_mode: str,
    *,
    system_actions_unlocked: bool,
) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()

    tabs = []
    for idx, name in enumerate(VIEWS, start=1):
        marker = "*" if name == view else " "
        tabs.append(f"{idx}:{VIEW_TITLES[name]}{marker}")
    title = "my-service-mgr [" + " | ".join(tabs) + "]"
    stdscr.addnstr(0, 0, _truncate_ascii(title, width - 1), width - 1, curses.A_BOLD)

    primary_keys = "[Arrows] Move  [Enter/Space] Toggle  [S] Start/Stop  [R] Restart  [D] Details"
    secondary_keys = "[1/2/3] View  [Tab] Next View  [T] Sort Status  [E] Sort Enabled  [F] System Filter  [!] Unlock System  [Q] Quit"
    stdscr.addnstr(1, 0, _truncate_ascii(primary_keys, width - 1), width - 1, curses.A_BOLD)
    stdscr.addnstr(2, 0, _truncate_ascii(secondary_keys, width - 1), width - 1, curses.A_DIM)
    status_line = f"Sort: {SORT_LABELS[sort_mode]}  System Filter: {_system_row_filter_label(system_filter_mode)}"
    stdscr.addnstr(3, 0, _truncate_ascii(status_line, width - 1), width - 1, curses.A_DIM)

    start_row = 5
    max_rows = max(0, height - start_row - 2)
    if max_rows < 1:
        stdscr.refresh()
        return

    visible = services[offset : offset + max_rows]

    enabled_width = 10
    active_width = 10
    checkbox_width = 4
    name_width = 28
    inner_width = max(0, width - 1)
    active_x = max(0, inner_width - active_width)
    enabled_x = max(0, active_x - enabled_width - 1)
    name_x = checkbox_width + 1
    max_name_width = max(0, enabled_x - name_x - 1)
    name_draw_width = min(name_width, max_name_width)
    desc_x = name_x + name_draw_width + 1
    desc_draw_width = max(0, enabled_x - desc_x - 1)

    for idx, row in enumerate(visible):
        absolute_idx = offset + idx
        row_y = start_row + idx
        enabled = row.get("enabled", "unknown")
        active = row.get("active", "unknown")
        checkbox = "[x]" if enabled == "enabled" else "[ ]"
        main_attr = curses.A_REVERSE if absolute_idx == selected else curses.A_NORMAL
        desc_attr = (main_attr | curses.A_BOLD) if absolute_idx == selected else (main_attr | curses.A_DIM)

        stdscr.addnstr(row_y, 0, checkbox, checkbox_width, main_attr)
        stdscr.addnstr(
            row_y,
            name_x,
            _truncate_ascii(row["unit_name"], name_draw_width).ljust(name_draw_width),
            name_draw_width,
            main_attr,
        )
        if desc_draw_width > 0:
            stdscr.addnstr(
                row_y,
                desc_x,
                _truncate_ascii(row.get("description", ""), desc_draw_width),
                desc_draw_width,
                desc_attr,
            )
        stdscr.addnstr(
            row_y,
            enabled_x,
            _truncate_ascii(enabled, enabled_width).rjust(enabled_width),
            enabled_width,
            _compose_attr(main_attr, _color_for_enabled(enabled)),
        )
        stdscr.addnstr(
            row_y,
            active_x,
            _truncate_ascii(active, active_width).rjust(active_width),
            active_width,
            _compose_attr(main_attr, _color_for_active(active)),
        )

    if not services:
        stdscr.addnstr(start_row, 0, "No services available in this view.", width - 1, curses.A_DIM)

    if view == VIEW_SYSTEM and not system_actions_unlocked:
        lock_msg = "System view is read-only until you press ! to unlock actions."
        stdscr.addnstr(height - 2, 0, _truncate_ascii(lock_msg, width - 1), width - 1, curses.A_DIM)

    msg = message[: width - 1]
    stdscr.addnstr(height - 1, 0, msg, width - 1, curses.A_BOLD if "Error:" in msg else curses.A_NORMAL)
    stdscr.refresh()


def _toggle_selected(manager: ServiceManager, view: str, row: dict[str, str]) -> ActionResult:
    unit_name = row["unit_name"]
    enabled = row.get("enabled", "disabled")
    if view == VIEW_TEMPLATES:
        if enabled == "enabled":
            return manager.disable_by_unit_name(unit_name)
        return manager.enable_by_unit_name(unit_name)

    scope = row["scope"]
    if enabled == "enabled":
        return manager.disable_existing_unit(unit_name, scope)
    return manager.enable_existing_unit(unit_name, scope)


def _start_or_stop_selected(manager: ServiceManager, row: dict[str, str]) -> ActionResult:
    scope = row["scope"]
    unit_name = row["unit_name"]
    if row.get("active") == "active":
        return manager.stop_existing_unit(unit_name, scope)
    return manager.start_existing_unit(unit_name, scope)


def _restart_selected(manager: ServiceManager, row: dict[str, str]) -> ActionResult:
    return manager.restart_existing_unit(row["unit_name"], row["scope"])


def _details_selected(manager: ServiceManager, row: dict[str, str]) -> ActionResult:
    if row["source"] == "template":
        return ActionResult(
            ok=True,
            unit_name=row["unit_name"],
            action="details",
            message=(
                f"{row['unit_name']} [template/{row['scope']}] enabled={row['enabled']} "
                f"active={row['active']} state={row['state']}"
            ),
            actual_enabled=row["enabled"],
            scope=row["scope"],
            source="template",
        )
    return manager.status_existing_unit(row["unit_name"], row["scope"])


def _run_with_curses_pause(stdscr: Any, manager: ServiceManager, row: dict[str, str], action: Any) -> ActionResult:
    needs_elevation = row["scope"] == "system" and manager.needs_elevation("system")
    if needs_elevation:
        curses.def_prog_mode()
        curses.endwin()
        try:
            print(f"sudo authentication may be required for {row['unit_name']}.")
            manager.ensure_elevation("system")
        finally:
            curses.reset_prog_mode()
            stdscr.refresh()
            curses.doupdate()
    return action()


def run_tui(manager: ServiceManager) -> None:
    def _curses_main(stdscr: Any) -> None:
        view = VIEW_TEMPLATES
        selected = 0
        offset = 0
        message = ""
        sort_mode = SORT_NONE
        system_filter_mode = SYSTEM_FILTER_ALL
        system_actions_unlocked = False
        services = _load_services(manager, view, sort_mode, system_filter_mode)

        _init_colors()
        curses.curs_set(0)
        stdscr.keypad(True)

        while True:
            max_rows = _visible_capacity(stdscr.getmaxyx()[0])
            if services:
                selected = min(selected, len(services) - 1)
            else:
                selected = 0
            offset = _adjust_offset_for_selection(selected, offset, max_rows, len(services))

            _draw_screen(
                stdscr,
                view,
                services,
                selected=selected,
                offset=offset,
                message=message,
                sort_mode=sort_mode,
                system_filter_mode=system_filter_mode,
                system_actions_unlocked=system_actions_unlocked,
            )
            message = ""
            key = stdscr.getch()

            if key in (ord("q"), ord("Q")):
                break
            if key in (ord("1"), ord("2"), ord("3")):
                view = VIEWS[key - ord("1")]
                services = _load_services(manager, view, sort_mode, system_filter_mode)
                selected = 0
                offset = 0
                continue
            if key == 9:
                view = VIEWS[(_view_index(view) + 1) % len(VIEWS)]
                services = _load_services(manager, view, sort_mode, system_filter_mode)
                selected = 0
                offset = 0
                continue
            if key == ord("!"):
                system_actions_unlocked = not system_actions_unlocked
                message = "System actions unlocked." if system_actions_unlocked else "System actions locked."
                continue
            if key in (ord("t"), ord("T")):
                sort_mode = SORT_NONE if sort_mode == SORT_STATUS else SORT_STATUS
                services = _load_services(manager, view, sort_mode, system_filter_mode)
                selected = 0
                offset = 0
                message = f"Sort set to {SORT_LABELS[sort_mode]}."
                continue
            if key in (ord("e"), ord("E")):
                sort_mode = SORT_NONE if sort_mode == SORT_ENABLED else SORT_ENABLED
                services = _load_services(manager, view, sort_mode, system_filter_mode)
                selected = 0
                offset = 0
                message = f"Sort set to {SORT_LABELS[sort_mode]}."
                continue
            if key in (ord("f"), ord("F")):
                system_filter_mode = SYSTEM_FILTER_CURATED if system_filter_mode == SYSTEM_FILTER_ALL else SYSTEM_FILTER_ALL
                services = _load_services(manager, view, sort_mode, system_filter_mode)
                selected = _restore_selection(services, None, selected)
                offset = _adjust_offset_for_selection(selected, offset, max_rows, len(services))
                message = f"System filter set to {_system_row_filter_label(system_filter_mode)}."
                continue
            if key == curses.KEY_UP:
                if selected > 0:
                    selected -= 1
                    if max_rows > 0 and selected < offset:
                        offset = selected
                continue
            if key == curses.KEY_DOWN:
                if services and selected < len(services) - 1:
                    selected += 1
                    if max_rows > 0 and selected >= offset + max_rows:
                        offset = selected - max_rows + 1
                continue
            if not services:
                message = "No services in this view."
                continue

            row = services[selected]
            if row["scope"] == "system" and not system_actions_unlocked and key in (
                curses.KEY_ENTER,
                10,
                13,
                ord(" "),
                ord("s"),
                ord("S"),
                ord("r"),
                ord("R"),
            ):
                message = "System view is locked. Press ! to unlock actions."
                continue
            try:
                if key in (curses.KEY_ENTER, 10, 13, ord(" ")):
                    result = _run_with_curses_pause(stdscr, manager, row, lambda: _toggle_selected(manager, view, row))
                elif key in (ord("s"), ord("S")):
                    if view == VIEW_TEMPLATES:
                        message = "Start/stop is only available for existing services."
                        continue
                    result = _run_with_curses_pause(stdscr, manager, row, lambda: _start_or_stop_selected(manager, row))
                elif key in (ord("r"), ord("R")):
                    if view == VIEW_TEMPLATES:
                        message = "Restart is only available for existing services."
                        continue
                    result = _run_with_curses_pause(stdscr, manager, row, lambda: _restart_selected(manager, row))
                elif key in (ord("d"), ord("D")):
                    result = _details_selected(manager, row)
                else:
                    continue
            except Exception as exc:
                message = f"Error: {exc}"
                continue

            message = result.message
            current_unit_name = row["unit_name"]
            services = _load_services(manager, view, sort_mode, system_filter_mode)
            selected = _restore_selection(services, current_unit_name, selected)
            offset = _adjust_offset_for_selection(selected, offset, max_rows, len(services))

    curses.wrapper(_curses_main)
