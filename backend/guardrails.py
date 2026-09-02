"""
Guardrails: the "bounded and gated" part of the track's bar.
Every money-moving action must pass through here BEFORE it executes.
"""
from config import MAX_ORDER_VALUE_INR, MAX_ORDERS_PER_SESSION


class GuardrailViolation(Exception):
    """Raised when a proposed action would break a spending/behavior bound."""
    pass


def check_order_value(total_amount: float):
    if total_amount > MAX_ORDER_VALUE_INR:
        raise GuardrailViolation(
            f"Order value ₹{total_amount} exceeds the allowed limit of ₹{MAX_ORDER_VALUE_INR}."
        )


def check_session_order_count(orders_this_session: int):
    if orders_this_session >= MAX_ORDERS_PER_SESSION:
        raise GuardrailViolation(
            f"Session has already placed {orders_this_session} orders "
            f"(limit is {MAX_ORDERS_PER_SESSION}). Blocking further purchases."
        )


def check_stock(product: dict, requested_qty: int):
    if product["stock"] < requested_qty:
        raise GuardrailViolation(
            f"Requested quantity ({requested_qty}) exceeds available stock "
            f"({product['stock']}) for '{product['name']}'."
        )


def check_explicit_confirmation(user_confirmed: bool):
    """
    Never let the agent charge a card without an explicit 'yes' from the user.
    This is the 'gated' requirement -- payment cannot fire silently.
    """
    if not user_confirmed:
        raise GuardrailViolation(
            "Payment blocked: no explicit user confirmation was received before charging."
        )