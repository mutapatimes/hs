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

from fastapi import Body, Depends

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


def register(app) -> None:
    @app.get("/v1/seats")
    def list_seats(shop: str = Depends(require_shop)) -> dict:
        """The tenant's seats for the dashboard Team panel, plus the active-seat count (billing meter)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_ACTIVE_DAYS)).isoformat(timespec="seconds")
        seats = []
        for s in shop_store().list_seats(shop):
            last = s.get("last_seen_at")
            seats.append({"id": s["id"], "name": s["name"], "lastSeen": last,
                          "active": bool(last and last >= cutoff)})
        return {"seats": seats, "count": shop_store().active_seat_count(shop, days=_ACTIVE_DAYS)}

    @app.post("/v1/seats")
    def create_seat(shop: str = Depends(require_shop), payload: dict = Body(default={})) -> dict:
        """Provision a seat and return its one-time join token + QR (the raw token is shown only here)."""
        name = str((payload or {}).get("name") or "").strip()[:80] or "Teammate"
        token = new_token()
        seat_id = shop_store().create_seat(shop, name, hash_token(token))
        base = (config.HALIA_APP_URL or "").rstrip("/")
        connect = f"halia://connect?t={token}&b={base}"
        return {"seat_id": seat_id, "name": name, "token": token, "base": base,
                "connect": connect, "qr": _connect_qr(connect)}

    @app.post("/v1/seats/{seat_id}/revoke")
    def revoke_seat(seat_id: str, shop: str = Depends(require_shop)) -> dict:
        """Hard-kill a seat: its token stops authenticating and it drops from the seat count."""
        shop_store().revoke_seat(shop, seat_id)
        return {"ok": True}
