"""The employer-alias table: loader validation and its effect on company matching.

The table is generated offline by scripts/build_employer_aliases.py and reviewed as a git diff, so
these tests cover the second line of defence — the rules the loader re-applies at read time, which
must hold even for a hand-edited or badly generated row. The property being defended is that an
alias can only ever help an employer that is ALREADY in the reference list to match itself; it can
never introduce an organisation, and it can never over-match free text.
"""
import pytest

from scoring.signals.work_email import (employer_names, load_aliases, match_company)

# The canonical employers a test table is allowed to refer to, keyed by the normalised form of
# their own label — the shape employer_names() passes in.
CANON = {"GOLDMAN SACHS": "Goldman Sachs", "JPMORGAN CHASE": "JPMorgan Chase",
         "ROTHSCHILD CO": "Rothschild & Co"}


@pytest.fixture()
def table(tmp_path):
    def _write(text: str):
        p = tmp_path / "employer_aliases.csv"
        p.write_text(text, encoding="utf-8")
        return p
    return _write


# ── what a good row does ──────────────────────────────────────────────────────
def test_a_valid_alias_is_loaded(table):
    path = table("alias,canonical\nJ P Morgan,JPMorgan Chase\n")
    assert load_aliases(path, CANON) == [("J P MORGAN", "JPMorgan Chase")]


def test_comments_blanks_and_the_header_are_skipped(table):
    path = table("# a comment\n\nalias,canonical\nJ P Morgan,JPMorgan Chase\n\n# another\n")
    assert load_aliases(path, CANON) == [("J P MORGAN", "JPMorgan Chase")]


def test_the_reference_lists_own_label_wins(table):
    """The table may spell the canonical loosely; the reason must still read as the reference
    list writes it, never as the alias file does."""
    path = table("alias,canonical\nJ P Morgan,JPMORGAN  CHASE\n")
    assert load_aliases(path, CANON)[0][1] == "JPMorgan Chase"


def test_aliases_are_returned_longest_first(table):
    path = table("alias,canonical\nJ P Morgan,JPMorgan Chase\n"
                 "Goldman Sachs International,Goldman Sachs\n")
    assert [a for a, _c in load_aliases(path, CANON)][0] == "GOLDMAN SACHS INTERNATIONAL"


# ── what a bad row cannot do ──────────────────────────────────────────────────
def test_an_unknown_employer_is_never_introduced(table):
    """The single most important rule: the alias table cannot add an organisation the domain
    list does not already have."""
    path = table("alias,canonical\nSome Hedge Fund LLP,Some Hedge Fund\n")
    assert load_aliases(path, CANON) == []


def test_a_generic_alias_cannot_over_match(table):
    """A canonical name may be a single 5+ character word, because the domain list is curated by
    hand. A generated alias may not be one that names an industry rather than a firm."""
    for junk in ("Capital", "Bank", "Group", "PLC", "AB",
                 "Capital Partners", "Private Wealth Management", "The Bank"):
        path = table(f"alias,canonical\n{junk},Goldman Sachs\n")
        assert load_aliases(path, CANON) == [], junk


def test_a_distinctive_token_alongside_generic_ones_is_kept(table):
    path = table("alias,canonical\nGoldman Sachs International,Goldman Sachs\n")
    assert load_aliases(path, CANON) == [("GOLDMAN SACHS INTERNATIONAL", "Goldman Sachs")]


def test_an_alias_claimed_by_two_employers_is_dropped_not_guessed(table):
    path = table("alias,canonical\nMorgan Bank,JPMorgan Chase\nMorgan Bank,Goldman Sachs\n")
    assert load_aliases(path, CANON) == []


def test_an_alias_that_is_already_a_canonical_name_adds_nothing(table):
    path = table("alias,canonical\nRothschild & Co,Goldman Sachs\n")
    assert load_aliases(path, CANON) == []


def test_malformed_rows_are_ignored(table):
    path = table("alias,canonical\n,\nJ P Morgan\n,Goldman Sachs\n   ,   \n")
    assert load_aliases(path, CANON) == []


def test_a_missing_table_is_normal(tmp_path):
    assert load_aliases(tmp_path / "nope.csv", CANON) == []


# ── the effect on matching ────────────────────────────────────────────────────
def _domains():
    return {"gs.com": ("Goldman Sachs", "bank"), "jpmorgan.com": ("JPMorgan Chase", "bank")}


def test_aliases_recover_a_match_that_normalisation_loses(table):
    """"J.P. Morgan" strips to the tokens J P MORGAN, which never equals JPMORGAN. This is the
    gap the offline table exists to close."""
    names_without = employer_names(_domains(), aliases_path=None)
    assert match_company("J.P. Morgan", names_without) == (False, None)

    path = table("alias,canonical\nJ P Morgan,JPMorgan Chase\n")
    hit, reason = match_company("J.P. Morgan", employer_names(_domains(), aliases_path=path))
    assert hit is True and "JPMorgan Chase" in reason


def test_an_alias_cannot_make_an_unrelated_company_match(table):
    path = table("alias,canonical\nJ P Morgan,JPMorgan Chase\n")
    names = employer_names(_domains(), aliases_path=path)
    assert match_company("Morgan Removals Ltd", names) == (False, None)
    assert match_company("A Corner Shop", names) == (False, None)


def test_canonical_matching_is_unaffected_when_no_table_exists():
    names = employer_names(_domains())          # the real (absent) table path
    assert match_company("Goldman Sachs", names)[0] is True
    assert match_company("Nothing Related", names) == (False, None)
