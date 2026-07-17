"""The brand layer: one shared engine, more than one face.

Halia (the default) is the private-client intelligence product. Store Concierge is a
separate, cheaper clienteling product that runs on the very same codebase but never
exposes the wealth engine, only the friendly quick-wins (catalogues, win-back, notes,
appointment templates).

A brand is resolved from the request Host, so a single deployment serves both storefronts:
``haliascore.com`` -> halia, ``storeconcierge.app`` -> storeconcierge. Extra hostnames
(staging, preview, apex vs www) map in via the ``HALIA_BRAND_HOSTS`` /
``STORECONCIERGE_HOSTS`` env lists, comma-separated.

Features are named so the dashboard and app surface can gate on them later without
knowing about brands directly: ``brand.enables("scoring")``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Every capability the app can switch on. Store Concierge deliberately omits the wealth
# engine (scoring, signals, grades, the world map, the outreach pipeline) and keeps only
# the service quick-wins a small shop actually wants.
ALL_FEATURES = frozenset({
    "scoring", "signals", "map", "pipeline", "outreach",       # the Halia engine
    "catalogues", "winback", "notes", "templates",              # the clienteling quick-wins
})

_CLIENTELING_ONLY = frozenset({"catalogues", "winback", "notes", "templates"})


@dataclass(frozen=True)
class Brand:
    key: str
    name: str
    tagline: str
    landing: str                 # web/site/<landing>.html, served at this brand's root
    features: frozenset
    email_from_name: str
    hosts: tuple = ()            # extra hostnames that resolve to this brand

    def enables(self, feature: str) -> bool:
        return feature in self.features


def _hosts_env(key: str) -> tuple:
    return tuple(h.strip().lower() for h in os.environ.get(key, "").split(",") if h.strip())


HALIA = Brand(
    key="halia",
    name="Halia",
    tagline="Private client intelligence for luxury retail",
    landing="index",
    features=ALL_FEATURES,
    email_from_name="Halia",
    hosts=_hosts_env("HALIA_BRAND_HOSTS"),
)

STORECONCIERGE = Brand(
    key="storeconcierge",
    name="Store Concierge",
    tagline="Look after your best customers like a boutique",
    landing="storeconcierge",
    features=_CLIENTELING_ONLY,
    email_from_name="Store Concierge",
    hosts=_hosts_env("STORECONCIERGE_HOSTS"),
)

BRANDS = {b.key: b for b in (HALIA, STORECONCIERGE)}
DEFAULT = HALIA

# Built-in host-name tokens so resolution works before any env override is configured.
_BUILTIN_TOKENS = (("storeconcierge", STORECONCIERGE),)


def default_brand() -> Brand:
    return DEFAULT


def brand(key: str | None) -> Brand:
    """The brand for a stored key (tenant.brand), falling back to Halia."""
    return BRANDS.get((key or "").strip().lower(), DEFAULT)


def brand_for_host(host: str | None) -> Brand:
    """Resolve a brand from a request Host header. Port is stripped and case ignored.
    An explicit env host list wins, then a built-in name match, else Halia."""
    h = (host or "").split(":")[0].strip().lower()
    if not h:
        return DEFAULT
    for b in BRANDS.values():
        if h in b.hosts:
            return b
    for token, b in _BUILTIN_TOKENS:
        if token in h:
            return b
    return DEFAULT
