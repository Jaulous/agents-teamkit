"""Error types shared by TeamKit modules."""

from __future__ import annotations


class TeamKitError(Exception):
    """A user-facing error. The CLI prints the message and exits with code 2."""
