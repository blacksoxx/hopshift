"""Result types shared by the target and source conformance checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

Status = Literal["pass", "fail", "skip"]

_STATUS_LABEL = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}


class SkipCheck(Exception):
    """Raised inside a check to record it as skipped with the given note."""


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    message: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "message": self.message}


@dataclass
class ConformanceReport:
    """Ordered list of checks for one target or source."""

    kind: str                     # "target" | "source"
    subject: str                  # registry name
    label: str = ""
    checks: list[CheckResult] = field(default_factory=list)

    # ── recording ─────────────────────────────────────────────────────────

    def add(self, name: str, status: Status, message: str = "") -> CheckResult:
        result = CheckResult(name=name, status=status, message=_one_line(message))
        self.checks.append(result)
        return result

    def add_pass(self, name: str, message: str = "") -> CheckResult:
        return self.add(name, "pass", message)

    def add_fail(self, name: str, message: str) -> CheckResult:
        return self.add(name, "fail", message)

    def add_skip(self, name: str, message: str) -> CheckResult:
        return self.add(name, "skip", message)

    def run(self, name: str, check: Callable[[], str | None]) -> CheckResult:
        """Run `check`; its return value is the pass message.

        SkipCheck records a skip; any other exception (AssertionError included) records a
        readable failure instead of propagating, so a broken plugin yields a report, not a
        traceback.
        """
        try:
            message = check()
        except SkipCheck as exc:
            return self.add_skip(name, str(exc))
        except AssertionError as exc:
            # first line only: pytest's assertion rewriting appends the expression when a check
            # module happens to be rewritten, and the explanatory message is what the reader needs
            first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
            return self.add_fail(name, first_line or "assertion failed")
        except Exception as exc:  # noqa: BLE001
            return self.add_fail(name, f"{type(exc).__name__}: {exc}")
        return self.add_pass(name, message or "")

    # ── reading ───────────────────────────────────────────────────────────

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def failures(self) -> list[CheckResult]:
        return [item for item in self.checks if item.status == "fail"]

    @property
    def skipped(self) -> list[CheckResult]:
        return [item for item in self.checks if item.status == "skip"]

    @property
    def passes(self) -> list[CheckResult]:
        return [item for item in self.checks if item.status == "pass"]

    def get(self, name: str) -> CheckResult | None:
        return next((item for item in self.checks if item.name == name), None)

    def names(self, status: Status | None = None) -> list[str]:
        return [item.name for item in self.checks if status is None or item.status == status]

    def summary(self) -> str:
        return f"{len(self.passes)} passed, {len(self.failures)} failed, {len(self.skipped)} skipped"

    def render(self) -> str:
        """Plain-text report: a title line with the summary, then one line per check."""
        title = f"{self.kind} conformance: {self.subject}"
        if self.label:
            title += f" ({self.label})"
        lines = [f"{title} - {self.summary()}"]
        width = max((len(item.name) for item in self.checks), default=0)
        for item in self.checks:
            line = f"  {_STATUS_LABEL[item.status]}  {item.name.ljust(width)}"
            if item.message:
                line += f"  {item.message}"
            lines.append(line.rstrip())
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "label": self.label,
            "passed": self.passed,
            "summary": {"passed": len(self.passes), "failed": len(self.failures), "skipped": len(self.skipped)},
            "checks": [item.to_dict() for item in self.checks],
        }


def _one_line(text: str, limit: int = 600) -> str:
    collapsed = " ".join(str(text).split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 3] + "..."
