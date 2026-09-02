"""
Simple file-based order storage. Swap for a real DB if you have time,
but this is plenty for a hackathon demo.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from config import ORDERS_FILE


def create_order_record(product: dict, quantity: int, session_id: str, razorpay_order_id: str = None):
    order = {
        "order_id": str(uuid.uuid4())[:8],
        "session_id": session_id,
        "product_id": product["id"],
        "product_name": product["name"],
        "quantity": quantity,
        "unit_price": product["price"],
        "total_amount": product["price"] * quantity,
        "status": "created",
        "razorpay_order_id": razorpay_order_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    orders = _read_orders()
    orders.append(order)
    _write_orders(orders)
    return order


def mark_order_paid(order_id: str, razorpay_payment_id: str):
    orders = _read_orders()
    for o in orders:
        if o["order_id"] == order_id:
            o["status"] = "paid"
            o["razorpay_payment_id"] = razorpay_payment_id
    _write_orders(orders)


def get_orders_for_session(session_id: str):
    return [o for o in _read_orders() if o["session_id"] == session_id]


def _read_orders():
    if not os.path.exists(ORDERS_FILE):
        return []
    with open(ORDERS_FILE, "r") as f:
        return json.load(f)


def _write_orders(orders):
    with open(ORDERS_FILE, "w") as f:
        json.dump(orders, f, indent=2)