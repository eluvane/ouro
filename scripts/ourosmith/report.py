"""Findings and the deterministic run report.

A finding records everything needed to reproduce and classify a problem: the
seed, profile, generator hash, minimal input, expected and actual properties,
failing phase, resource classification, and the exact replay command.  The
report separates timing (host dependent) from the deterministic body so two
runs of the same seeds can be compared by fingerprint.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional, TYPE_CHECKING

from repo_support import write_json_atomic

if TYPE_CHECKING:
    from pathlib import Path

REPORT_KIND = "ouro.smith-report.v1"

CLASSIFICATIONS = (
    "crash",
    "timeout",
    "memory",
    "wrong-accept",
    "wrong-reject",
    "wrong-class",
    "divergence",
    "property-violation",
    "oracle-unavailable",
    "generator-error",
)


@dataclass
class Finding:
    layer: str
    prop: str
    classification: str
    seed: int
    profile: str
    generator_hash: str
    case_id: str
    failing_phase: str
    expected: Any
    actual: Any
    minimal_input: Any
    replay: str
    original_size: int = 0
    shrunk_size: int = 0
    resource: str = "ok"
    notes: list[str] = field(default_factory=list)

    @property
    def finding_id(self) -> str:
        body = json.dumps(
            [self.layer, self.prop, self.classification, self.seed, self.case_id, self.failing_phase],
            sort_keys=True,
        )
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["id"] = self.finding_id
        return data


@dataclass
class LayerSummary:
    layer: str
    cases: int = 0
    positive_checks: int = 0
    negative_checks: int = 0
    property_checks: int = 0
    abstentions: dict[str, int] = field(default_factory=dict)
    findings: int = 0
    coverage: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def abstain(self, reason: str, count: int = 1) -> None:
        self.abstentions[reason] = self.abstentions.get(reason, 0) + count


class Report:
    def __init__(self, *, profile: str, generator_hash: str, seeds: list[int], command: str) -> None:
        self.profile = profile
        self.generator_hash = generator_hash
        self.seeds = seeds
        self.command = command
        self.findings: list[Finding] = []
        self.layers: dict[str, LayerSummary] = {}
        self.gaps: list[dict[str, Any]] = []
        self.sections: dict[str, Any] = {}
        self.timing: dict[str, float] = {}
        self.skips: list[dict[str, Any]] = []

    def layer(self, name: str) -> LayerSummary:
        if name not in self.layers:
            self.layers[name] = LayerSummary(layer=name)
        return self.layers[name]

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)
        self.layer(finding.layer).findings += 1

    def gap(self, layer: str, what: str, why: str, *, blocking: bool = False) -> None:
        """Record missing coverage.  Blocking gaps (completeness violations) fail the run;
        informational gaps only document what a profile did not reach."""
        self.gaps.append({"layer": layer, "what": what, "why": why, "blocking": blocking})

    def skip(self, what: str, why: str) -> None:
        """Record a check that could not run.  A skip is never a pass."""
        self.skips.append({"what": what, "why": why})

    @property
    def blocking_gaps(self) -> list[dict[str, Any]]:
        return [g for g in self.gaps if g.get("blocking")]

    @property
    def passed(self) -> bool:
        return (
            bool(self.layers)
            and sum(layer.cases for layer in self.layers.values()) > 0
            and not any(layer.abstentions for layer in self.layers.values())
            and not self.findings
            and not self.skips
            and not self.blocking_gaps
        )

    def body(self) -> dict[str, Any]:
        return {
            "kind": REPORT_KIND,
            "pass": self.passed,
            "profile": self.profile,
            "generator_hash": self.generator_hash,
            "seeds": self.seeds,
            "command": self.command,
            "summary": {
                "findings": len(self.findings),
                "skips": len(self.skips),
                "gaps": len(self.gaps),
                "layers": {name: asdict(summary) for name, summary in sorted(self.layers.items())},
            },
            "findings": sorted((f.to_json() for f in self.findings), key=lambda f: (f["layer"], f["prop"], f["id"])),
            "skips": self.skips,
            "gaps": sorted(self.gaps, key=lambda g: (g["layer"], g["what"])),
            "sections": self.sections,
        }

    def fingerprint(self) -> str:
        text = json.dumps(self.body(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def write(self, path: Path) -> dict[str, Any]:
        data = self.body()
        data["fingerprint"] = self.fingerprint()
        data["timing_s"] = {k: round(v, 3) for k, v in sorted(self.timing.items())}
        write_json_atomic(path, data)
        return data


def summarize_line(report: Report, *, prefix: str = "OURO_SMITH") -> str:
    layers = " ".join(
        f"{name}={summary.cases}/{summary.findings}" for name, summary in sorted(report.layers.items())
    )
    status = "PASS" if report.passed else "FAIL"
    return f"{prefix}: {status} findings={len(report.findings)} skips={len(report.skips)} gaps={len(report.gaps)} {layers}".rstrip()


def finding_size(value: Any) -> int:
    """Size metric shared by the shrinker and the report: serialized JSON length."""
    if isinstance(value, str):
        return len(value)
    return len(json.dumps(value, sort_keys=True, separators=(",", ":")))


def load_report(path: Path) -> Optional[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("kind") != REPORT_KIND:
        return None
    return data
