from __future__ import annotations

import os
import logging
import re
import shutil
import subprocess
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_PATH_PLACEHOLDER = "__SCRIPT_PATH__"


class ElevationRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    unit_name: str
    action: str
    message: str
    error: str | None = None
    script_dest: str | None = None
    unit_dest: str | None = None
    expected_enabled: bool | None = None
    actual_enabled: str | None = None


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


def _default_log_path() -> Path:
    """
    Prefer a user-writable location.
    """
    home = Path("~").expanduser()
    state_dir = home / ".local" / "state" / "my-service-mgr"
    log_dir = state_dir / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / "my-service-mgr.log"
    except Exception:
        # Last resort: keep logs in the current working directory.
        return Path.cwd() / "my-service-mgr.log"


def _detect_systemd_context(mode: str, dry_run: bool) -> SystemdContext:
    """
    mode:
      - "auto": root -> system units, non-root -> user units
      - "system": force system units (requires root unless dry-run)
      - "user": force user units
    """
    is_root = os.geteuid() == 0

    # Root/system: system units.
    if mode == "auto":
        if is_root:
            return SystemdContext(
                unit_dir=Path("/etc/systemd/system"),
                bin_dir=Path("/usr/local/bin"),
                systemctl_base=["systemctl"],
            )

        return SystemdContext(
            unit_dir=Path("~/.config/systemd/user").expanduser(),
            bin_dir=Path("~/.local/bin").expanduser(),
            systemctl_base=["systemctl", "--user"],
        )

    if mode == "system":
        if not is_root and not dry_run:
            raise ElevationRequired("Systemd system units require root. Re-run with `sudo` or use `--mode user`.")
        return SystemdContext(
            unit_dir=Path("/etc/systemd/system"),
            bin_dir=Path("/usr/local/bin"),
            systemctl_base=["systemctl"],
        )

    if mode == "user":
        return SystemdContext(
            unit_dir=Path("~/.config/systemd/user").expanduser(),
            bin_dir=Path("~/.local/bin").expanduser(),
            systemctl_base=["systemctl", "--user"],
        )

    raise ValueError(f"Unknown mode: {mode!r} (expected auto/system/user)")


def _run(
    systemctl_base: list[str],
    args: list[str],
    *,
    logger: logging.Logger,
    unit_name: str | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = systemctl_base + args
    start = time.time()
    proc = subprocess.run(cmd, check=False, text=True, capture_output=True)
    elapsed_ms = int((time.time() - start) * 1000)

    prefix = f"[{unit_name}] " if unit_name else ""
    if proc.returncode == 0:
        logger.info("%scommand ok: %s (elapsed=%sms)", prefix, " ".join(cmd), elapsed_ms)
    else:
        logger.error(
            "%scommand failed rc=%s: %s\nstdout:\n%s\nstderr:\n%s",
            prefix,
            proc.returncode,
            " ".join(cmd),
            (proc.stdout or "").strip(),
            (proc.stderr or "").strip(),
        )
    return proc


class ServiceManager:
    def __init__(
        self,
        services_dir: Path,
        scripts_dir: Path,
        *,
        mode: str = "auto",
        dry_run: bool = False,
    ) -> None:
        self.services_dir = services_dir
        self.scripts_dir = scripts_dir
        self.dry_run = dry_run
        self.ctx = _detect_systemd_context(mode=mode, dry_run=dry_run)

        self.log_path = _default_log_path()
        self.logger = logging.getLogger("my_service_mgr")
        self.logger.setLevel(logging.INFO)

        # Avoid duplicate handlers if the manager gets constructed multiple times.
        if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "").endswith(str(self.log_path)) for h in self.logger.handlers):
            fh = logging.FileHandler(self.log_path, encoding="utf-8")
            fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            fh.setFormatter(fmt)
            self.logger.addHandler(fh)

        if not self.services_dir.exists():
            raise FileNotFoundError(f"Services directory does not exist: {self.services_dir}")
        if not self.scripts_dir.exists():
            raise FileNotFoundError(f"Scripts directory does not exist: {self.scripts_dir}")

        self.logger.info(
            "Initialized manager mode=%s dry_run=%s systemd_unit_dir=%s bin_dir=%s log=%s",
            mode,
            dry_run,
            str(self.ctx.unit_dir),
            str(self.ctx.bin_dir),
            str(self.log_path),
        )

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

        enabled_proc = _run(
            self.ctx.systemctl_base,
            ["is-enabled", unit_name],
            logger=self.logger,
            unit_name=unit_name,
        )
        enabled_out = (enabled_proc.stdout or "").strip()
        enabled = "unknown"
        if enabled_out == "enabled":
            enabled = "enabled"
        elif enabled_out in {"disabled", "static"}:
            enabled = enabled_out

        active_proc = _run(
            self.ctx.systemctl_base,
            ["is-active", unit_name],
            logger=self.logger,
            unit_name=unit_name,
        )
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

    def enable_by_unit_name(self, unit_name: str) -> ActionResult:
        template = self._get_template(unit_name)
        return self._install(template)

    def disable_by_unit_name(self, unit_name: str) -> ActionResult:
        template = self._get_template(unit_name)
        return self._uninstall(template)

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

    def _install(self, template: ServiceTemplate) -> ActionResult:
        action = "enable"
        unit_name = template.unit_name
        installed_script_path = template.installed_script_path()
        installed_unit_path = template.installed_unit_path()

        if self.dry_run:
            log_hint = self.log_path.name
            msg = (
                f"[dry-run] Would install script to {installed_script_path} and unit to {installed_unit_path} "
                f"then run: {' '.join(self.ctx.systemctl_base)} enable --now {unit_name} (log: {log_hint})"
            )
            self.logger.info("%s", msg)
            return ActionResult(
                ok=True,
                unit_name=unit_name,
                action=action,
                message=msg,
                script_dest=str(installed_script_path),
                unit_dest=str(installed_unit_path),
                expected_enabled=True,
                actual_enabled="unknown",
            )

        script_dest = str(installed_script_path)
        unit_dest = str(installed_unit_path)
        self.logger.info("[%s] install paths script=%s unit=%s", unit_name, script_dest, unit_dest)

        try:
            installed_script_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(template.resolve_script_template_path(), installed_script_path)
            installed_script_path.chmod(0o755)

            self.ctx.unit_dir.mkdir(parents=True, exist_ok=True)
            rendered = template.render_unit_text(installed_script_path=installed_script_path)
            installed_unit_path.write_text(rendered, encoding="utf-8")

            _run(self.ctx.systemctl_base, ["daemon-reload"], logger=self.logger, unit_name=unit_name)
            enable_proc = _run(
                self.ctx.systemctl_base,
                ["enable", "--now", unit_name],
                logger=self.logger,
                unit_name=unit_name,
            )
            if enable_proc.returncode != 0:
                err = (enable_proc.stderr or "").strip() or (enable_proc.stdout or "").strip() or "unknown error"
                return ActionResult(
                    ok=False,
                    unit_name=unit_name,
                    action=action,
                    message=(
                        f"Error: Failed to enable/start {unit_name} "
                        f"(script: {script_dest}, unit: {unit_dest}, log: {self.log_path.name})"
                    ),
                    error=err,
                    script_dest=script_dest,
                    unit_dest=unit_dest,
                    expected_enabled=True,
                    actual_enabled=None,
                )

            _, enabled, _ = self._installed_state(unit_name)
            if enabled != "enabled":
                return ActionResult(
                    ok=False,
                    unit_name=unit_name,
                    action=action,
                    message=(
                        f"Error: {unit_name} enabled check failed (expected enabled, got {enabled}) "
                        f"(script: {script_dest}, unit: {unit_dest}, log: {self.log_path.name})"
                    ),
                    error=f"systemctl is-enabled returned: {enabled}",
                    script_dest=script_dest,
                    unit_dest=unit_dest,
                    expected_enabled=True,
                    actual_enabled=enabled,
                )

            msg = (
                f"Enabled {unit_name}. Copied script to {script_dest} and unit to {unit_dest}. (log: {self.log_path.name})"
            )
            self.logger.info("%s", msg)
            return ActionResult(
                ok=True,
                unit_name=unit_name,
                action=action,
                message=msg,
                script_dest=script_dest,
                unit_dest=unit_dest,
                expected_enabled=True,
                actual_enabled=enabled,
            )
        except ElevationRequired:
            raise
        except Exception as e:
            self.logger.error("install failed for %s: %s", unit_name, str(e))
            self.logger.exception("install exception for %s", unit_name)
            return ActionResult(
                ok=False,
                unit_name=unit_name,
                action=action,
                message=(
                    f"Error: Exception while enabling {unit_name} "
                    f"(script: {script_dest}, unit: {unit_dest}, log: {self.log_path.name})"
                ),
                error=str(e),
                script_dest=script_dest,
                unit_dest=unit_dest,
                expected_enabled=True,
            )

    def _uninstall(self, template: ServiceTemplate) -> ActionResult:
        action = "disable"
        unit_name = template.unit_name
        installed_script_path = template.installed_script_path()
        installed_unit_path = template.installed_unit_path()

        if self.dry_run:
            log_hint = self.log_path.name
            msg = (
                f"[dry-run] Would disable/remove unit {installed_unit_path} "
                f"and run: {' '.join(self.ctx.systemctl_base)} disable --now {unit_name} "
                f"then remove script {installed_script_path} (log: {log_hint})"
            )
            self.logger.info("%s", msg)
            return ActionResult(
                ok=True,
                unit_name=unit_name,
                action=action,
                message=msg,
                script_dest=str(installed_script_path),
                unit_dest=str(installed_unit_path),
                expected_enabled=False,
                actual_enabled="unknown",
            )

        script_dest = str(installed_script_path)
        unit_dest = str(installed_unit_path)
        self.logger.info("[%s] uninstall paths script=%s unit=%s", unit_name, script_dest, unit_dest)

        try:
            # Best-effort stop/disable (unit may not exist).
            _run(
                self.ctx.systemctl_base,
                ["disable", "--now", unit_name],
                logger=self.logger,
                unit_name=unit_name,
            )
            if installed_unit_path.exists():
                installed_unit_path.unlink()

            _run(self.ctx.systemctl_base, ["daemon-reload"], logger=self.logger, unit_name=unit_name)

            # Script cleanup is part of "remove".
            if installed_script_path.exists():
                installed_script_path.unlink()

            _, enabled, _ = self._installed_state(unit_name)
            if enabled == "enabled":
                return ActionResult(
                    ok=False,
                    unit_name=unit_name,
                    action=action,
                    message=(
                        f"Error: {unit_name} still appears enabled after disable "
                        f"(script: {script_dest}, unit: {unit_dest}, log: {self.log_path.name})"
                    ),
                    error=f"systemctl is-enabled returned: {enabled}",
                    script_dest=script_dest,
                    unit_dest=unit_dest,
                    expected_enabled=False,
                    actual_enabled=enabled,
                )

            msg = f"Disabled {unit_name}. Removed script {script_dest} and unit {unit_dest}. (log: {self.log_path.name})"
            self.logger.info("%s", msg)
            return ActionResult(
                ok=True,
                unit_name=unit_name,
                action=action,
                message=msg,
                script_dest=script_dest,
                unit_dest=unit_dest,
                expected_enabled=False,
                actual_enabled=enabled,
            )
        except Exception as e:
            self.logger.error("uninstall failed for %s: %s", unit_name, str(e))
            self.logger.exception("uninstall exception for %s", unit_name)
            return ActionResult(
                ok=False,
                unit_name=unit_name,
                action=action,
                message=(
                    f"Error: Exception while disabling {unit_name} "
                    f"(script: {script_dest}, unit: {unit_dest}, log: {self.log_path.name})"
                ),
                error=str(e),
                script_dest=str(installed_script_path),
                unit_dest=str(installed_unit_path),
                expected_enabled=False,
            )


