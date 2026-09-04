"""
Razorpay test-mode integration.
All amounts are in paise (Razorpay's smallest currency unit) internally,
per their API convention -- we convert from rupees at the boundary.

Setup:
1. Sign up at https://dashboard.razorpay.com/
2. Toggle "Test Mode" ON (top right of dashboard)
3. Go to Settings -> API Keys -> Generate Test Key
4. Put RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in your .env file
"""
import razorpay
from config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET

_client = None


def get_client():
    global _client
    if _client is None:
        if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
            raise RuntimeError(
                "Razorpay keys not configured. Add RAZORPAY_KEY_ID and "
                "RAZORPAY_KEY_SECRET to your .env file (test mode keys)."
            )
        _client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    return _client


def create_razorpay_order(amount_inr: float, receipt: str):
    """
    Creates an order on Razorpay in test mode.
    amount_inr is in rupees; Razorpay wants paise (multiply by 100).

    TEMPORARY MOCK MODE: if Razorpay keys aren't configured yet (e.g. KYC
    pending), we simulate a successful order response instead of calling
    the real API. This lets the rest of the agent (guardrails, audit,
    upsell, etc.) be built and demoed without being blocked. Swap this
    out once real Razorpay test keys are available.
    """
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        import uuid
        mock_order_id = f"mock_order_{uuid.uuid4().hex[:10]}"
        return {
            "id": mock_order_id,
            "amount": int(amount_inr * 100),
            "currency": "INR",
            "receipt": receipt,
            "status": "created",
            "mocked": True,
        }

    client = get_client()
    order = client.order.create({
        "amount": int(amount_inr * 100),
        "currency": "INR",
        "receipt": receipt,
        "payment_capture": 1,
    })
    return order


def verify_payment_signature(razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str) -> bool:
    """
    Verifies the payment signature returned by Razorpay's checkout flow.
    """
    client = get_client()
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        })
        return True
    except razorpay.errors.SignatureVerificationError:
        return False


def fetch_payment_status(payment_id: str):
    client = get_client()
    return client.payment.fetch(payment_id)