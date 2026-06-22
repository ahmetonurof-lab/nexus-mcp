INITIAL_CAPITAL = 10000.0
RISK_PER_TRADE = 0.01
SL_ATR_MULT = 1.5
TP_RR = 2.0
FVG_BUFFER_MULT = 0.25

COINS: dict[str, dict] = {
    "BTCUSDT": {"min_fvg_size": 10.0},
    "ETHUSDT": {"min_fvg_size": 1.5},
    "BNBUSDT": {"min_fvg_size": 0.8},
    "SOLUSDT": {"min_fvg_size": 0.14},
    "AVAXUSDT": {"min_fvg_size": 0.01},
    "LINKUSDT": {"min_fvg_size": 0.01},
    "XRPUSDT": {"min_fvg_size": 0.002},
    "ATOMUSDT": {"min_fvg_size": 0.005},
    "ADAUSDT": {"min_fvg_size": 0.0003},
    "SUIUSDT": {"min_fvg_size": 0.001},
    "APTUSDT": {"min_fvg_size": 0.003},
    "DOTUSDT": {"min_fvg_size": 0.003},
    "NEARUSDT": {"min_fvg_size": 0.001},
}


def get_config(symbol: str) -> dict:
    base = {
        "initial_capital": INITIAL_CAPITAL,
        "risk_per_trade": RISK_PER_TRADE,
        "sl_atr_mult": SL_ATR_MULT,
        "tp_rr": TP_RR,
        "fvg_buffer_mult": FVG_BUFFER_MULT,
    }
    coin = COINS.get(symbol.upper())
    if coin is None:
        raise ValueError(f"Unknown symbol: {symbol}. Available: {list(COINS.keys())}")
    base.update(coin)
    base["symbol"] = symbol.upper()
    return base
