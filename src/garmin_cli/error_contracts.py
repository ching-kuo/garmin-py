"""Stable machine-readable error categories and recovery guidance."""
from __future__ import annotations

ERROR_CODE_TABLE: dict[str, dict[str, str]] = {
    "AUTH_MISSING": {
        "category": "authentication",
        "recovery_hint": "Authenticate with garmin-cli login and retry.",
    },
    "AUTH_FAILED": {
        "category": "authentication",
        "recovery_hint": "Reconnect the Garmin account and retry.",
    },
    "MFA_REQUIRED": {
        "category": "authentication",
        "recovery_hint": (
            "Complete the pending challenge with submit_mfa_code (MCP), or run "
            "garmin-cli login in a terminal to enter the code (CLI); --mfa-code only "
            "works for a code valid for a new challenge, such as an authenticator app's."
        ),
    },
    "INVALID_INPUT": {
        "category": "validation",
        "recovery_hint": "Correct the request and retry.",
    },
    "NOT_FOUND": {
        "category": "not_found",
        "recovery_hint": "Confirm the identifier and retry if the resource still exists.",
    },
    "RATE_LIMITED": {
        "category": "rate_limit",
        "recovery_hint": "Wait before retrying; do not retry immediately.",
    },
    "NETWORK_ERROR": {
        "category": "network",
        "recovery_hint": (
            "Check connectivity; a read may be retried once. A failed write may still "
            "have been applied: verify the remote state before repeating any write."
        ),
    },
    "SERVER_ERROR": {
        "category": "upstream",
        "recovery_hint": (
            "Retry later. If the problem persists, check Garmin service status. A failed "
            "write may still have been applied: verify the remote state before repeating a write."
        ),
    },
    "INTERRUPTED": {
        "category": "client",
        "recovery_hint": "The command was interrupted (Ctrl-C or end of input); run it again when ready.",
    },
    "INTERNAL_ERROR": {
        "category": "internal",
        "recovery_hint": "Retry once, then report the failure if it persists.",
    },
}

_UNKNOWN_ERROR_CONTRACT: dict[str, str] = {
    "category": "upstream",
    "recovery_hint": "Retry later. If the problem persists, check Garmin service status.",
}


def error_contract(error_code: str) -> dict[str, str]:
    """Return a copy of the contract for ``error_code``."""
    return dict(ERROR_CODE_TABLE.get(error_code, _UNKNOWN_ERROR_CONTRACT))
