from enum import StrEnum

from pydantic import BaseModel


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PolicyDecision(BaseModel):
    allowed: bool
    risk_level: RiskLevel
    reason: str


DECISION_GATES: dict[str, RiskLevel] = {
    "security": RiskLevel.HIGH,
    "auth": RiskLevel.HIGH,
    "database_schema": RiskLevel.HIGH,
    "api_contract": RiskLevel.MEDIUM,
    "performance": RiskLevel.MEDIUM,
    "logging": RiskLevel.LOW,
    "ui": RiskLevel.LOW,
}

_HIGH_RISK_PATCH_PATTERNS = [
    "DROP TABLE",
    "DELETE FROM",
    "TRUNCATE",
    "rm -rf",
    "os.remove",
    "shutil.rmtree",
    "subprocess.call",
    "eval(",
    "exec(",
]


def check_decision_gate(decision: dict) -> PolicyDecision:
    """Return a PolicyDecision for a single decision dict.

    Decisions in HIGH-risk categories require human approval (allowed=False).
    All others are auto-allowed.
    """
    category = (decision.get("category") or "").lower()
    risk = DECISION_GATES.get(category, RiskLevel.LOW)
    if risk == RiskLevel.HIGH:
        return PolicyDecision(
            allowed=False,
            risk_level=risk,
            reason=f"Category '{category}' requires human approval (HIGH risk).",
        )
    return PolicyDecision(allowed=True, risk_level=risk, reason="Auto-approved.")


def check_patch_risk(diff_text: str) -> PolicyDecision:
    """Scan a patch diff for high-risk patterns.

    Returns allowed=False if any dangerous pattern is found.
    """
    for pattern in _HIGH_RISK_PATCH_PATTERNS:
        if pattern in diff_text:
            return PolicyDecision(
                allowed=False,
                risk_level=RiskLevel.HIGH,
                reason=f"Patch contains high-risk pattern: '{pattern}'.",
            )
    return PolicyDecision(allowed=True, risk_level=RiskLevel.LOW, reason="No high-risk patterns found.")
