"""
Agent-readable catalog.
This is the structured "menu" an AI agent can query -- no scraping,
no guessing from a webpage, just clean JSON.
"""
import json
from config import PRODUCTS_FILE


def get_all_products():
    with open(PRODUCTS_FILE, "r") as f:
        return json.load(f)


def get_product(product_id: str):
    for p in get_all_products():
        if p["id"] == product_id:
            return p
    return None


def search_products(query: str = "", max_price: float = None, size: str = None, color: str = None):
    results = get_all_products()
    query = (query or "").lower().strip()

    if max_price is not None:
        max_price = float(max_price)
    ...

    def matches(p):
        if query:
            searchable_text = f"{p['name']} {p['category']} {p['description']} {p['color']}".lower()
            query_words = query.split()
            if not any(word in searchable_text for word in query_words):
                return False
        if max_price is not None and float(p["price"]) > max_price:
            return False
        if size and size.upper() not in [s.upper() for s in p["sizes_available"]]:
            return False
        if color and color.lower() != p["color"].lower():
            return False
        return True

    return [p for p in results if matches(p)]


def get_pairing_suggestions(product_id: str):
    """Returns product objects that pair well with the given product (for upsell)."""
    product = get_product(product_id)
    if not product:
        return []
    return [get_product(pid) for pid in product.get("pairs_with", []) if get_product(pid)]