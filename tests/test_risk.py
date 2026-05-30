from risk_management import compute_qty, compute_lot_size


def test_qty_sizing():
    # $1000 account, 1% risk = $10. Stop distance on BTC = $500.
    # qty = 10 / 500 = 0.02 BTC.
    qty = compute_qty(capital=1000, risk_pct=1.0, entry_price=50000, stop_price=49500)
    assert abs(qty - 0.02) < 1e-9


def test_qty_scales_with_price():
    # Same $ risk, tiny-priced coin → large qty (percentage stop keeps risk constant).
    qty = compute_qty(capital=1000, risk_pct=1.0, entry_price=0.40, stop_price=0.396)
    # risk $10 / distance 0.004 = 2500 coins
    assert abs(qty - 2500.0) < 1e-6


def test_zero_distance():
    assert compute_qty(1000, 1.0, 50000, 50000) == 0.0
    assert compute_lot_size(1000, 1.0, 50000, 50000, contract_size=1) == 0.0


def test_lot_size_linear_contract():
    # contract_size=1 (linear perp) → same result as compute_qty
    lot = compute_lot_size(1000, 1.0, 50000, 49500, contract_size=1)
    assert abs(lot - 0.02) < 1e-9
