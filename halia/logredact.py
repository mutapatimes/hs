"""Nothing that looks like a person reaches a log line.

Installed on the root logger and on uvicorn's loggers at app start. It masks email addresses and
long digit runs (phone numbers, card-like strings) in every record's message and arguments, so a
stray exception trace, a debug line or a request log cannot carry a client's identity into the
host's log store. Halia's own access log already records only paths and hashed references; this
is the guard for everything else, including libraries.
"""
from __future__ import annotations

import logging
import re

_EMAIL = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_DIGITS = re.compile(r"(?<!\d)(\+?\d[\d\s-]{7,}\d)(?!\d)")


def redact(text: str) -> str:
    text = _EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", text)
    return _DIGITS.sub(lambda m: m.group(1)[:2] + "…" + m.group(1)[-2:], text)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: (redact(v) if isinstance(v, str) else v) for k, v in record.args.items()}
                else:
                    record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        except Exception:  # noqa: BLE001 — a filter must never break logging
            pass
        return True


_FILTER = RedactFilter()


def install() -> None:
    """Attach the filter to every logger that writes to the host: root, halia's, uvicorn's."""
    for name in ("", "halia", "halia.access", "uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        if _FILTER not in lg.filters:
            lg.addFilter(_FILTER)
        for h in lg.handlers:
            if _FILTER not in h.filters:
                h.addFilter(_FILTER)
