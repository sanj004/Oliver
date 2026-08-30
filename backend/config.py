"""
Central config for the AI shopping agent.
Loads secrets from environment variables (.env file) and defines
guardrail constants used across the app.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Razorpay test-mode credentials ---
# Get these from https://dashboard.razorpay.com/app/keys (Test Mode toggle ON)
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")

# --- LLM provider credentials ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# --- Guardrails (the "bounded" part of the bar) ---
MAX_ORDER_VALUE_INR = int(os.getenv("MAX_ORDER_VALUE_INR", "5000"))
MAX_ORDERS_PER_SESSION = int(os.getenv("MAX_ORDERS_PER_SESSION", "3"))

# --- File-based "database" paths ---
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
PRODUCTS_FILE = os.path.join(DATA_DIR, "products.json")
ORDERS_FILE = os.path.join(DATA_DIR, "orders.json")
LOGS_FILE = os.path.join(DATA_DIR, "logs.json")