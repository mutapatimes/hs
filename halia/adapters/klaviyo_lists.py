"""Create a Klaviyo list from a chosen set of clients (Lists API).

Lets a merchant select customers in the Halia dashboard and spin up a Klaviyo list of them
in one click — "build a list from Shopify". We upsert each selected client (to get their
Klaviyo profile id), create a list, and add the profiles to it.

Needs the `lists:write` scope. Docs: https://developers.klaviyo.com/en/reference/create_list
"""
from __future__ import annotations

from halia.adapters.klaviyo_sink import DEFAULT_REVISION, KlaviyoError, KlaviyoSink

LISTS_URL = "https://a.klaviyo.com/api/lists"


def _post(url: str, api_key: str, revision: str, body: dict) -> tuple[int, dict]:
    import requests

    headers = {
        "Authorization": f"Klaviyo-API-Key {api_key}",
        "revision": revision,
        "accept": "application/json",
        "content-type": "application/json",
    }
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    try:
        return resp.status_code, (resp.json() if resp.content else {})
    except ValueError:
        return resp.status_code, {"raw": resp.text}


def create_list(api_key: str, name: str, revision: str = DEFAULT_REVISION, transport=None) -> str:
    status, payload = (transport or _post)(
        LISTS_URL, api_key, revision, {"data": {"type": "list", "attributes": {"name": name}}})
    if not (200 <= status < 300):
        raise KlaviyoError(f"create list HTTP {status}: {str(payload)[:200]}")
    return payload["data"]["id"]


def add_profiles(api_key: str, list_id: str, profile_ids: list[str],
                 revision: str = DEFAULT_REVISION, transport=None) -> None:
    if not profile_ids:
        return
    url = f"{LISTS_URL}/{list_id}/relationships/profiles"
    body = {"data": [{"type": "profile", "id": pid} for pid in profile_ids]}
    status, payload = (transport or _post)(url, api_key, revision, body)
    if not (200 <= status < 300):
        raise KlaviyoError(f"add to list HTTP {status}: {str(payload)[:200]}")


def list_from_results(api_key: str, name: str, results: list) -> dict:
    """Upsert each result (to get its profile id), create a list, add the profiles."""
    sink = KlaviyoSink(api_key=api_key)
    profile_ids = []
    for r in results:
        if not r.email:
            continue
        pid = (sink.push_one(r).get("data") or {}).get("id")
        if pid:
            profile_ids.append(pid)
    list_id = create_list(api_key, name)
    add_profiles(api_key, list_id, profile_ids)
    return {"list_id": list_id, "count": len(profile_ids),
            "url": f"https://www.klaviyo.com/list/{list_id}"}
