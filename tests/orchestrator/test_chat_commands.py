"""parse_command — happy paths + malformed inputs."""
from __future__ import annotations

from tradefarm.orchestrator.chat_commands import (
    PickCommand,
    PinCommand,
    SpyCommand,
    UnknownCommand,
    VoteCommand,
    parse_command,
)


# ---------------------------------------------------------------------------
# Non-command messages.
# ---------------------------------------------------------------------------


def test_plain_text_returns_none():
    assert parse_command("hello world") is None
    assert parse_command("") is None
    assert parse_command("   ") is None


def test_leading_whitespace_is_not_a_command():
    # Must start with ``!`` — leading space disqualifies it.
    assert parse_command(" !vote up") is None


def test_non_string_returns_none():
    # Robust against junk payloads.
    assert parse_command(123) is None  # type: ignore[arg-type]
    assert parse_command(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Vote.
# ---------------------------------------------------------------------------


def test_vote_up():
    cmd = parse_command("!vote up")
    assert cmd == VoteCommand(direction="up")


def test_vote_down():
    cmd = parse_command("!vote down")
    assert cmd == VoteCommand(direction="down")


def test_vote_case_insensitive_command():
    cmd = parse_command("!VOTE up")
    assert cmd == VoteCommand(direction="up")


def test_vote_case_insensitive_args():
    cmd = parse_command("!vote UP")
    assert cmd == VoteCommand(direction="up")


def test_vote_extra_whitespace_trimmed():
    cmd = parse_command("!vote   down   ")
    assert cmd == VoteCommand(direction="down")


def test_vote_bad_direction_is_unknown():
    assert parse_command("!vote sideways") == UnknownCommand()
    assert parse_command("!vote") == UnknownCommand()


# ---------------------------------------------------------------------------
# SPY.
# ---------------------------------------------------------------------------


def test_spy_up():
    assert parse_command("!spy up") == SpyCommand(direction="up")


def test_spy_down():
    assert parse_command("!spy down") == SpyCommand(direction="down")


def test_spy_case_insensitive():
    assert parse_command("!SPY DOWN") == SpyCommand(direction="down")


def test_spy_bad_direction():
    assert parse_command("!spy sideways") == UnknownCommand()
    assert parse_command("!spy") == UnknownCommand()


# ---------------------------------------------------------------------------
# Pin.
# ---------------------------------------------------------------------------


def test_pin_by_id():
    assert parse_command("!pin 42") == PinCommand(agent_query="42")


def test_pin_by_name():
    assert parse_command("!pin agent-007") == PinCommand(agent_query="agent-007")


def test_pin_multiword_name():
    assert parse_command("!pin smart trader") == PinCommand(agent_query="smart trader")


def test_pin_trims_whitespace():
    assert parse_command("!pin   42   ") == PinCommand(agent_query="42")


def test_pin_empty_is_unknown():
    assert parse_command("!pin") == UnknownCommand()
    assert parse_command("!pin   ") == UnknownCommand()


# ---------------------------------------------------------------------------
# Pick.
# ---------------------------------------------------------------------------


def test_pick_by_id():
    assert parse_command("!pick 13") == PickCommand(agent_query="13")


def test_pick_by_name():
    assert parse_command("!pick alpha") == PickCommand(agent_query="alpha")


def test_pick_empty_is_unknown():
    assert parse_command("!pick") == UnknownCommand()


# ---------------------------------------------------------------------------
# Unknown commands.
# ---------------------------------------------------------------------------


def test_unknown_command_word():
    assert parse_command("!yeet x") == UnknownCommand()


def test_bare_bang_is_unknown():
    # Just "!" with nothing after.
    assert parse_command("!") == UnknownCommand()


def test_bang_with_only_whitespace():
    assert parse_command("!   ") == UnknownCommand()
