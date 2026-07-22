"""The delivery-venue alias guard (scoring/signals/delivery_venue.usable_alias).

The reference file has always warned that an alias must be "SPECIFIC enough not to collide with
streets/buildings" — good: "MANDARIN ORIENTAL", bad: "MANDARIN" (reaches Mandarin Plaza) — but
until now nothing enforced it, so a single careless row could fire the signal on every ordinary
address in a book. These tests hold that line from both directions: the guard must block the
collision-prone shapes AND must not quietly drop anything already shipped.
"""
import csv

import pytest

from config import SIGNAL_VENUES_FILE
from scoring.signals.delivery_venue import _normalize, load_venues, usable_alias


# ── what the guard blocks ─────────────────────────────────────────────────────
@pytest.mark.parametrize("alias", [
    "MANDARIN",        # the reference file's own worked example: reaches Mandarin Plaza
    "SAVOY", "RITZ", "PENINSULA", "DORCHESTER", "BERKELEY",   # collide alone, fine in a phrase
])
def test_a_venue_word_that_collides_alone_is_blocked(alias):
    assert usable_alias(alias) is False


@pytest.mark.parametrize("alias", ["HOTEL", "PLAZA", "TOWER", "COURT", "APARTMENT"])
def test_a_kind_of_place_is_never_an_alias(alias):
    assert usable_alias(alias) is False


@pytest.mark.parametrize("alias", ["THE PARK", "GRAND HOTEL", "PARK LANE", "ROYAL COURT"])
def test_two_ordinary_words_do_not_name_a_venue(alias):
    assert usable_alias(alias) is False


@pytest.mark.parametrize("alias", ["OSWALD", "ANNABE", "CLARID", "SAVO", "EDEN"])
def test_a_short_single_word_is_blocked(alias):
    """Under seven characters a lone word is too likely to appear inside another name.
    Seven is the floor because the shortest alias the reference list actually ships
    ("OSWALDS") is seven, so the guard must not reach past it."""
    assert len(alias) < 7 and usable_alias(alias) is False


def test_an_empty_alias_is_blocked():
    assert usable_alias("") is False and usable_alias("   ") is False


# ── what the guard keeps ──────────────────────────────────────────────────────
@pytest.mark.parametrize("alias", [
    "MANDARIN ORIENTAL",     # the file's own example of a good alias
    "FOUR SEASONS", "ANNABELS", "LANESBOROUGH", "SUPERYACHT", "CLARIDGE", "TETERBORO",
])
def test_a_distinctive_alias_is_kept(alias):
    assert usable_alias(alias) is True


def test_three_ordinary_words_are_specific_enough_together():
    """Every word in "Royal Garden Hotel" is ordinary, but the phrase is a real hotel and
    matches nothing else. Specificity comes from length as well as from wording."""
    assert usable_alias("ROYAL GARDEN HOTEL") is True


# ── the shipped reference data ────────────────────────────────────────────────
def test_the_guard_drops_nothing_currently_shipped():
    """A guard that silently discards curated rows would weaken the engine while looking tidy."""
    dropped = []
    with SIGNAL_VENUES_FILE.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            name = row[0].strip() if row else ""
            if not name or name.startswith("#") or name == "venue":
                continue
            for part in (row[2] if len(row) > 2 else "").split(";"):
                norm = _normalize(part)
                if norm and not usable_alias(norm):
                    dropped.append(f"{norm!r} ({name})")
    assert dropped == []


def test_the_reference_list_still_loads_every_venue():
    venues = load_venues(alias_guard=usable_alias)
    assert len(venues) >= 100
    assert all(v.aliases for v in venues)
    assert all(usable_alias(a) for v in venues for a in v.aliases)


def test_the_guard_is_opt_in_so_shared_tables_keep_short_place_names():
    """This loader is shared with the area, prime-residence and district lists, where names like
    "Gstaad" and "Davos" are legitimately short. Applying the venue guard to those would silently
    delete real places, so only the venue caller opts in."""
    from config import HNW_AREAS_FILE
    areas = load_venues(HNW_AREAS_FILE)                       # no guard: the default
    short = [a for v in areas for a in v.aliases if len(a.split()) == 1 and len(a) < 7]
    assert short, "expected the areas list to contain short place names"
    guarded = load_venues(HNW_AREAS_FILE, alias_guard=usable_alias)
    assert sum(len(v.aliases) for v in guarded) < sum(len(v.aliases) for v in areas)
