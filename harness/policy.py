from enum import StrEnum

from pydantic import BaseModel


class RiskLevel(StrEnum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class PolicyDecision(BaseModel):
    requires_human: bool
    risk_level:     RiskLevel
    reason:         str


DECISION_GATES: frozenset[str] = frozenset({
    "security_permission",
    "migration_compatibility",
    "architecture_pattern",
    "persistence_transaction",
})


def check_decision_gate(category: str) -> PolicyDecision:
    if category in DECISION_GATES:
        return PolicyDecision(
            requires_human=True,
            risk_level=RiskLevel.HIGH,
            reason=f"'{category}' requires human sign-off",
        )
    return PolicyDecision(
        requires_human=False,
        risk_level=RiskLevel.LOW,
        reason="auto-approvable",
    )


def check_patch_risk(patch_content: str, contract: dict) -> RiskLevel:
    HIGH_SIGNALS = ("DROP TABLE", "DELETE FROM", "exec(", "eval(", "subprocess", "os.system")
    for sig in HIGH_SIGNALS:
        if sig in patch_content:
            return RiskLevel.CRITICAL
    return RiskLevel.LOW
