from __future__ import annotations

import unittest

from my_service_mgr.tui import (
    SORT_ENABLED,
    SORT_STATUS,
    _adjust_offset_for_selection,
    _sort_services,
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


if __name__ == "__main__":
    unittest.main()
