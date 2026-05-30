"""Position sizing helpers."""
from __future__ import annotations


def compute_qty(
    capital: float,
    risk_pct: float,
    entry_price: float,
    stop_price: float,
) -> float:
    """
    Risk-based size for a Bybit linear USDT perpetual.

    For linear USDT perps 1 contract = 1 coin, so PnL = qty * price_change.
    To risk ``risk_pct`` of ``capital`` over the stop distance:

        risk_amount = capital * risk_pct/100
        qty         = risk_amount / |entry - stop|

    The result is the RAW coin quantity – the broker rounds it to the
    instrument's qtyStep and clamps to minOrderQty / maxOrderQty.
    """
    if entry_price <= 0 or stop_price <= 0:
        return 0.0
    distance = abs(entry_price - stop_price)
    if distance <= 0:
        return 0.0
    risk_amount = capital * (risk_pct / 100.0)
    return risk_amount / distance


def compute_lot_size(
    capital: float,
    risk_pct: float,
    entry_price: float,
    stop_price: float,
    contract_size: float = 1.0,
    min_lot: float = 0.0,
    max_lot: float = 1e12,
    price_to_account_fx: float = 1.0,
) -> float:
    """
    Generic risk-based size (kept for compatibility / paper broker).

    ``contract_size`` units per contract; for linear USDT perps this is 1.
    Returns a quantity clamped to [min_lot, max_lot].
    """
    if entry_price <= 0 or stop_price <= 0:
        return 0.0
    distance = abs(entry_price - stop_price)
    if distance == 0:
        return 0.0
    risk_amount = capital * (risk_pct / 100.0)
    value_per_unit = contract_size * price_to_account_fx
    loss_per_unit = distance * value_per_unit
    if loss_per_unit <= 0:
        return 0.0
    qty = risk_amount / loss_per_unit
    return max(min_lot, min(max_lot, qty))
