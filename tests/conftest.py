"""Shared fixtures."""
import pytest


@pytest.fixture(autouse=True)
def _fresh_caller_ceilings():
    """The per-caller ceilings on the extension endpoints live in process memory; each test
    starts with nobody counted."""
    from halia.api import extension
    extension._EXT_HITS.clear()
    yield
    extension._EXT_HITS.clear()
