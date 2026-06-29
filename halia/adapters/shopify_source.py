"""ShopifySource — read customers (and orders) from Shopify, behind the source port.

A thin wrapper: the heavy lifting (paged GraphQL fetch, GraphQL→REST adapt,
order→customer aggregation) already lives in `scoring/shopify_fetch.py` and
`scoring/shopify.py`. This just presents it as a `CustomerSource` so the engine and
sync loop never know it's Shopify. The `transport` is injectable for testing, exactly
like the fetch layer.
"""
from __future__ import annotations

from collections.abc import Iterator

from halia.ports import CustomerSource


class ShopifySource(CustomerSource):
    name = "shopify"

    def __init__(self, transport=None, **fetch_kwargs):
        self.transport = transport
        self.fetch_kwargs = fetch_kwargs
        self._orders: list[dict] | None = None

    def _orders_list(self) -> list[dict]:
        if self._orders is None:
            from scoring.shopify_fetch import fetch_orders
            self._orders = fetch_orders(self.transport, **self.fetch_kwargs)
        return self._orders

    def fetch_all(self) -> Iterator[dict]:
        from scoring.shopify import orders_to_customers
        customers = orders_to_customers(self._orders_list())
        for _, row in customers.iterrows():
            yield row.to_dict()

    def fetch_one(self, identifier: str, by: str = "email") -> dict | None:
        from scoring.shopify import orders_to_customers
        from scoring.shopify_fetch import fetch_customer_orders
        orders = fetch_customer_orders(identifier, transport=self.transport, by=by)
        if not orders:
            return None
        customers = orders_to_customers(orders)
        return None if customers.empty else customers.iloc[0].to_dict()

    def iter_orders(self) -> Iterator[dict]:
        for o in self._orders_list():
            cust = o.get("customer") or {}
            yield {
                "order_id": str(o.get("id") or o.get("name")),
                "customer_id": None if cust.get("id") is None else str(cust.get("id")),
                "email": o.get("email") or cust.get("email"),
                "created_at": o.get("created_at"),
            }
