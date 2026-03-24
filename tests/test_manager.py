from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from my_service_mgr.manager import ServiceManager


class ServiceManagerExistingServicesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.manager = ServiceManager(
            services_dir=root / "services",
            scripts_dir=root / "scripts",
            dry_run=True,
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_list_existing_services_user_scope_shows_disabled_units(self) -> None:
        responses = [
            CompletedProcess(args=[], returncode=0, stdout="alpha.service enabled\nbeta.service disabled\n", stderr=""),
            CompletedProcess(
                args=[],
                returncode=0,
                stdout=(
                    "alpha.service loaded active running Alpha Service\n"
                    "beta.service loaded inactive dead Beta Service\n"
                ),
                stderr="",
            ),
        ]
        with patch("my_service_mgr.manager._run", side_effect=responses):
            rows = self.manager.list_existing_services("user", filtered=False)

        self.assertEqual(["alpha.service", "beta.service"], [row["unit_name"] for row in rows])
        self.assertEqual("enabled", rows[0]["enabled"])
        self.assertEqual("disabled", rows[1]["enabled"])

    def test_list_existing_services_system_scope_filters_low_level_units(self) -> None:
        responses = [
            CompletedProcess(
                args=[],
                returncode=0,
                stdout=(
                    "dbus.service static\n"
                    "nginx.service enabled\n"
                    "systemd-timesyncd.service enabled\n"
                    "off.service disabled\n"
                ),
                stderr="",
            ),
            CompletedProcess(
                args=[],
                returncode=0,
                stdout=(
                    "dbus.service loaded active running D-Bus System Message Bus\n"
                    "nginx.service loaded active running A high performance web server\n"
                    "systemd-timesyncd.service loaded active running Network Time Synchronization\n"
                    "off.service loaded inactive dead Disabled Service\n"
                ),
                stderr="",
            ),
        ]
        with patch("my_service_mgr.manager._run", side_effect=responses):
            rows = self.manager.list_existing_services("system", filtered=True)

        self.assertEqual(["nginx.service"], [row["unit_name"] for row in rows])

    def test_enable_existing_unit_dry_run_reports_command(self) -> None:
        result = self.manager.enable_existing_unit("demo", "user")

        self.assertTrue(result.ok)
        self.assertEqual("existing", result.source)
        self.assertIn("systemctl --user enable --now demo.service", result.message)

    def test_status_existing_unit_normalizes_service_name(self) -> None:
        responses = [
            CompletedProcess(args=[], returncode=0, stdout="enabled\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="active\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="Demo Service\n", stderr=""),
        ]
        with patch("my_service_mgr.manager._run", side_effect=responses):
            result = self.manager.status_existing_unit("demo", "user")

        self.assertTrue(result.ok)
        self.assertIn("demo.service [user]", result.message)
        self.assertIn("description=Demo Service", result.message)

    def test_system_mode_manager_initializes_without_root(self) -> None:
        with patch("my_service_mgr.manager.os.geteuid", return_value=1000):
            manager = ServiceManager(
                services_dir=Path(self.tmpdir.name) / "services",
                scripts_dir=Path(self.tmpdir.name) / "scripts",
                mode="system",
                dry_run=False,
            )

        self.assertEqual("system", manager.template_scope)

    def test_enable_existing_unit_system_scope_uses_sudo(self) -> None:
        manager = ServiceManager(
            services_dir=Path(self.tmpdir.name) / "services",
            scripts_dir=Path(self.tmpdir.name) / "scripts",
            dry_run=False,
        )
        responses = [
            CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="enabled\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="active\n", stderr=""),
            CompletedProcess(args=[], returncode=0, stdout="Demo Service\n", stderr=""),
        ]
        with patch("my_service_mgr.manager.os.geteuid", return_value=1000):
            with patch("my_service_mgr.manager._run", side_effect=responses) as mocked_run:
                result = manager.enable_existing_unit("demo", "system")

        self.assertTrue(result.ok)
        self.assertTrue(mocked_run.call_args_list[0].kwargs["use_sudo"])


if __name__ == "__main__":
    unittest.main()
