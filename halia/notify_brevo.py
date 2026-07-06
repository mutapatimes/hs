"""Halia's own marketing-list sync into Brevo.

This is distinct from the merchant-facing CRM sinks (halia/adapters/klaviyo_sink,
mailchimp_sink, hubspot_sink), which write the Halia grade onto a *client's* audience. Here we
manage **Halia's own** Brevo contact lists so that Brevo automations fire the lifecycle journeys:

  - a demo lead (someone who asked for a demo) is added to the Demo list, which triggers the
    demo-nurture automation (instant "we'll be in touch" + a 3-email drip);
  - a new client is added to the Clients list (and unlinked from Demo so the demo drip stops),
    triggering the client welcome/onboarding series.

Uses the same HALIA_BREVO_API_KEY as transactional email. Best-effort by design: it never raises
into a request path and returns a bool. When the API key is unset it is a silent no-op, so local
dev and tests without Brevo keep working.
"""
from __future__ import annotations

import os

from halia import config


def _key() -> str | None:
    return os.environ.get("HALIA_BREVO_API_KEY")


def configured() -> bool:
    return bool(_key())


def _demo_list() -> int:
    try:
        return int(config.BREVO_LIST_DEMO)
    except (TypeError, ValueError):
        return 3


def _clients_list() -> int:
    try:
        return int(config.BREVO_LIST_CLIENTS)
    except (TypeError, ValueError):
        return 4


def _call(body: dict) -> int:
    """POST a contact upsert to Brevo; return the HTTP status (0 on transport error).

    Kept as a tiny seam so tests can monkeypatch it without any network.
    """
    import requests
    try:
        resp = requests.post(
            "https://api.brevo.com/v3/contacts",
            json=body,
            headers={"api-key": _key() or "", "accept": "application/json",
                     "content-type": "application/json"},
            timeout=15,
        )
        return resp.status_code
    except Exception:  # noqa: BLE001 - never break the caller
        return 0


def sync_contact(email: str, *, list_ids: list[int] | tuple[int, ...] = (),
                 unlink: list[int] | tuple[int, ...] = (),
                 attributes: dict | None = None) -> bool:
    """Create-or-update a Brevo contact and (un)link lists. Returns True on a 2xx.

    Idempotent via updateEnabled, so re-adding a known contact just updates their list membership.
    """
    email = (email or "").strip().lower()
    if not configured() or "@" not in email:
        return False
    body: dict = {"email": email, "updateEnabled": True}
    if list_ids:
        body["listIds"] = [int(x) for x in list_ids]
    if unlink:
        body["unlinkListIds"] = [int(x) for x in unlink]
    if attributes:
        body["attributes"] = attributes
    status = _call(body)
    return 200 <= status < 300


def add_demo_lead(email: str, attributes: dict | None = None) -> bool:
    """Someone asked for a demo -> add to the Demo list (starts the demo-nurture automation)."""
    return sync_contact(email, list_ids=[_demo_list()], attributes=attributes)


def add_client(email: str, attributes: dict | None = None) -> bool:
    """A tenant onboarded -> add to the Clients list, unlink Demo (stop the demo drip)."""
    return sync_contact(email, list_ids=[_clients_list()], unlink=[_demo_list()],
                        attributes=attributes)
