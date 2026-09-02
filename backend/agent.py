"""
The agent brain.
Uses Claude with tool-calling: the LLM decides which function to call
(search products, create order, confirm payment) based on the
conversation, and we execute those functions server-side with
guardrails + audit logging wrapped around every money-affecting step.
"""
import anthropic
from config import ANTHROPIC_API_KEY
import catalog
import orders as orders_db
import payments
import guardrails
import audit

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """You are a shopping assistant for TeeStore, a small clothing store.
You help customers find and buy products using the available tools.

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
        "name": "search_products",
        "description": "Search the product catalog by keyword, max price, size, or color.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword to search for, e.g. 'tee', 'jacket'"},
                "max_price": {"type": "number", "description": "Maximum price in INR"},
                "size": {"type": "string", "description": "Size filter, e.g. 'M'"},
                "color": {"type": "string", "description": "Color filter, e.g. 'black'"},
            },
        },
    },
    {
        "name": "get_pairing_suggestions",
        "description": "Get complementary products that pair well with a given product ID, for upsell suggestions.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}},
            "required": ["product_id"],
        },
    },
    {
        "name": "create_order",
        "description": "Create an order for a product. This does NOT charge payment yet -- it just reserves the order and returns the total to confirm with the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
                "quantity": {"type": "integer"},
            },
            "required": ["product_id", "quantity"],
        },
    },
    {
        "name": "confirm_payment",
        "description": "Charge payment for a previously created order. Only call this AFTER the user has explicitly confirmed they want to pay.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "user_confirmed": {"type": "boolean", "description": "Must be true, based on an explicit user 'yes'"},
            },
            "required": ["order_id", "user_confirmed"],
        },
    },
]


def execute_tool(tool_name: str, tool_input: dict, session_id: str):
    """Runs the actual function behind a tool call, with guardrails + audit logging."""

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
        suggestions = catalog.get_pairing_suggestions(tool_input["product_id"])
        audit.log_event("get_pairing_suggestions", tool_input,
                         {"suggestions": [s["id"] for s in suggestions]},
                         "Looking up complementary products for upsell.")
        return {"suggestions": suggestions}

    if tool_name == "create_order":
        product = catalog.get_product(tool_input["product_id"])
        if not product:
            audit.log_event("create_order", tool_input, {"error": "not_found"},
                             "Product ID did not match any catalog item.")
            return {"error": f"Product {tool_input['product_id']} not found."}

        qty = tool_input["quantity"]
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
        order_id = tool_input["order_id"]
        user_confirmed = tool_input.get("user_confirmed", False)

        try:
            guardrails.check_explicit_confirmation(user_confirmed)
        except guardrails.GuardrailViolation as e:
            audit.log_event("confirm_payment", tool_input, {"blocked": str(e)},
                             f"Guardrail blocked payment: {e}")
            return {"error": str(e)}

        session_orders = orders_db.get_orders_for_session(session_id)
        order = next((o for o in session_orders if o["order_id"] == order_id), None)
        if not order:
            audit.log_event("confirm_payment", tool_input, {"error": "order_not_found"},
                             "No matching order found for this session.")
            return {"error": "Order not found."}

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
    Runs one turn of the agent loop: sends the conversation to Claude,
    executes any tool calls, feeds results back, and returns the final
    text reply plus the updated history.
    """
    messages = conversation_history + [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            final_text = "".join(block.text for block in response.content if block.type == "text")
            messages.append({"role": "assistant", "content": response.content})
            return final_text, messages

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = execute_tool(block.name, block.input, session_id)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result),
                })

        messages.append({"role": "user", "content": tool_results})