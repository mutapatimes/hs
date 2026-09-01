"""Who is a manager here, and who is an associate.

The person who installs the app on Shopify is the one who bought it and set it up, so they are
the manager. Shopify tells us who that is: an App Bridge session token carries the staff user id
in ``sub``, which needs no scope (the staff *list* would need read_users, which is Plus-only, so
we never enumerate staff, we recognise them as they arrive). The first staff member to open the
embedded app is recorded as the owner, and from then on the owner and anyone they promote are
managers; everyone else who opens it is a stranger until the manager lets them in.

Two rules keep this from locking anyone out of their own store:

* A tenant who signs in with their private link (WooCommerce, BigCommerce, the hosted dashboard)
  holds the secret itself, so they are the manager. There is no staff identity to read there.
* A Shopify session we cannot attribute (no ``sub``) falls back to manager, exactly as before this
  existed. Losing a claim must never cost a merchant their own dashboard.

Managers can change what the whole store sees: settings, the house voice, billing, and the team.
Associates work the floor: clients, pipeline, appointments, selections, capture.
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import Depends, HTTPException, Request

from halia.api.shopify_auth import current_staff_id, require_shop, shop_store

MANAGER = "manager"
ASSOCIATE = "associate"


def _settings(shop: str) -> dict:
    raw = shop_store().get_settings_raw(shop)
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


def owner_staff_id(shop: str) -> str:
    return str(_settings(shop).get("owner_staff_id") or "")


def claim_owner(shop: str, staff_id: str, name: str = "") -> bool:
    """Record the first staff member to open the embedded app as the owner. Returns True when this
    call is the one that claimed it. Never overwrites an existing owner."""
    if not staff_id:
        return False
    data = _settings(shop)
    if data.get("owner_staff_id"):
        return False
    data["owner_staff_id"] = str(staff_id)[:64]
    if name:
        data["owner_name"] = str(name)[:120]
    shop_store().save_settings(shop, json.dumps(data))
    return True


def transfer_owner(shop: str, staff_id: str) -> None:
    """Hand the store to another Shopify staff member. Only a manager can call this."""
    data = _settings(shop)
    data["owner_staff_id"] = str(staff_id)[:64]
    shop_store().save_settings(shop, json.dumps(data))


def role_for_request(request: Request, shop: str) -> str:
    """The caller's role. See the module docstring for why an unidentifiable caller is a manager."""
    staff = current_staff_id(request)
    if not staff:
        return MANAGER                      # the private link, or a session with no staff claim
    owner = owner_staff_id(shop)
    if not owner:
        claim_owner(shop, staff)            # first one through the door set the store up
        return MANAGER
    if staff == owner:
        return MANAGER
    seat = shop_store().seat_by_staff_id(shop, staff)
    if seat:
        return MANAGER if (seat.get("role") or ASSOCIATE) == MANAGER else ASSOCIATE
    note_pending(shop, staff)               # a stranger: put them where the manager will see them
    return ASSOCIATE


def is_manager(request: Request, shop: str) -> bool:
    return role_for_request(request, shop) == MANAGER


def require_manager(request: Request, shop: str = Depends(require_shop)) -> str:
    """FastAPI dependency for anything that changes the whole store."""
    if not is_manager(request, shop):
        raise HTTPException(403, "Only a manager can change this. Ask whoever set the store up.")
    return shop


# ── access requests ──────────────────────────────────────────────────────────
# A Shopify staff member who opens the app and has no seat is a stranger. Rather than a silent
# refusal, they are put on a list the manager sees, so letting a new hire in is one tap.
_MAX_PENDING = 40


def note_pending(shop: str, staff_id: str, name: str = "", email: str = "") -> None:
    if not staff_id or shop_store().seat_by_staff_id(shop, staff_id):
        return
    if str(staff_id) == owner_staff_id(shop):
        return
    data = _settings(shop)
    pending = [p for p in (data.get("pending_staff") or []) if str(p.get("id")) != str(staff_id)]
    pending.append({"id": str(staff_id)[:64], "name": str(name or "")[:120],
                    "email": str(email or "")[:200]})
    data["pending_staff"] = pending[-_MAX_PENDING:]
    shop_store().save_settings(shop, json.dumps(data))


def pending_staff(shop: str) -> list[dict]:
    return [dict(p) for p in (_settings(shop).get("pending_staff") or [])]


def clear_pending(shop: str, staff_id: str) -> None:
    data = _settings(shop)
    data["pending_staff"] = [p for p in (data.get("pending_staff") or [])
                             if str(p.get("id")) != str(staff_id)]
    shop_store().save_settings(shop, json.dumps(data))


def seat_role(seat_id: Optional[str]) -> str:
    """The role on a seat token (the extension, the keyboard, the app). No seat means the legacy
    shared token, which predates roles and stays a manager."""
    if not seat_id:
        return MANAGER
    prof = shop_store().seat_profile(seat_id) or {}
    return MANAGER if (prof.get("role") or ASSOCIATE) == MANAGER else ASSOCIATE
