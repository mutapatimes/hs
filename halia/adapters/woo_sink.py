"""WooCommerce write-back: the same sink surface as ShopifySink, over WC customer meta.

WooCommerce has no customer tags or metafields, so Halia keeps the pipeline, the capture record
and its tags in the customer's ``meta_data`` (``halia_pipeline``, ``halia_capture``,
``halia_preferences``, ``halia_tags``) in the merchant's own store. Nothing about a customer is
persisted by Halia; the only thing Halia keeps for a Woo store is an index of opaque customer
ids that carry a pipeline card or a capture record, so the board and the reports know which
customers to read (WC REST cannot search by meta). Campaign memberships already hold ids the
same way.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from scoring.shopify_pipeline import STAGES, stage_tag

KEY = "halia_"


class WooClient:
    """The thin REST client (HTTP Basic over HTTPS). Injectable for tests."""

    def __init__(self, store_url: str, ck: str, cs: str, timeout: int = 30):
        from scoring.woocommerce_fetch import endpoint
        self.store_url, self.ck, self.cs, self.timeout, self._endpoint = store_url, ck, cs, timeout, endpoint

    def req(self, method: str, path: str, params: dict | None = None, body: dict | None = None):
        import requests
        resp = requests.request(method, self._endpoint(self.store_url, path), params=params, json=body,
                                auth=(self.ck, self.cs), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()


def _meta_get(customer: dict, key: str):
    for m in customer.get("meta_data") or []:
        if m.get("key") == key:
            return m.get("value")
    return None


class WooSink:
    name = "woocommerce"

    def __init__(self, client: WooClient, index_add: Callable[[str, str], None] | None = None,
                 index_remove: Callable[[str, str], None] | None = None,
                 index_list: Callable[[str], list[str]] | None = None):
        self.client = client
        self.index_add = index_add or (lambda kind, cid: None)
        self.index_remove = index_remove or (lambda kind, cid: None)
        self.index_list = index_list or (lambda kind: [])
        self._cache: dict[str, dict] = {}

    # ── compat with the Shopify sink surface ──
    def _transport(self):
        return lambda path, params: self.client.req("GET", path, params=params)

    # ── customers ──
    def resolve_customer(self, cid: str, create: bool = True, fields: dict | None = None) -> str | None:
        """A WC customer id for a Halia cid. Guest orders carry the email as their cid; those are
        looked up by email and, if the merchant is putting them on the pipeline, registered."""
        cid = str(cid or "").strip()
        if cid.isdigit():
            return cid
        if "@" in cid:
            found = self.find_customer(cid, "")
            if found:
                return str(found["id"])
            if create:
                return str(self.create_customer({"email": cid, **(fields or {})})["id"])
        return None

    def get_customer(self, wid: str) -> dict:
        if wid not in self._cache:
            self._cache[wid] = self.client.req("GET", f"customers/{wid}")
        return self._cache[wid]

    def find_customer(self, email: str, phone: str) -> dict | None:
        if email:
            rows = self.client.req("GET", "customers", params={"email": email, "per_page": 1}) or []
            if rows:
                return rows[0]
        if phone:
            digits = "".join(ch for ch in phone if ch.isdigit())
            if len(digits) >= 7:
                rows = self.client.req("GET", "customers", params={"search": digits[-9:], "per_page": 5}) or []
                for r in rows:
                    bp = "".join(ch for ch in str((r.get("billing") or {}).get("phone") or "") if ch.isdigit())
                    if bp.endswith(digits[-9:]):
                        return r
        return None

    def create_customer(self, fields: dict) -> dict:
        body: dict = {"email": fields.get("email") or ""}
        for k in ("first_name", "last_name"):
            if fields.get(k):
                body[k] = fields[k]
        billing = {k: v for k, v in {
            "first_name": fields.get("first_name"), "last_name": fields.get("last_name"),
            "phone": fields.get("phone"), "address_1": fields.get("address"),
            "city": fields.get("city"), "postcode": fields.get("postcode"),
            "country": fields.get("country_code")}.items() if v}
        if billing:
            body["billing"] = billing
        if fields.get("meta"):
            body["meta_data"] = [{"key": k, "value": v} for k, v in fields["meta"].items()]
        out = self.client.req("POST", "customers", body=body)
        self._cache[str(out["id"])] = out
        return out

    def update_customer(self, wid: str, fields: dict) -> dict:
        body: dict = {}
        for k in ("first_name", "last_name", "email"):
            if fields.get(k):
                body[k] = fields[k]
        billing = {k: v for k, v in {
            "phone": fields.get("phone"), "address_1": fields.get("address"),
            "city": fields.get("city"), "postcode": fields.get("postcode")}.items() if v}
        if billing:
            body["billing"] = {**((self.get_customer(wid).get("billing") or {})), **billing}
        if fields.get("meta"):
            body["meta_data"] = [{"key": k, "value": v} for k, v in fields["meta"].items()]
        out = self.client.req("PUT", f"customers/{wid}", body=body)
        self._cache[wid] = out
        return out

    # ── "metafields" and "tags" over meta_data ──
    def get_metafield(self, customer_id: str, key: str, namespace: str = "halia"):
        wid = self.resolve_customer(customer_id, create=False)
        if not wid:
            return None
        try:
            return _meta_get(self.get_customer(wid), KEY + key)
        except Exception:  # noqa: BLE001
            return None

    def set_metafield(self, customer_id: str, key: str, value: str, mtype: str = "json",
                      namespace: str = "halia") -> None:
        wid = self.resolve_customer(customer_id)
        if not wid:
            return
        self.update_customer(wid, {"meta": {KEY + key: value}})
        if key == "pipeline":
            self.index_add("pipeline", wid)
        if key == "capture":
            self.index_add("captured", wid)

    def _tags(self, wid: str) -> list[str]:
        raw = _meta_get(self.get_customer(wid), KEY + "tags")
        try:
            tags = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (TypeError, ValueError):
            tags = []
        return [str(t) for t in tags] if isinstance(tags, list) else []

    def tag_customer(self, customer_id: str, tags: list[str]) -> None:
        wid = self.resolve_customer(customer_id)
        if not wid:
            return
        cur = self._tags(wid)
        new = cur + [t for t in tags if t not in cur]
        self.update_customer(wid, {"meta": {KEY + "tags": json.dumps(new)}})
        if any(t in {stage_tag(s) for s in STAGES} for t in tags):
            self.index_add("pipeline", wid)

    def untag_customer(self, customer_id: str, tags: list[str]) -> None:
        wid = self.resolve_customer(customer_id, create=False)
        if not wid:
            return
        cur = self._tags(wid)
        new = [t for t in cur if t not in tags]
        if new != cur:
            self.update_customer(wid, {"meta": {KEY + "tags": json.dumps(new)}})
        if not any(t in {stage_tag(s) for s in STAGES} for t in new):
            self.index_remove("pipeline", wid)

    # ── readers the board, the reports and the birthdays fold over ──
    def pipeline_cards(self) -> dict:
        cards: dict = {}
        for wid in self.index_list("pipeline"):
            try:
                c = self.get_customer(wid)
            except Exception:  # noqa: BLE001
                continue
            raw = _meta_get(c, KEY + "pipeline")
            try:
                pipe = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except (TypeError, ValueError):
                pipe = {}
            tags = self._tags(wid)
            stage = pipe.get("stage") or next((s for s in STAGES if stage_tag(s) in tags), None)
            if not stage:
                continue
            cards[wid] = {"cid": wid, "stage": stage,
                          "name": " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x).strip(),
                          "email": c.get("email") or "", "assignee": pipe.get("assignee"),
                          "activity": pipe.get("activity") or []}
        return cards

    def captures(self) -> list[dict]:
        out = []
        for wid in self.index_list("captured"):
            try:
                c = self.get_customer(wid)
            except Exception:  # noqa: BLE001
                continue
            raw = _meta_get(c, KEY + "capture")
            try:
                rec = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except (TypeError, ValueError):
                rec = {}
            if isinstance(rec, dict):
                rec = dict(rec); rec["cid"] = wid
                prefs = _meta_get(c, KEY + "preferences")
                try:
                    rec["preferences"] = json.loads(prefs) if isinstance(prefs, str) else (prefs or {})
                except (TypeError, ValueError):
                    rec["preferences"] = {}
                rec["name"] = " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x).strip()
                out.append(rec)
        return out
