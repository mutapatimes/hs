"""Client pages on the store's own Shopify domain, through the app proxy Halia already has:
theirbrand.com/a/catalogue/i/<token> and theirbrand.com/a/catalogue/c/<slug>. Shopify signs every
proxied request; the token and slug are self-contained, so nothing else is needed."""
from __future__ import annotations

from typing import Any

from fastapi import Body, HTTPException, Request

from halia.api.shopify_auth import verify_app_proxy


def _gate(request: Request) -> None:
    if not verify_app_proxy(request):
        raise HTTPException(403, "Invalid proxy signature")


def register(app) -> None:
    from halia.api.appointments import render_invite
    from halia.api.capture import check_public, render_capture, submit_public

    @app.get("/proxy/catalogue/i/{token}", include_in_schema=False)
    def proxy_invite(token: str, request: Request):
        _gate(request)
        return render_invite(token)

    @app.get("/proxy/catalogue/c/{slug}", include_in_schema=False)
    def proxy_capture(slug: str, request: Request):
        _gate(request)
        return render_capture(slug)

    @app.post("/proxy/catalogue/c/{slug}", include_in_schema=False)
    def proxy_capture_submit(slug: str, request: Request, body: Any = Body(...)) -> dict:
        _gate(request)
        return submit_public(slug, body)

    @app.post("/proxy/catalogue/c/{slug}/check", include_in_schema=False)
    def proxy_capture_check(slug: str, request: Request, body: Any = Body(...)) -> dict:
        _gate(request)
        return check_public(slug, body)
