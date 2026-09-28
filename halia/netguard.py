"""Outbound requests to addresses a merchant or a visitor supplied.

The server fetches a handful of things from addresses it did not choose: a storefront to detect
its platform, a WooCommerce site to validate its keys, product and logo images for a catalogue
PDF. Each of those is a place where a crafted address could point the server at itself, at the
cloud metadata service, or at something on the private network. Every such fetch goes through
here: the scheme must be http(s), the host must resolve to a public address (checked again on
every redirect hop), and the body is read up to a fixed size.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

import requests


class UnsafeAddress(ValueError):
    """The address is not one the server may fetch."""


_BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata"}


def _public_ip(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast
                or a.is_reserved or a.is_unspecified or (a.version == 4 and a in ipaddress.ip_network("100.64.0.0/10")))


def assert_public(url: str) -> str:
    """Return the URL if it is a fetchable public http(s) address; raise UnsafeAddress otherwise."""
    parts = urlsplit(str(url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeAddress("Only public http(s) addresses can be fetched.")
    host = parts.hostname.lower().rstrip(".")
    if host in _BLOCKED_HOSTS or host.endswith((".localhost", ".internal", ".local")):
        raise UnsafeAddress("That address is not reachable from here.")
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise UnsafeAddress("That address does not resolve.")
    ips = {info[4][0] for info in infos}
    if not ips or not all(_public_ip(ip) for ip in ips):
        raise UnsafeAddress("That address is not reachable from here.")
    return url


def safe_get(url: str, *, max_bytes: int = 4 * 1024 * 1024, timeout: float = 10.0,
             headers: dict | None = None, max_redirects: int = 5, **kwargs) -> requests.Response:
    """GET a public address, re-checking every redirect target, and stop reading at max_bytes.
    The returned response has ``.content`` and ``.text`` filled up to the cap."""
    hops = 0
    current = assert_public(url)
    while True:
        resp = requests.get(current, timeout=timeout, headers=headers, allow_redirects=False,
                            stream=True, **kwargs)
        if resp.is_redirect or resp.is_permanent_redirect:
            resp.close()
            hops += 1
            if hops > max_redirects or not resp.headers.get("location"):
                raise UnsafeAddress("Too many redirects.")
            current = assert_public(requests.compat.urljoin(current, resp.headers["location"]))
            continue
        chunks, size = [], 0
        for chunk in resp.iter_content(64 * 1024):
            chunks.append(chunk)
            size += len(chunk)
            if size >= max_bytes:
                break
        resp.close()
        resp._content = b"".join(chunks)[:max_bytes]   # noqa: SLF001 — requests' own cache slot
        resp._content_consumed = True                   # noqa: SLF001
        return resp
