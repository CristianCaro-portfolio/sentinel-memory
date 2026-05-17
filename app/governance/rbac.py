"""Simulated RBAC.

The analyst's role lives in the LTM table (key ``"role"``). Each HTTP
request must carry the ``X-Analyst-Id`` header; a FastAPI dependency
looks up the role and either lets the call through or returns 403.

For a portfolio project this is intentionally simple — no JWT, no IdP.
In production you'd swap ``get_role`` for a token-validation step and
the rest of the design stays the same.
"""
from fastapi import Header, HTTPException

from app.memory import ltm

# Permissions allowed per role.
ROLE_PERMS: dict[str, set[str]] = {
    "auditor": {"read_audit"},
    "analyst": {
        "chat",
        "search",
        "patch_alert",
        "create_alert",
        "submit_feedback",
    },
    "senior_analyst": {
        "chat",
        "search",
        "patch_alert",
        "create_alert",
        "submit_feedback",
        "read_audit",
    },
}


def get_role(analyst_id: str) -> str:
    prefs = ltm.get_ltm(analyst_id) or {}
    return prefs.get("role", "analyst")


def require_permission(perm: str):
    def dep(x_analyst_id: str = Header(..., alias="X-Analyst-Id")) -> dict:
        role = get_role(x_analyst_id)
        if perm not in ROLE_PERMS.get(role, set()):
            raise HTTPException(
                status_code=403,
                detail=f"role '{role}' lacks permission '{perm}'",
            )
        return {"analyst_id": x_analyst_id, "role": role}

    return dep
