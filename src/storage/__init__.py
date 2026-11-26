"""Storage package export."""

from src.storage.state_diff_engine import (
    AuditDiffLogger,
    StateIsolationError,
    capture_state,
    compute_diff,
    compute_sha256,
    get_audit_logger,
    validate_state_isolation,
)

__all__ = [
    "StateIsolationError",
    "capture_state",
    "compute_diff",
    "compute_sha256",
    "validate_state_isolation",
    "AuditDiffLogger",
    "get_audit_logger",
    "TicketStore",
    "get_ticket_store",
    "ProductStore",
    "get_product_store",
]


def __getattr__(name: str):
    if name in ("ProductStore", "get_product_store"):
        from src.storage.product_store import ProductStore, get_product_store
        return {"ProductStore": ProductStore, "get_product_store": get_product_store}[name]
    if name in ("TicketStore", "get_ticket_store"):
        from src.storage.ticket_store import TicketStore, get_ticket_store
        return {"TicketStore": TicketStore, "get_ticket_store": get_ticket_store}[name]
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
