# Oliver — AI Shopping Agent (Razorpay Buildathon)

A conversational shopping agent for "TeeStore" — chat with it to search products, create orders, and complete payments via Razorpay test-mode APIs. Every money-affecting action is guardrail-checked and logged to a full audit trail.

Built for the Razorpay AI Buildathon — AI Growth & Agentic Commerce track.

## Setup
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt


Create a `.env` file:
RAZORPAY_KEY_ID=your_test_key_id
RAZORPAY_KEY_SECRET=your_test_key_secret
GROQ_API_KEY=your_groq_key
MAX_ORDER_VALUE_INR=5000
MAX_ORDERS_PER_SESSION=3


Run:
cd backend
uvicorn main:app --reload


Chat with it:

POST http://127.0.0.1:8000/chat
{"message": "Show me black t-shirts under 700 rupees"}

View the audit trail:

GET http://127.0.0.1:8000/logs