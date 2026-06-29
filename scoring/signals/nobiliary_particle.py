"""Nobiliary-particle signal — DELIBERATELY WEAK, corroboration-only.

============================ SENSITIVE SIGNAL ============================
Detects an aristocratic name particle ("particule") in a customer's name —
French "de / du / des / de la", German "von / vom / zu / von und zu", etc.
(reference_data/names/nobiliary_particles.csv). These genuinely correlate with
old-money / aristocratic lineage ("Côme de Bouchony", "von und zu Liechtenstein").

BUT bare particles are also national-origin / language markers: "de la" (Hispanic),
"van" (Dutch), "dos/das" (Portuguese) are borne by vast numbers of ordinary-status
people. Detecting them as "wealth" on their own would systematically mis-score
customers by origin (disparate impact). That is exactly why name_structure.py
excludes particle lists — and why THIS signal is:
  - WEIGHTED AT THE FLOOR (SIGNAL_WEIGHTS["nobiliary_particle"] = 1), and
  - CORROBORATION-ONLY (see SUPPORTING_SIGNALS in combine.py): it is counted ONLY
    when a STRONGER, non-supporting signal has already fired. It can NEVER surface,
    grade, or action a client by itself — it only re-ranks already-flagged clients.
The reference list ships with the higher-signal French/German particles and leaves
the noisiest origin markers (van, di, dos, ...) out by default. Set the weight to 0
to switch the signal off entirely.
=========================================================================
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

import pandas as pd

from config import NOBILIARY_PARTICLES_FILE

FLAG_COL = "nobiliary_particle"
REASON_COL = "nobiliary_particle_reason"


def _reason(particle: str) -> str:
    return f'nobiliary particle "{particle}" — weak heritage-wealth marker (corroborating only)'


def load_particles(path: Path | str = NOBILIARY_PARTICLES_FILE):
    """Read particles → (singles set, multiword token-tuples longest-first)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Nobiliary-particle reference not found: {path}")
    singles: set[str] = set()
    multi: list[tuple[str, ...]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            raw = row[0].strip().lower()
            if not raw or raw.startswith("#") or raw == "particle":
                continue
            toks = raw.split()
            if len(toks) == 1:
                singles.add(toks[0])
            else:
                multi.append(tuple(toks))
    multi.sort(key=len, reverse=True)
    return singles, multi


def _tokens(name: object) -> list[str]:
    """Accent-folded, lower-cased name tokens, dropping single-letter initials."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return []
    folded = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^A-Za-z'\- ]+", " ", folded).lower().strip()
    return [t for t in cleaned.split() if len(t.strip(".'-")) > 1]


def detect_particle(name: object, singles=None, multi=None):
    """Return (matched, reason). Needs a particle AND a following surname token."""
    if singles is None or multi is None:
        singles, multi = load_particles()
    toks = _tokens(name)
    if len(toks) < 2:
        return False, None
    # Multi-word particles first (more specific, e.g. "von und zu").
    for mw in multi:
        span = len(mw)
        for i in range(len(toks) - span + 1):
            if tuple(toks[i:i + span]) == mw and len(toks) > span:
                return True, _reason(" ".join(mw))
    # Single particles — require at least one non-particle token (the surname).
    for i, tok in enumerate(toks):
        if tok in singles and any(o not in singles for j, o in enumerate(toks) if j != i):
            return True, _reason(tok)
    return False, None


def flag_nobiliary_particle(df: pd.DataFrame, particles=None, name_col: str = "Name"):
    """Add the (weak, corroborating) nobiliary-particle flag + reason columns."""
    if particles is None:
        particles = load_particles()
    singles, multi = particles
    out = df.copy()
    if name_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[name_col].apply(lambda n: detect_particle(n, singles, multi))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
