from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Final


class ToolValidationError(ValueError):
    """Raised when a remediation tool request is not safe to execute."""


class ToolExecutionError(RuntimeError):
    """Raised when an allowlisted tool cannot complete successfully."""


@dataclass(frozen=True)
class ToolResult:
    output: str


class RemediationTool(ABC):
    name: Final[str]
    risk: Final[str]
    auto_allowed: Final[bool]

    @abstractmethod
    def validate(self, arguments: dict[str, str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def execute(self, arguments: dict[str, str], timeout_seconds: float) -> ToolResult:
        raise NotImplementedError


def _run_fixed_command(
    command: list[str], timeout_seconds: float, success_codes: set[int] | None = None
) -> ToolResult:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Command timed out: {command[0]}") from exc
    except OSError as exc:
        raise ToolExecutionError(f"Unable to execute {command[0]}: {exc}") from exc
    accepted = success_codes or {0}
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode not in accepted:
        raise ToolExecutionError(
            f"{command[0]} exited with code {completed.returncode}: {output[:500]}"
        )
    return ToolResult(output=output)


class CheckDiskUtilizationTool(RemediationTool):
    name = "check_disk_utilization"
    risk = "low"
    auto_allowed = True

    def validate(self, arguments: dict[str, str]) -> None:
        if set(arguments) - {"path"}:
            raise ToolValidationError("Only the path argument is supported")
        path = arguments.get("path", "/")
        if not path.startswith("/"):
            raise ToolValidationError("path must be an absolute Linux path")

    def execute(self, arguments: dict[str, str], timeout_seconds: float) -> ToolResult:
        self.validate(arguments)
        return _run_fixed_command(["df", "-P", arguments.get("path", "/")], timeout_seconds)


class CheckServiceHealthTool(RemediationTool):
    name = "check_service_health"
    risk = "low"
    auto_allowed = True

    def validate(self, arguments: dict[str, str]) -> None:
        service = arguments.get("service", "")
        if set(arguments) != {"service"} or not service or not _valid_service_name(service):
            raise ToolValidationError("service must be a safe systemd unit name")

    def execute(self, arguments: dict[str, str], timeout_seconds: float) -> ToolResult:
        self.validate(arguments)
        return _run_fixed_command(
            ["systemctl", "is-active", arguments["service"]],
            timeout_seconds,
            success_codes={0, 3},
        )


class InspectServiceLogsTool(RemediationTool):
    name = "inspect_service_logs"
    risk = "low"
    auto_allowed = True

    def validate(self, arguments: dict[str, str]) -> None:
        service = arguments.get("service", "")
        if set(arguments) - {"service", "lines"} or not service or not _valid_service_name(service):
            raise ToolValidationError("service must be a safe systemd unit name")
        try:
            lines = int(arguments.get("lines", "50"))
        except ValueError as exc:
            raise ToolValidationError("lines must be an integer") from exc
        if not 1 <= lines <= 200:
            raise ToolValidationError("lines must be between 1 and 200")

    def execute(self, arguments: dict[str, str], timeout_seconds: float) -> ToolResult:
        self.validate(arguments)
        return _run_fixed_command(
            ["journalctl", "-u", arguments["service"], "-n", arguments.get("lines", "50"), "--no-pager"],
            timeout_seconds,
            success_codes={0, 1},
        )


class InspectProcessResourceTool(RemediationTool):
    name = "inspect_process_resource_consumption"
    risk = "low"
    auto_allowed = True

    def validate(self, arguments: dict[str, str]) -> None:
        if arguments:
            raise ToolValidationError("This tool does not accept arguments")

    def execute(self, arguments: dict[str, str], timeout_seconds: float) -> ToolResult:
        self.validate(arguments)
        return _run_fixed_command(["ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-%cpu"], timeout_seconds)


class RestartServiceTool(RemediationTool):
    name = "restart_authorized_service"
    risk = "high"
    auto_allowed = False

    def __init__(self, authorized_services: set[str]) -> None:
        self.authorized_services = frozenset(authorized_services)

    def validate(self, arguments: dict[str, str]) -> None:
        service = arguments.get("service", "")
        if set(arguments) != {"service"} or service not in self.authorized_services:
            raise ToolValidationError("service is not in the authorized restart list")
        if not _valid_service_name(service):
            raise ToolValidationError("service must be a safe systemd unit name")

    def execute(self, arguments: dict[str, str], timeout_seconds: float) -> ToolResult:
        self.validate(arguments)
        return _run_fixed_command(["systemctl", "restart", arguments["service"]], timeout_seconds)


def _valid_service_name(service: str) -> bool:
    return (
        len(service) <= 128
        and service.endswith((".service", ".socket", ".target"))
        and all(character.isalnum() or character in "._@-" for character in service)
    )

