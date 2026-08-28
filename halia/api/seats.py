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

from fastapi import HTTPException, Body, Depends

from halia import config
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


def _welcome_associate(shop: str, email: str, name: str, connect: str) -> None:
    """A new seat starts the associate journey (how to sign in, the first moves, capture) and
    joins the Brevo associates list. Best-effort: a mail hiccup never blocks the seat."""
    try:
        from halia import journeys
        from halia.api.shopify_auth import shop_store as _ss
        tenant = dict(_ss().get_tenant(shop) or {})
        journeys.enroll_associate(email, first=name.split(" ")[0] if name else "",
                                  shop=shop, store_name=tenant.get("label") or shop,
                                  connect=connect)
    except Exception:  # noqa: BLE001
        pass
    try:
        from halia import notify_brevo
        notify_brevo.add_associate(email, {"SEAT_NAME": name, "SHOP": shop})
    except Exception:  # noqa: BLE001
        pass


def register(app) -> None:
    @app.get("/v1/seats")
    def list_seats(shop: str = Depends(require_shop)) -> dict:
        """The tenant's seats for the dashboard Team panel, plus the active-seat count (billing meter)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_ACTIVE_DAYS)).isoformat(timespec="seconds")
        seats = []
        for s in shop_store().list_seats(shop):
            last = s.get("last_seen_at")
            seats.append({"id": s["id"], "name": s["name"], "email": s.get("email") or "",
                          "title": s.get("title") or "", "signoff": s.get("signoff") or "",
                          "lastSeen": last, "active": bool(last and last >= cutoff)})
        return {"seats": seats, "count": shop_store().active_seat_count(shop, days=_ACTIVE_DAYS)}

    @app.post("/v1/seats")
    def create_seat(shop: str = Depends(require_shop), payload: dict = Body(default={})) -> dict:
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
        if existing:
            # The email is the identity: a second "add" re-issues that seat's token rather
            # than creating a twin (a lost phone, a new laptop). The old token stops working.
            store.rotate_seat_token(existing["id"], hash_token(token), name)
            seat_id, reissued = existing["id"], True
        else:
            seat_id = store.create_seat(shop, name, hash_token(token), email)
        connect = f"halia://connect?t={token}&b={base}"
        if email and not reissued:
            _welcome_associate(shop, email, name, connect)
        return {"seat_id": seat_id, "name": name, "email": email, "token": token, "base": base,
                "connect": connect, "qr": _connect_qr(connect), "reissued": reissued}

    def _own_seat(shop: str, seat_id: str) -> dict:
        for s in shop_store().list_seats(shop):
            if s["id"] == seat_id:
                return s
        raise HTTPException(404, "No such seat.")

    @app.patch("/v1/seats/{seat_id}")
    def edit_seat(seat_id: str, shop: str = Depends(require_shop), payload: dict = Body(default={})) -> dict:
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
    def reissue_seat(seat_id: str, shop: str = Depends(require_shop)) -> dict:
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
    def revoke_seat(seat_id: str, shop: str = Depends(require_shop)) -> dict:
        """Hard-kill a seat: its token stops authenticating and it drops from the seat count."""
        shop_store().revoke_seat(shop, seat_id)
        return {"ok": True}
