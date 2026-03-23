from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCRIPT_PATH_PLACEHOLDER = "__SCRIPT_PATH__"


@dataclass(frozen=True)
class SystemdContext:
    unit_dir: Path
    bin_dir: Path
    systemctl_base: list[str]

    @property
    def is_user_mode(self) -> bool:
        return "--user" in self.systemctl_base


@dataclass(frozen=True)
class ServiceTemplate:
    unit_template_path: Path
    scripts_dir: Path
    unit_install_dir: Path
    bin_install_dir: Path

    @property
    def unit_name(self) -> str:
        return self.unit_template_path.name  # includes ".service"

    @property
    def unit_stem(self) -> str:
        return self.unit_template_path.stem

    def resolve_script_template_path(self) -> Path:
        """
        Convention:
        - scripts/<stem>.sh
        - scripts/<stem>
        """
        candidates = [
            self.scripts_dir / f"{self.unit_stem}.sh",
            self.scripts_dir / self.unit_stem,
        ]
        for p in candidates:
            if p.exists():
                return p
        raise FileNotFoundError(
            f"Missing script template for unit '{self.unit_name}'. Tried: "
            + ", ".join(str(p) for p in candidates)
        )

    def installed_unit_path(self) -> Path:
        return self.unit_install_dir / self.unit_name

    def installed_script_path(self) -> Path:
        script_template = self.resolve_script_template_path()
        return self.bin_install_dir / script_template.name

    def render_unit_text(self, installed_script_path: Path) -> str:
        text = self.unit_template_path.read_text(encoding="utf-8")
        if SCRIPT_PATH_PLACEHOLDER not in text:
            raise ValueError(
                f"Unit template '{self.unit_template_path}' is missing placeholder "
                f"'{SCRIPT_PATH_PLACEHOLDER}' in ExecStart (or similar)."
            )
        return text.replace(SCRIPT_PATH_PLACEHOLDER, str(installed_script_path))

    def description(self) -> str:
        """
        Reads `Description=` from the unit template.
        """
        text = self.unit_template_path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            m = re.match(r"^Description\s*=\s*(.*?)\s*$", stripped)
            if m:
                return m.group(1) or ""
        return ""


def _detect_systemd_context(dry_run: bool) -> SystemdContext:
    # Root/system: system units.
    if os.geteuid() == 0:
        return SystemdContext(
            unit_dir=Path("/etc/systemd/system"),
            bin_dir=Path("/usr/local/bin"),
            systemctl_base=["systemctl"],
        )

    # Non-root/user: user units.
    # Note: user units still require systemd --user (usually available in desktop sessions).
    if dry_run:
        # For dry-run we still choose user paths.
        pass
    return SystemdContext(
        unit_dir=Path("~/.config/systemd/user").expanduser(),
        bin_dir=Path("~/.local/bin").expanduser(),
        systemctl_base=["systemctl", "--user"],
    )


def _run(systemctl_base: list[str], args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = systemctl_base + args
    return subprocess.run(cmd, check=False, text=True, capture_output=True)


class ServiceManager:
    def __init__(self, services_dir: Path, scripts_dir: Path, dry_run: bool = False) -> None:
        self.services_dir = services_dir
        self.scripts_dir = scripts_dir
        self.dry_run = dry_run
        self.ctx = _detect_systemd_context(dry_run=dry_run)

        if not self.services_dir.exists():
            raise FileNotFoundError(f"Services directory does not exist: {self.services_dir}")
        if not self.scripts_dir.exists():
            raise FileNotFoundError(f"Scripts directory does not exist: {self.scripts_dir}")

    def discover_service_templates(self) -> list[ServiceTemplate]:
        templates: list[ServiceTemplate] = []
        for p in sorted(self.services_dir.glob("*.service")):
            templates.append(
                ServiceTemplate(
                    unit_template_path=p,
                    scripts_dir=self.scripts_dir,
                    unit_install_dir=self.ctx.unit_dir,
                    bin_install_dir=self.ctx.bin_dir,
                )
            )
        return templates

    def _installed_state(self, unit_name: str) -> tuple[str, str, str]:
        """
        Returns:
        - state: human readable ("enabled/disabled/unknown")
        - enabled: "enabled"/"disabled"/"unknown"
        - active: "active"/"inactive"/"unknown"
        """
        unit_path = self.ctx.unit_dir / unit_name
        unit_present = unit_path.exists()
        if not unit_present:
            return ("disabled", "disabled", "inactive")

        enabled_proc = _run(self.ctx.systemctl_base, ["is-enabled", unit_name])
        enabled_out = (enabled_proc.stdout or "").strip()
        enabled = "unknown"
        if enabled_out == "enabled":
            enabled = "enabled"
        elif enabled_out in {"disabled", "static"}:
            enabled = enabled_out

        active_proc = _run(self.ctx.systemctl_base, ["is-active", unit_name])
        active_out = (active_proc.stdout or "").strip()
        active = "unknown"
        if active_out in {"active", "inactive"}:
            active = active_out

        # If unit file exists but systemctl isn't confident, call it unknown.
        if enabled == "unknown":
            return ("unknown", "unknown", active)

        return (enabled, enabled, active)

    def list_service_templates_with_status(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for t in self.discover_service_templates():
            state, enabled, active = self._installed_state(t.unit_name)
            rows.append(
                {
                    "unit_name": t.unit_name,
                    "description": t.description(),
                    "state": state,
                    "enabled": enabled,
                    "active": active,
                }
            )
        return rows

    def enable_by_unit_name(self, unit_name: str) -> None:
        template = self._get_template(unit_name)
        self._install(template)

    def disable_by_unit_name(self, unit_name: str) -> None:
        template = self._get_template(unit_name)
        self._uninstall(template)

    def _get_template(self, unit_name: str) -> ServiceTemplate:
        if not unit_name.endswith(".service"):
            unit_name = unit_name + ".service"
        p = self.services_dir / unit_name
        if not p.exists():
            raise FileNotFoundError(f"Unknown service template: {p}")
        return ServiceTemplate(
            unit_template_path=p,
            scripts_dir=self.scripts_dir,
            unit_install_dir=self.ctx.unit_dir,
            bin_install_dir=self.ctx.bin_dir,
        )

    def _install(self, template: ServiceTemplate) -> None:
        installed_script_path = template.installed_script_path()
        installed_unit_path = template.installed_unit_path()

        if self.dry_run:
            print(f"[dry-run] Install script -> {installed_script_path}")
            print(f"[dry-run] Install unit   -> {installed_unit_path}")
            print(f"[dry-run] systemctl {self.ctx.systemctl_base} enable --now {template.unit_name}")
            return

        installed_script_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template.resolve_script_template_path(), installed_script_path)
        installed_script_path.chmod(0o755)

        self.ctx.unit_dir.mkdir(parents=True, exist_ok=True)
        rendered = template.render_unit_text(installed_script_path=installed_script_path)
        installed_unit_path.write_text(rendered, encoding="utf-8")

        # Reload and enable/start.
        _run(self.ctx.systemctl_base, ["daemon-reload"])
        enable_proc = _run(self.ctx.systemctl_base, ["enable", "--now", template.unit_name])
        if enable_proc.returncode != 0:
            raise RuntimeError(
                f"Failed to enable/start {template.unit_name}:\n{enable_proc.stderr.strip() or enable_proc.stdout.strip()}"
            )

    def _uninstall(self, template: ServiceTemplate) -> None:
        installed_script_path = template.installed_script_path()
        installed_unit_path = template.installed_unit_path()

        if self.dry_run:
            print(f"[dry-run] Disable/remove unit -> {installed_unit_path}")
            print(f"[dry-run] systemctl {self.ctx.systemctl_base} disable --now {template.unit_name}")
            print(f"[dry-run] Remove script -> {installed_script_path}")
            return

        # Best-effort stop/disable (unit may not exist).
        _run(self.ctx.systemctl_base, ["disable", "--now", template.unit_name])
        if installed_unit_path.exists():
            installed_unit_path.unlink()

        _run(self.ctx.systemctl_base, ["daemon-reload"])

        # Script cleanup is part of "remove".
        if installed_script_path.exists():
            installed_script_path.unlink()


