"""GraphQL Admin API adapter.

We fetch customers (with their orders) from Shopify's GraphQL Admin API, then
transform each order node into the **REST-shaped order dict** that
``scoring.shopify.flatten_order`` already expects. That keeps the tested core
(flatten + aggregate + signals) completely untouched — this module is the only
new surface for moving from REST to GraphQL.

The query is customer-centric, so a single response gives us, per customer:
  - identity + tags (drives Name/email/phone/SEGMENT),
  - ``amountSpent`` / ``numberOfOrders`` (authoritative spend + order count,
    stashed on each order dict for the future behavioural-feature layer),
  - every order with its billing/shipping address, discount total, timestamp.

Pipeline:  GraphQL nodes ──graphql_customers_to_orders──▶ REST-shaped orders
           ──orders_to_customers──▶ per-customer DataFrame ──▶ score_customers
"""
from __future__ import annotations

# The customer node fields, shared by the paged backfill query and the
# single-customer lookup (so they never drift). orders are capped at 250 per
# customer; country is the NAME (matchers key on names — see ingestion spec
# §3/§8), with countryCodeV2 carried for the optional country-code upgrade.
_CUSTOMER_NODE = """
      id
      email
      phone
      firstName
      lastName
      tags
      numberOfOrders
      amountSpent { amount currencyCode }
      orders(first: 60) {
        nodes {
          id
          createdAt
          displayFinancialStatus
          displayFulfillmentStatus
          cancelledAt
          tags
          totalPriceSet { shopMoney { amount } }
          totalDiscountsSet { shopMoney { amount } }
          billingAddress { address1 address2 city country countryCodeV2 zip company phone }
          shippingAddress { address1 address2 city country countryCodeV2 zip company phone }
          lineItems(first: 10) { nodes { quantity } }
        }
      }
"""

# Paged pull for the initial backfill / refresh (cursor on the customers conn).
CUSTOMERS_QUERY = (
    "query Customers($cursor: String) {\n"
    "  customers(first: 50, after: $cursor) {\n"
    "    pageInfo { hasNextPage endCursor }\n"
    "    nodes {" + _CUSTOMER_NODE + "    }\n"
    "  }\n"
    "}\n"
)

# Single-customer lookup by email/phone — the real-time / POS path.
# Pass variables {"q": "email:a@b.com"} or {"q": "phone:+4477..."}.
CUSTOMER_BY_QUERY = (
    "query OneCustomer($q: String!) {\n"
    "  customers(first: 1, query: $q) {\n"
    "    nodes {" + _CUSTOMER_NODE + "    }\n"
    "  }\n"
    "}\n"
)


# Catalog products — a separate, product-centric pull (not customer data), used by the
# catalog-PDF builder. Cursor-paged over the products connection.
PRODUCTS_QUERY = (
    "query Products($cursor: String) {\n"
    "  products(first: 100, after: $cursor, sortKey: TITLE) {\n"
    "    pageInfo { hasNextPage endCursor }\n"
    "    nodes {\n"
    "      id title handle vendor productType tags status\n"
    "      description(truncateAt: 400)\n"
    "      variantsCount { count }\n"
    "      featuredImage { url }\n"
    "      images(first: 1) { nodes { url } }\n"
    "      variants(first: 1) { nodes { sku } }\n"
    "      priceRangeV2 { minVariantPrice { amount currencyCode } }\n"
    "      collections(first: 8) { nodes { title } }\n"
    "    }\n"
    "  }\n"
    "}\n"
)


def product_node_to_dict(node: dict) -> dict:
    """Shopify product node -> a flat dict for the catalog picker / renderer."""
    node = node or {}
    img = (node.get("featuredImage") or {}).get("url")
    if not img:
        imgs = ((node.get("images") or {}).get("nodes")) or []
        img = imgs[0].get("url") if imgs else None
    price_obj = ((node.get("priceRangeV2") or {}).get("minVariantPrice")) or {}
    collections = [c.get("title") for c in (((node.get("collections") or {}).get("nodes")) or [])
                   if c.get("title")]
    tags = node.get("tags")
    tags = list(tags) if isinstance(tags, (list, tuple)) else ([tags] if tags else [])
    variants_nodes = ((node.get("variants") or {}).get("nodes")) or []
    sku = variants_nodes[0].get("sku") if variants_nodes else None
    return {
        "id": node.get("id"),
        "title": node.get("title") or "Untitled",
        "handle": node.get("handle"),
        "vendor": node.get("vendor") or "",
        "type": node.get("productType") or "",
        "tags": tags,
        "collections": collections,
        "image_url": img,
        "price": price_obj.get("amount"),
        "currency": price_obj.get("currencyCode") or "",
        "status": node.get("status"),
        "description": (node.get("description") or "").strip(),
        "sku": sku or "",
        "variants": ((node.get("variantsCount") or {}).get("count")) or 0,
    }


def _address(node: dict | None) -> dict | None:
    """GraphQL MailingAddress -> REST address dict (snake_case keys)."""
    if not node:
        return None
    return {
        "address1": node.get("address1"),
        "address2": node.get("address2"),
        "city": node.get("city"),
        "country": node.get("country"),            # NAME — matchers key on this
        "country_code": node.get("countryCodeV2"),  # carried for the code upgrade
        "zip": node.get("zip"),
        "company": node.get("company"),
        "phone": node.get("phone"),
    }


def _money(node: dict | None) -> str | None:
    """{ shopMoney { amount } } -> the amount string, or None."""
    return ((node or {}).get("shopMoney") or {}).get("amount")


def _tags_str(tags) -> str:
    """GraphQL tags are a list; flatten_order expects a comma-joined string."""
    if isinstance(tags, (list, tuple)):
        return ", ".join(str(t) for t in tags)
    return tags or ""


def order_node_to_rest(order: dict, customer: dict) -> dict:
    """Transform one GraphQL order node (+ its parent customer) into the REST
    order shape ``flatten_order`` consumes."""
    amount_spent = (customer.get("amountSpent") or {}).get("amount")
    line_items = ((order.get("lineItems") or {}).get("nodes")) or []

    return {
        "id": order.get("id"),
        "email": customer.get("email"),
        "phone": customer.get("phone"),
        "created_at": order.get("createdAt"),
        # Order status -> powers the dashboard Orders view (shared with WooCommerce).
        "financial_status": str(order.get("displayFinancialStatus") or "").lower(),
        "fulfillment_status": str(order.get("displayFulfillmentStatus") or "").lower(),
        "cancelled_at": order.get("cancelledAt"),
        "tags": _tags_str(order.get("tags")),
        "total_price": _money(order.get("totalPriceSet")),
        "total_discounts": _money(order.get("totalDiscountsSet")),
        "billing_address": _address(order.get("billingAddress")),
        "shipping_address": _address(order.get("shippingAddress")),
        # Shopify removed Order.clientDetails (browser IP) in recent API versions;
        # the ip_location signal is dormant anyway. Omit it.
        "line_items": [{"quantity": li.get("quantity")} for li in line_items],
        "customer": {
            "id": customer.get("id"),
            "email": customer.get("email"),
            "first_name": customer.get("firstName"),
            "last_name": customer.get("lastName"),
            "phone": customer.get("phone"),
            "tags": _tags_str(customer.get("tags")),
            # Authoritative customer-level rollups for the behavioural layer (§5a).
            "amount_spent": amount_spent,
            "number_of_orders": customer.get("numberOfOrders"),
        },
    }


def graphql_customers_to_orders(customer_nodes: list[dict]) -> list[dict]:
    """Flatten GraphQL ``customers.nodes`` into a flat list of REST-shaped orders.

    The result feeds straight into ``scoring.shopify.orders_to_customers``.
    Customers with no orders are skipped (nothing to score on yet).
    """
    orders: list[dict] = []
    for customer in customer_nodes or []:
        for order in ((customer.get("orders") or {}).get("nodes")) or []:
            orders.append(order_node_to_rest(order, customer))
    return orders
