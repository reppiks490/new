from __future__ import annotations

from pydantic import BaseModel, Field


class GateCheck(BaseModel):
    name: str
    passed: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProductionGateReport(BaseModel):
    passed: bool
    check_count: int
    failed_checks: list[str]
    blockers: list[str]
    warnings: list[str]
    checks: list[GateCheck]


def compile_production_gate(checks: list[GateCheck]) -> ProductionGateReport:
    """Aggregate independent QA domains without hiding the failure source.

    A production release passes only when every submitted check passes. Warnings do
    not block release, but remain attached to the aggregate report.
    """
    failed = [c.name for c in checks if not c.passed]
    blockers: list[str] = []
    warnings: list[str] = []
    for c in checks:
        blockers.extend(f"{c.name}: {x}" for x in c.blockers)
        warnings.extend(f"{c.name}: {x}" for x in c.warnings)
    return ProductionGateReport(
        passed=not failed,
        check_count=len(checks),
        failed_checks=failed,
        blockers=blockers,
        warnings=warnings,
        checks=checks,
    )
