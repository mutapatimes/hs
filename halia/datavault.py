"""Where real customer data may live, and what may be built from it.

The rules, enforced in code rather than remembered:

1. A real export never lives inside the repository. It lives in the vault, a directory outside
   the checkout (``HALIA_REAL_DATA_DIR``, default ``~/HaliaVault``), readable by this user only.
   ``sample_data/`` inside the repo holds synthetic files and nothing else.
2. Anything written to a public place (``web/``, ``docs/``) may only be built from a synthetic
   file. ``public_safe_source`` refuses everything else, by name, before a byte is read.
3. Every script that scores a real export resolves it through ``real_source`` so the path is
   the vault's, and a real file dropped into the repo by mistake is refused, not scored.
4. Text with the tells of a real consumer export cannot be committed (pre-commit hook), cannot
   pass CI (test), and cannot be served (the app refuses to start; ``assert_public_tree_clean``).

See docs/data-handling-policy.md.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC_PREFIX = "synthetic_"
PUBLIC_DIRS = ("web", "docs")
TEXT_SUFFIXES = {".html", ".htm", ".md", ".txt", ".csv", ".json", ".js", ".py", ".swift", ".xml",
                 ".yml", ".yaml"}
EXEMPT_PREFIXES = ("tests/", "sample_data/README.md")

# The tells of a real consumer export, which synthetic data never carries: email addresses with
# a purely numeric local part, and free-mail domains the synthetic generator does not write.
_NUMERIC_LOCAL = re.compile(r"(?<![\w.])\d{5,}@[A-Za-z0-9.-]+\.[a-z]{2,}")
_CONSUMER_DOMAINS = re.compile(r"[A-Za-z0-9._%+-]+@(qq|163|126|sina|foxmail|yeah)\.(com|net)")


class RealDataOutsideVault(RuntimeError):
    """A real export was found, or asked for, somewhere other than the vault."""


class NotSyntheticSource(RuntimeError):
    """A public artefact was about to be built from something other than a synthetic file."""


# ── the vault ──────────────────────────────────────────────────────────────────────

def vault_dir() -> Path:
    return Path(os.environ.get("HALIA_REAL_DATA_DIR") or "~/HaliaVault").expanduser()


def is_synthetic(path: Path | str) -> bool:
    return Path(path).name.lower().startswith(SYNTHETIC_PREFIX)


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT)
        return True
    except ValueError:
        return False


def real_source(name_or_path: str | Path) -> Path:
    """Resolve a real export by name to its vault copy. A bare name looks in the vault; a path
    inside the repository is refused unless it is synthetic; a path elsewhere is used as given."""
    p = Path(name_or_path).expanduser()
    if is_synthetic(p):
        return p if p.exists() else ROOT / "sample_data" / p.name
    if p.parent == Path(".") or not p.is_absolute() and not p.exists():
        candidate = vault_dir() / p.name
        if candidate.exists():
            return candidate
    if _inside_repo(p):
        raise RealDataOutsideVault(
            f"{p} is inside the repository. Real exports live only in the vault "
            f"({vault_dir()}); move the file there and pass its name.")
    if not p.exists():
        raise FileNotFoundError(f"{p} not found; the vault is {vault_dir()}")
    return p


def public_safe_source(path: str | Path) -> Path:
    """The only kind of file a public page may be built from."""
    p = Path(path)
    if not is_synthetic(p):
        raise NotSyntheticSource(
            f"Refusing to build a public page from {p.name}: anything under {PUBLIC_DIRS} is "
            f"built from a file named {SYNTHETIC_PREFIX}*.xlsx and nothing else.")
    return p


def resolve_data_path(path: str | Path) -> Path:
    """For the generic loader: synthetic files pass; a real file inside the repo is refused; a
    missing repo path whose name exists in the vault is redirected there."""
    p = Path(path)
    if is_synthetic(p):
        return p
    if _inside_repo(p):
        vaulted = vault_dir() / p.name
        if vaulted.exists():
            return vaulted
        if p.exists():
            raise RealDataOutsideVault(
                f"{p} looks like a real export inside the repository. Move it to {vault_dir()} "
                f"(mv '{p}' '{vault_dir()}/') and run again; the loader will find it there.")
    return p


# ── the scanner ────────────────────────────────────────────────────────────────────

def scan_text(text: str) -> list[str]:
    """Human-readable problems found in one text, empty when clean."""
    out = []
    numeric = set(_NUMERIC_LOCAL.findall(text))
    if numeric:
        sample = sorted(numeric)[0]
        out.append(f"{len(numeric)} email address(es) with a numeric local part, e.g. {sample[:2]}***@{sample.split('@')[1]}")
    cn = set(_CONSUMER_DOMAINS.findall(text))
    if cn:
        out.append(f"{len(cn)} address(es) at a domain synthetic data never uses")
    return out


def scan_file(path: Path) -> list[str]:
    rel = str(path.relative_to(ROOT)) if path.is_absolute() and _inside_repo(path) else str(path)
    if rel.startswith(EXEMPT_PREFIXES) or path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return [f"{rel}: {p}" for p in scan_text(text)]


def scan_tree(dirs=("web", "docs", "halia", "scripts", "extension", "ios", "wordpress")) -> list[str]:
    problems: list[str] = []
    for d in dirs:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if any(part in ("node_modules", "build", ".venv") for part in p.parts):
                continue
            problems += scan_file(p)
    return problems


def assert_public_tree_clean() -> None:
    """Called when the app starts: refuse to serve if anything public carries a real export.
    Failing closed here is the point; a leak must never survive a deploy."""
    problems = scan_tree(PUBLIC_DIRS)
    if problems:
        raise RuntimeError("Refusing to start: real customer data in a public file.\n" + "\n".join(problems))
