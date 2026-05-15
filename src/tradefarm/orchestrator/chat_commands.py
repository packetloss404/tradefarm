"""Pure-function parser for audience chat commands.

A command:
- MUST start with a literal ``!`` (no leading whitespace).
- Has a single command word, case-insensitive, immediately after the ``!``.
- May be followed by a single space and an argument string (which is trimmed).

Anything that doesn't begin with ``!`` returns ``None`` (it's a plain chat
message — not a command). Anything that starts with ``!`` but doesn't match
a known shape returns :class:`UnknownCommand` (the caller decides how to react,
e.g. log it).

The discriminated-union return type uses plain ``dataclasses`` + ``Literal``
field types — no pydantic — matching the codebase's "event payloads are plain
dicts" convention.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union


@dataclass(frozen=True)
class VoteCommand:
    """``!vote up`` or ``!vote down`` — sentiment ticker."""

    direction: Literal["up", "down"]


@dataclass(frozen=True)
class PinCommand:
    """``!pin <agent>`` — operator-approved spotlight request."""

    agent_query: str


@dataclass(frozen=True)
class PickCommand:
    """``!pick <agent>`` — prediction: today's winner."""

    agent_query: str


@dataclass(frozen=True)
class SpyCommand:
    """``!spy up|down`` — prediction: SPY close direction."""

    direction: Literal["up", "down"]


@dataclass(frozen=True)
class UnknownCommand:
    """Starts with ``!`` but doesn't match any known command."""


Command = Union[VoteCommand, PinCommand, PickCommand, SpyCommand, UnknownCommand]


def parse_command(text: str) -> Command | None:
    """Parse a single chat-message string.

    Returns ``None`` when the message isn't a command (doesn't start with
    ``!``). Returns :class:`UnknownCommand` when it starts with ``!`` but
    doesn't match any of the four supported shapes (or when args are
    malformed for an otherwise-known command word).
    """
    if not isinstance(text, str):
        return None
    if not text.startswith("!"):
        return None
    # Strip the leading "!" and split off the command word.
    body = text[1:]
    # Split on the FIRST whitespace run — args may contain spaces.
    parts = body.split(maxsplit=1)
    if not parts:
        return UnknownCommand()
    word = parts[0].lower()
    args = parts[1].strip() if len(parts) == 2 else ""

    if word == "vote":
        if args.lower() == "up":
            return VoteCommand(direction="up")
        if args.lower() == "down":
            return VoteCommand(direction="down")
        return UnknownCommand()

    if word == "spy":
        if args.lower() == "up":
            return SpyCommand(direction="up")
        if args.lower() == "down":
            return SpyCommand(direction="down")
        return UnknownCommand()

    if word == "pin":
        if not args:
            return UnknownCommand()
        return PinCommand(agent_query=args)

    if word == "pick":
        if not args:
            return UnknownCommand()
        return PickCommand(agent_query=args)

    return UnknownCommand()
