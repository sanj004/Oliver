"""
The agent brain.
Uses Groq (Llama 70B) with tool-calling: the LLM decides which function to call
(search products, create order, confirm payment) based on the
conversation, and we execute those functions server-side with
guardrails + audit logging wrapped around every money-affecting step.
"""
import os
from openai import OpenAI
import catalog
import orders as orders_db
import payments
import guardrails
import audit

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ["GROQ_API_KEY"],
)

MODEL_NAME = "openai/gpt-oss-120b"

SYSTEM_PROMPT = """You are a shopping assistant for TeeStore, a small clothing store.
You help customers find and buy products using the available tools.

CRITICAL: You must NEVER write out a tool call as text in your reply (e.g. never
write something like {"name": "confirm_payment", ...} in your message). If you need
to use a tool, you MUST invoke it properly through the tool-calling mechanism, not
explain it in words. If you're unsure whether to call a tool, call it -- do not
explain what you would do instead.

CRITICAL: When calling search_products, ONLY include parameters the user actually
mentioned. Do NOT invent, guess, or default a max_price, size, or color the user
never stated. Omit any parameter you're not sure about entirely -- an omitted
parameter means "no filter," which is safer than guessing wrong.

CRITICAL: When calling create_order, you MUST use the exact product_id value
returned by a prior search_products call. NEVER invent, guess, or construct a
product_id yourself (e.g. do not make up SKU-style IDs like "RGT-001"). If you
don't have a product_id from a real search result, call search_products again
first.

CRITICAL: Never state a price, product name, or availability that did not come
from an actual search_products or create_order tool result in this conversation.
Do not make up products or prices.

Rules you must always follow:
- Never call confirm_payment unless the user has explicitly said something
  affirmative like "yes", "confirm", "go ahead" AFTER you've shown them the
  final price.
- Always show the product name and price before asking for confirmation.
- If a product is out of stock or a size isn't available, say so clearly
  and suggest an alternative instead of failing silently.
- After a user adds an item, check if there's a complementary product
  worth suggesting (upsell) -- but only suggest once, don't be pushy about it.
- Keep responses short and conversational.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search the product catalog by keyword, max price, size, or color.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword to search for, e.g. 'tee', 'jacket'"},
                    "max_price": {"type": "number", "description": "Maximum price in INR"},
                    "size": {"type": "string", "description": "Size filter, e.g. 'M'"},
                    "color": {"type": "string", "description": "Color filter, e.g. 'black'"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pairing_suggestions",
            "description": "Get complementary products that pair well with a given product ID, for upsell suggestions.",
            "parameters": {
                "type": "object",
                "properties": {"product_id": {"type": "string"}},
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_order",
            "description": "Create an order for a product. This does NOT charge payment yet -- it just reserves the order and returns the total to confirm with the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string"},
                    "quantity": {"type": "integer"},
                },
                "required": ["product_id", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_payment",
            "description": "Charge payment for the customer's most recent pending order in this session. Only call this AFTER the user has explicitly confirmed they want to pay. Do NOT invent or guess an order_id -- this tool automatically finds the correct pending order.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_confirmed": {"type": "boolean", "description": "Must be true, based on an explicit user 'yes'"},
                },
                "required": ["user_confirmed"],
            },
        },
    },
]


def execute_tool(tool_name: str, tool_input: dict, session_id: str):
    """Runs the actual function behind a tool call, with guardrails + audit logging."""

    # Defensive: strip unexpected keys that don't belong to this tool,
    # since the model sometimes bleeds params from other tool schemas.
    EXPECTED_KEYS = {
        "search_products": {"query", "max_price", "size", "color"},
        "get_pairing_suggestions": {"product_id"},
        "create_order": {"product_id", "quantity"},
        "confirm_payment": {"user_confirmed"},
    }
    if tool_name in EXPECTED_KEYS:
        tool_input = {k: v for k, v in tool_input.items() if k in EXPECTED_KEYS[tool_name]}

    if tool_name == "search_products":
        results = catalog.search_products(
            query=tool_input.get("query", ""),
            max_price=tool_input.get("max_price"),
            size=tool_input.get("size"),
            color=tool_input.get("color"),
        )
        audit.log_event("search_products", tool_input, {"count": len(results)},
                         "User searched the catalog; returning matching products.")
        return {"products": results}

    if tool_name == "get_pairing_suggestions":
        suggestions = catalog.get_pairing_suggestions(tool_input.get("product_id", ""))
        audit.log_event("get_pairing_suggestions", tool_input,
                         {"suggestions": [s["id"] for s in suggestions]},
                         "Looking up complementary products for upsell.")
        return {"suggestions": suggestions}

    if tool_name == "create_order":
        raw_id = tool_input.get("product_id", "")
        product = catalog.get_product(raw_id) or catalog.find_product_by_name(raw_id)
        if not product:
            audit.log_event("create_order", tool_input, {"error": "not_found"},
                             "Product ID did not match any catalog item.")
            return {"error": f"No product matches '{raw_id}'. Call search_products first and use the exact id field from a result."}

        qty = tool_input.get("quantity", 1)
        try:
            qty = int(qty)
        except (ValueError, TypeError):
            qty = 1

        try:
            guardrails.check_stock(product, qty)
            existing_orders = orders_db.get_orders_for_session(session_id)
            guardrails.check_session_order_count(len(existing_orders))
            total = product["price"] * qty
            guardrails.check_order_value(total)
        except guardrails.GuardrailViolation as e:
            audit.log_event("create_order", tool_input, {"blocked": str(e)},
                             f"Guardrail blocked this order: {e}")
            return {"error": str(e)}

        order = orders_db.create_order_record(product, qty, session_id)
        audit.log_event("create_order", tool_input,
                         {"order_id": order["order_id"], "total": order["total_amount"]},
                         f"Order created for {product['name']} x{qty}, within limits, pending payment confirmation.")
        return {"order": order}

    if tool_name == "confirm_payment":
        user_confirmed = tool_input.get("user_confirmed", False)

        try:
            guardrails.check_explicit_confirmation(user_confirmed)
        except guardrails.GuardrailViolation as e:
            audit.log_event("confirm_payment", tool_input, {"blocked": str(e)},
                             f"Guardrail blocked payment: {e}")
            return {"error": str(e)}

        session_orders = orders_db.get_orders_for_session(session_id)
        pending_orders = [o for o in session_orders if o["status"] == "created"]
        order = pending_orders[-1] if pending_orders else None
        if not order:
            audit.log_event("confirm_payment", tool_input, {"error": "no_pending_order"},
                             "No pending (unpaid) order found for this session.")
            return {"error": "No pending order exists yet. You must call create_order first, then call confirm_payment."}

        order_id = order["order_id"]

        try:
            rp_order = payments.create_razorpay_order(order["total_amount"], receipt=order["order_id"])
            orders_db.mark_order_paid(order_id, razorpay_payment_id=rp_order["id"])
            audit.log_event("confirm_payment", tool_input,
                             {"razorpay_order_id": rp_order["id"], "status": "initiated"},
                             "User explicitly confirmed; Razorpay test order created and payment initiated.")
            return {"success": True, "razorpay_order_id": rp_order["id"]}
        except Exception as e:
            audit.log_event("confirm_payment", tool_input, {"error": str(e)},
                             f"Payment initiation failed: {e}")
            return {"error": f"Payment failed: {e}"}

    return {"error": f"Unknown tool {tool_name}"}


def chat(session_id: str, conversation_history: list, user_message: str):
    """
    Runs one turn of the agent loop: sends the conversation to Groq,
    executes any tool calls, feeds results back, and returns the final
    text reply plus the updated history.
    """
    if not conversation_history:
        conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]

    messages = conversation_history + [{"role": "user", "content": user_message}]

    while True:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=TOOLS,
            temperature=0,
        )

        choice = response.choices[0]
        message = choice.message

        if not message.tool_calls:
            messages.append({"role": "assistant", "content": message.content})
            return message.content, messages

        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [tc.model_dump() for tc in message.tool_calls],
        })

        for tool_call in message.tool_calls:
            import json
            tool_name = tool_call.function.name
            tool_input = json.loads(tool_call.function.arguments)
            result = execute_tool(tool_name, tool_input, session_id)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(result),
            })