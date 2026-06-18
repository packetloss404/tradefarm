"""Exact money arithmetic helpers.

Floats accumulate drift over thousands of fills, and the old
``abs(x) < 1e-9`` epsilon guards could misclassify a genuinely-flat
position. Money is held internally as :class:`~decimal.Decimal` so cash,
realized P&L, average price and quantities are exact.

Boundaries matter:
  - Market data (marks/prices) arrives as ``float``. Coerce it to Decimal
    with :func:`D` at the book boundary.
  - JSON/WS payloads and FastAPI responses must emit JSON numbers, so
    convert Decimal back to ``float`` with :func:`to_float` at every output
    boundary (``json.dumps`` cannot serialise a Decimal).

Quantization:
  - Cash / P&L / equity quantize to a sub-cent (4 dp) — fine enough to keep
    a cent exact while not throwing away fractional-share precision.
  - Quantities quantize to the existing 4 dp the agents already round to.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

# Sub-cent money grid. Keeping 4 dp (rather than 2) preserves precision for
# fractional-share notionals while remaining exact at the cent.
MONEY_QUANT = Decimal("0.0001")
# Quantities quantize to 4 dp — matches the `round(qty, 4)` the agents use.
QTY_QUANT = Decimal("0.0001")

ZERO = Decimal("0")


def D(x: object) -> Decimal:
    """Coerce a value to :class:`Decimal` losslessly.

    ``float`` is routed through ``str`` so the Decimal reflects the printed
    value (e.g. ``0.1``) rather than the binary-float artefact
    (``0.1000000000000000055…``). ``Decimal``/``int``/``str`` pass straight
    through.
    """
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(x)  # type: ignore[arg-type]


def quantize_money(x: Decimal) -> Decimal:
    """Round a money value to the sub-cent grid (banker's rounding)."""
    return x.quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN)


def quantize_qty(x: Decimal) -> Decimal:
    """Round a share quantity to 4 dp (banker's rounding)."""
    return x.quantize(QTY_QUANT, rounding=ROUND_HALF_EVEN)


def to_float(x: object) -> float:
    """Convert a Decimal (or any numeric) to ``float`` for a JSON/WS/REST
    output boundary. ``None`` passes through unchanged."""
    if x is None:
        return x  # type: ignore[return-value]
    return float(x)  # type: ignore[arg-type]
