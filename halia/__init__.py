"""Halia application layer — the wrapper around the scoring brain.

`scoring/` is the tool-agnostic scoring engine (the brain). This package is the
*application*: one consistent way to ask "what's this client's score, and why"
(`halia.engine` + `halia.api`), a place to persist scores (`halia.store`), and the
adapter seams that let any platform feed customers in (`CustomerSource`) and receive
the score back (`ScoreSink`) — see `halia.ports`.

The brain is wired to be multi-surface from day one; surfaces are lit one at a time.
"""
