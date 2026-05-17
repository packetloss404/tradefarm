from tradefarm.agents.names import _FIRSTS, _LASTS, agent_display_name


def test_first_100_full_names_unique() -> None:
    names = {agent_display_name(i) for i in range(100)}
    assert len(names) == 100


def test_first_names_all_unique() -> None:
    assert len(set(_FIRSTS)) == len(_FIRSTS) == 100


def test_last_names_all_unique() -> None:
    assert len(set(_LASTS)) == len(_LASTS) == 100


def test_deterministic() -> None:
    assert agent_display_name(0) == agent_display_name(0)
    assert agent_display_name(42) == agent_display_name(42)


def test_format_is_two_lowercase_segments() -> None:
    for i in (0, 1, 14, 15, 50, 99):
        name = agent_display_name(i)
        assert name == name.lower()
        parts = name.split("_")
        assert len(parts) == 2, name


def test_fits_db_column() -> None:
    for i in range(100):
        assert len(agent_display_name(i)) <= 64


def test_overflow_falls_back() -> None:
    assert agent_display_name(100) == "trader_100"
    assert agent_display_name(250) == "trader_250"
