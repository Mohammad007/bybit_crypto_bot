from execution import Order, PaperBroker


def test_paper_lifecycle():
    pb = PaperBroker()
    assert pb.connect()
    p = pb.get_price("BTCUSDT")
    assert "bid" in p and "ask" in p and p["ask"] > p["bid"]

    df = pb.get_history("BTCUSDT", "M15", 100)
    assert len(df) == 100 and {"open", "high", "low", "close"}.issubset(df.columns)

    mid = p["mid"]
    o = Order(side="BUY", symbol="BTCUSDT", lot=0.01,
              sl=mid * 0.99, tp=mid * 1.02)
    pos = pb.place_order(o)
    assert pos is not None and pos.side == "BUY"
    assert pb.open_positions()
    assert pb.close_position(pos.ticket)
    assert not pb.open_positions()
