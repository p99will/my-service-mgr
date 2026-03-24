from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from my_service_mgr.versioning import VersionFiles, bump_patch, parse_version, read_current_version, write_bumped_version


class VersioningTests(unittest.TestCase):
    def test_parse_version(self) -> None:
        self.assertEqual((0, 1, 0), parse_version("0.1.0"))

    def test_bump_patch(self) -> None:
        self.assertEqual("0.1.1", bump_patch("0.1.0"))

    def test_write_bumped_version_updates_project_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pyproject = root / "pyproject.toml"
            package_init = root / "__init__.py"
            pyproject.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
            package_init.write_text('__version__ = "1.2.3"\n', encoding="utf-8")

            old_version, new_version = write_bumped_version(VersionFiles(pyproject=pyproject, package_init=package_init))

            self.assertEqual("1.2.3", old_version)
            self.assertEqual("1.2.4", new_version)
            self.assertEqual("1.2.4", read_current_version(pyproject.read_text(encoding="utf-8")))
            self.assertIn('__version__ = "1.2.4"', package_init.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
