DEFAULT_ETFS: tuple[str, ...] = (
    "SPY", "QQQ", "IWM", "DIA", "VTI",
    "XLF", "XLK", "XLE", "XLV", "XLI",
    "XLY", "XLP", "XLU", "XLB", "XLRE",
    "SMH", "ARKK", "TLT", "GLD", "SLV",
)

DEFAULT_LARGE_CAPS: tuple[str, ...] = (
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
    "META", "TSLA", "AVGO", "BRK-B", "JPM",
    "V", "UNH", "XOM", "MA", "JNJ",
    "PG", "HD", "COST", "ABBV", "LLY",
)


def default_universe() -> list[str]:
    return list(DEFAULT_ETFS + DEFAULT_LARGE_CAPS)
