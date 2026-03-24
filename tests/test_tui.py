from __future__ import annotations

import unittest

from my_service_mgr.tui import (
    SORT_ENABLED,
    SORT_STATUS,
    SYSTEM_FILTER_ALL,
    SYSTEM_FILTER_CURATED,
    _adjust_offset_for_selection,
    _restore_selection,
    _sort_services,
    _system_row_filter_label,
)


class TuiHelpersTests(unittest.TestCase):
    def test_adjust_offset_does_not_scroll_when_moving_within_viewport(self) -> None:
        self.assertEqual(5, _adjust_offset_for_selection(selected=6, offset=5, max_rows=4, total_rows=20))

    def test_adjust_offset_scrolls_only_after_crossing_bottom_edge(self) -> None:
        self.assertEqual(6, _adjust_offset_for_selection(selected=9, offset=5, max_rows=4, total_rows=20))

    def test_adjust_offset_scrolls_when_selection_moves_above_top_edge(self) -> None:
        self.assertEqual(4, _adjust_offset_for_selection(selected=4, offset=5, max_rows=4, total_rows=20))

    def test_sort_services_by_status(self) -> None:
        services = [
            {"unit_name": "b.service", "active": "inactive", "enabled": "disabled"},
            {"unit_name": "c.service", "active": "failed", "enabled": "enabled"},
            {"unit_name": "a.service", "active": "active", "enabled": "disabled"},
        ]

        sorted_rows = _sort_services(services, SORT_STATUS)

        self.assertEqual(["a.service", "c.service", "b.service"], [row["unit_name"] for row in sorted_rows])

    def test_sort_services_by_enabled(self) -> None:
        services = [
            {"unit_name": "b.service", "active": "inactive", "enabled": "disabled"},
            {"unit_name": "c.service", "active": "failed", "enabled": "static"},
            {"unit_name": "a.service", "active": "active", "enabled": "enabled"},
        ]

        sorted_rows = _sort_services(services, SORT_ENABLED)

        self.assertEqual(["a.service", "c.service", "b.service"], [row["unit_name"] for row in sorted_rows])

    def test_restore_selection_prefers_same_service_after_reload(self) -> None:
        services = [
            {"unit_name": "first.service"},
            {"unit_name": "enable-scrolllock-backlight.service"},
            {"unit_name": "third.service"},
        ]

        restored = _restore_selection(services, "enable-scrolllock-backlight.service", 0)

        self.assertEqual(1, restored)

    def test_restore_selection_falls_back_when_service_missing(self) -> None:
        services = [
            {"unit_name": "first.service"},
            {"unit_name": "second.service"},
        ]

        restored = _restore_selection(services, "missing.service", 1)

        self.assertEqual(1, restored)

    def test_system_filter_label(self) -> None:
        self.assertEqual("all", _system_row_filter_label(SYSTEM_FILTER_ALL))
        self.assertEqual("curated", _system_row_filter_label(SYSTEM_FILTER_CURATED))


if __name__ == "__main__":
    unittest.main()
