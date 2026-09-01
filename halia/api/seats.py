"""Team seats: per-employee sign-in credentials a manager provisions in the dashboard.

Each seat is one staff member's login for the browser extension and the iOS keyboard. The manager
adds a seat (a name), gets a personal join QR / token to hand to that employee, and can revoke a
seat at any time. The token is the same shape as the shared extension token (a hashed capability);
the difference is that a seat carries an identity, so attribution is authenticated and the active
seat count can meter per-head billing later.

Manager-only (require_shop). The per-seat token is authenticated on the extension endpoints by
`extension._resolve_ext`. Nothing customer-related is stored.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Body, Depends, HTTPException, Request

from halia import config
from halia.api.roles import require_manager
from halia.api.shopify_auth import require_shop, shop_store
from halia.api.tenant_auth import hash_token, new_token

_ACTIVE_DAYS = 30


def _connect_qr(connect: str) -> Optional[str]:
    """A PNG data-URL QR of the halia://connect deep link, so the employee scans instead of typing.
    A convenience only: returns None if the QR library is unavailable."""
    try:
        import base64
        import io

        import segno
        buf = io.BytesIO()
        segno.make(connect, error="m").save(buf, kind="png", scale=6, border=2)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001 — never fail seat creation over the QR
        return None


def _welcome_associate(shop: str, email: str, name: str, connect: str, seat_id: str = "") -> None:
    """A new seat starts the associate journey (how to sign in, the first moves, capture) and
    joins the Brevo associates list. Best-effort: a mail hiccup never blocks the seat."""
    try:
        from halia import journeys
        from halia.api.shopify_auth import shop_store as _ss
        tenant = dict(_ss().get_tenant(shop) or {})
        journeys.enroll_associate(email, first=name.split(" ")[0] if name else "",
                                  shop=shop, store_name=tenant.get("label") or shop,
                                  connect=connect)
        if seat_id:
            journeys.enroll_monthly(email, seat_id, shop, tenant.get("label") or shop,
                                    name.split(" ")[0] if name else "")
    except Exception:  # noqa: BLE001
        pass
    try:
        from halia import notify_brevo
        notify_brevo.add_associate(email, {"SEAT_NAME": name, "SHOP": shop})
    except Exception:  # noqa: BLE001
        pass


FREE_SEATS = 1   # the free scan comes with one sign-in; teammates need a plan


def seat_terms(shop: str) -> dict:
    """What adding a seat means for this tenant: plan, bundle, price, and the live count."""
    from halia import plans
    from halia.api.billing import _free_shops
    from halia.api.billing_shopify import plan_key_for

    try:
        key = plan_key_for(shop)
    except Exception:  # noqa: BLE001 — billing lookups must never block the Team card
        key = "free"
    comped = shop in _free_shops()
    p = plans.plan(key) or {}
    inc = plans.included_seats(key)
    return {"key": key, "name": p.get("name") or key, "comped": comped,
            "metered": inc is not None and not comped, "included": inc,
            "free": key == "free" and not comped, "freeSeats": FREE_SEATS,
            "seatPrice": plans.SEAT_PRICE, "seats": len(shop_store().list_seats(shop))}


def register(app) -> None:
    @app.get("/v1/seats")
    def list_seats(request: Request, shop: str = Depends(require_shop)) -> dict:
        """The tenant's seats for the dashboard Team panel, plus the active-seat count (billing meter),
        who is a manager, and any Shopify staff waiting to be let in."""
        from halia.api import roles

        cutoff = (datetime.now(timezone.utc) - timedelta(days=_ACTIVE_DAYS)).isoformat(timespec="seconds")
        seats = []
        for s in shop_store().list_seats(shop):
            last = s.get("last_seen_at")
            seats.append({"id": s["id"], "name": s["name"], "email": s.get("email") or "",
                          "title": s.get("title") or "", "signoff": s.get("signoff") or "",
                          "role": s.get("role") or "associate",
                          "shopifyUser": bool(s.get("staff_user_id")),
                          "lastSeen": last, "active": bool(last and last >= cutoff)})
        mine = roles.role_for_request(request, shop)
        return {"seats": seats, "count": shop_store().active_seat_count(shop, days=_ACTIVE_DAYS),
                "plan": seat_terms(shop), "role": mine,
                "pending": roles.pending_staff(shop) if mine == roles.MANAGER else []}

    @app.post("/v1/seats/{seat_id}/role")
    def set_seat_role(seat_id: str, shop: str = Depends(require_manager),
                      payload: dict = Body(default={})) -> dict:
        """Promote a teammate to manager, or put them back on the floor. A manager can change the
        settings, the house voice, billing and the team, so this is the only door to that."""
        from halia.api import roles

        _own_seat(shop, seat_id)
        role = str((payload or {}).get("role") or "").strip().lower()
        if role not in (roles.MANAGER, roles.ASSOCIATE):
            raise HTTPException(422, "Role must be manager or associate.")
        shop_store().set_seat_role(shop, seat_id, role)
        return {"ok": True, "role": role}

    @app.post("/v1/seats/grant")
    def grant_staff(shop: str = Depends(require_manager), payload: dict = Body(default={})) -> dict:
        """Let a Shopify staff member who has opened the app in as an associate (or a manager).
        They are recognised by their Shopify account from then on, with no token to hand over."""
        from halia.api import roles

        p = payload or {}
        staff_id = str(p.get("staff_id") or "").strip()[:64]
        if not staff_id:
            raise HTTPException(422, "staff_id is required.")
        role = roles.MANAGER if str(p.get("role") or "").lower() == roles.MANAGER else roles.ASSOCIATE
        store = shop_store()
        existing = store.seat_by_staff_id(shop, staff_id)
        if existing:
            store.set_seat_role(shop, existing["id"], role)
            roles.clear_pending(shop, staff_id)
            return {"ok": True, "seat_id": existing["id"], "role": role}
        name = str(p.get("name") or "").strip()[:80] or "Teammate"
        email = str(p.get("email") or "").strip().lower()[:200]
        seat_id = store.seat_by_email(shop, email)["id"] if (email and store.seat_by_email(shop, email)) else ""
        if seat_id:                                  # they already had a seat: just tie it to Shopify
            store.link_seat_staff_id(seat_id, staff_id)
            store.set_seat_role(shop, seat_id, role)
        else:
            terms = seat_terms(shop)
            if terms["free"] and terms["seats"] >= terms["freeSeats"]:
                raise HTTPException(402, "The free scan includes one sign-in. Choose a plan in Billing to add teammates.")
            token = new_token()
            seat_id = store.create_seat(shop, name, hash_token(token), email,
                                        role=role, staff_user_id=staff_id)
        roles.clear_pending(shop, staff_id)
        return {"ok": True, "seat_id": seat_id, "role": role}

    @app.post("/v1/seats/deny")
    def deny_staff(shop: str = Depends(require_manager), payload: dict = Body(default={})) -> dict:
        """Take a waiting Shopify staff member off the list. They keep no access either way."""
        from halia.api import roles

        staff_id = str((payload or {}).get("staff_id") or "").strip()[:64]
        roles.clear_pending(shop, staff_id)
        return {"ok": True}

    @app.post("/v1/seats")
    def create_seat(shop: str = Depends(require_manager), payload: dict = Body(default={})) -> dict:
        """Provision a seat and return its one-time join token + QR (the raw token is shown only here)."""
        from halia.capture_quality import clean_email

        name = str((payload or {}).get("name") or "").strip()[:80] or "Teammate"
        raw_email = str((payload or {}).get("email") or "").strip()
        email, _, ok = clean_email(raw_email, check_dns=False) if raw_email else ("", None, True)
        if raw_email and not ok:
            raise HTTPException(422, "That email address does not look right.")
        token = new_token()
        base = (config.HALIA_APP_URL or "").rstrip("/")
        store = shop_store()
        reissued = False
        existing = store.seat_by_email(shop, email) if email else None
        if not existing:
            terms = seat_terms(shop)
            if terms["free"] and terms["seats"] >= terms["freeSeats"]:
                raise HTTPException(402, "The free scan includes one sign-in. Choose a plan in Billing to add teammates.")
        if existing:
            # The email is the identity: a second "add" re-issues that seat's token rather
            # than creating a twin (a lost phone, a new laptop). The old token stops working.
            store.rotate_seat_token(existing["id"], hash_token(token), name)
            seat_id, reissued = existing["id"], True
        else:
            seat_id = store.create_seat(shop, name, hash_token(token), email)
        connect = f"halia://connect?t={token}&b={base}"
        if email and not reissued:
            _welcome_associate(shop, email, name, connect, seat_id)
        return {"seat_id": seat_id, "name": name, "email": email, "token": token, "base": base,
                "connect": connect, "qr": _connect_qr(connect), "reissued": reissued}

    def _own_seat(shop: str, seat_id: str) -> dict:
        for s in shop_store().list_seats(shop):
            if s["id"] == seat_id:
                return s
        raise HTTPException(404, "No such seat.")

    @app.patch("/v1/seats/{seat_id}")
    def edit_seat(seat_id: str, shop: str = Depends(require_manager), payload: dict = Body(default={})) -> dict:
        """Edit a teammate's details from the dashboard: name, email, position, sign-off."""
        from halia.capture_quality import clean_email

        _own_seat(shop, seat_id)
        p = payload or {}
        fields: dict = {}
        if "name" in p:
            fields["name"] = str(p.get("name") or "").strip()[:80] or "Teammate"
        if "email" in p:
            raw = str(p.get("email") or "").strip()
            email, _, ok = clean_email(raw, check_dns=False) if raw else ("", None, True)
            if raw and not ok:
                raise HTTPException(422, "That email address does not look right.")
            other = shop_store().seat_by_email(shop, email) if email else None
            if other and other["id"] != seat_id:
                raise HTTPException(409, "Another teammate already uses that email.")
            fields["email"] = email
        for key in ("title", "signoff"):
            if key in p:
                fields[key] = str(p.get(key) or "").strip()[:80]
        if fields:
            shop_store().update_seat_profile(seat_id, **fields)
        return {"ok": True, "seat": {"id": seat_id, **(shop_store().seat_profile(seat_id) or {})}}

    @app.post("/v1/seats/{seat_id}/reissue")
    def reissue_seat(seat_id: str, shop: str = Depends(require_manager)) -> dict:
        """A fresh sign-in for an existing teammate (new phone, new laptop). The old token stops."""
        seat = _own_seat(shop, seat_id)
        token = new_token()
        base = (config.HALIA_APP_URL or "").rstrip("/")
        shop_store().rotate_seat_token(seat_id, hash_token(token))
        connect = f"halia://connect?t={token}&b={base}"
        return {"seat_id": seat_id, "name": seat["name"], "email": seat.get("email") or "",
                "token": token, "base": base, "connect": connect, "qr": _connect_qr(connect),
                "reissued": True}

    @app.post("/v1/seats/{seat_id}/revoke")
    def revoke_seat(seat_id: str, shop: str = Depends(require_manager)) -> dict:
        """Hard-kill a seat: its token stops authenticating and it drops from the seat count."""
        shop_store().revoke_seat(shop, seat_id)
        return {"ok": True}
