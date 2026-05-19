import os
from dotenv import load_dotenv

load_dotenv()

# ── API ───────────────────────────────────────────────────────────────────
API_KEY    = os.getenv("BYBIT_API_KEY", "")
API_SECRET = os.getenv("BYBIT_API_SECRET", "")
IS_TESTNET = os.getenv("IS_TESTNET", "True").lower() in ('true', '1', 't')

# ── Multi-Pair Settings ───────────────────────────────────────────────────
TOP_N_PAIRS            = int(os.getenv("TOP_N_PAIRS", "30"))
PAIR_REFRESH_SECONDS   = int(os.getenv("PAIR_REFRESH_SECONDS", "3600"))
CATEGORY               = os.getenv("CATEGORY", "linear")
SYMBOL                 = os.getenv("TRADING_SYMBOL", "BTCUSDT")

# ── Position Sizing ───────────────────────────────────────────────────────
POSITION_SIZE_USDT     = float(os.getenv("POSITION_SIZE_USDT", "200"))
LEVERAGE               = int(os.getenv("LEVERAGE", "5"))
MAX_OPEN_POSITIONS     = int(os.getenv("MAX_OPEN_POSITIONS", "8"))

# ─ Risk Management ───────────────────────────────────────────────────────
ATR_PERIOD             = int(os.getenv("ATR_PERIOD", "7"))
ATR_SL_MULTIPLIER      = float(os.getenv("ATR_SL_MULTIPLIER", "0.4"))
RISK_REWARD_RATIO      = float(os.getenv("RISK_REWARD_RATIO", "1.2"))
FALLBACK_SL_PCT        = float(os.getenv("FALLBACK_SL_PCT", "0.005"))
FALLBACK_TP_PCT        = float(os.getenv("FALLBACK_TP_PCT", "0.008"))

# ── Volatility Regime Thresholds ──────────────────────────────────────────
VOL_LOW_THRESHOLD      = float(os.getenv("VOL_LOW_THRESHOLD", "0.003"))
VOL_HIGH_THRESHOLD     = float(os.getenv("VOL_HIGH_THRESHOLD", "0.015"))

# ── Adaptive Position Sizing ──────────────────────────────────────────────
ADAPTIVE_SIZING_ENABLED = os.getenv("ADAPTIVE_SIZING_ENABLED", "True").lower() in ('true', '1', 't')
ADAPTIVE_LOOKBACK_TRADES = int(os.getenv("ADAPTIVE_LOOKBACK_TRADES", "5"))
MIN_POSITION_SIZE      = float(os.getenv("MIN_POSITION_SIZE", "100"))
MAX_POSITION_SIZE      = float(os.getenv("MAX_POSITION_SIZE", "250"))

# ── Strategy Thresholds ───────────────────────────────────────────────────
OBI_THRESHOLD          = float(os.getenv("OBI_THRESHOLD", "0.2"))
OBI_TOP_LEVELS         = int(os.getenv("OBI_TOP_LEVELS", "10"))
STOCH_RSI_OVERSOLD     = int(os.getenv("STOCH_RSI_OVERSOLD", "25"))
STOCH_RSI_OVERBOUGHT   = int(os.getenv("STOCH_RSI_OVERBOUGHT", "75"))

EMA_FAST_PERIOD        = int(os.getenv("EMA_FAST_PERIOD", "9"))
EMA_SLOW_PERIOD        = int(os.getenv("EMA_SLOW_PERIOD", "21"))

VOLUME_SPIKE_MULT      = float(os.getenv("VOLUME_SPIKE_MULT", "2.0"))
VOLUME_MA_PERIOD       = int(os.getenv("VOLUME_MA_PERIOD", "20"))

BB_PERIOD              = int(os.getenv("BB_PERIOD", "20"))
BB_STD                 = float(os.getenv("BB_STD", "2.0"))
BB_SQUEEZE_THRESHOLD   = float(os.getenv("BB_SQUEEZE_THRESHOLD", "0.02"))

ADX_PERIOD             = int(os.getenv("ADX_PERIOD", "14"))
ADX_TREND_THRESHOLD    = float(os.getenv("ADX_TREND_THRESHOLD", "25.0"))

# ── Multi-Timeframe ───────────────────────────────────────────────────────
PRIMARY_TIMEFRAME      = int(os.getenv("PRIMARY_TIMEFRAME", "1"))
CONFIRMATION_TIMEFRAME = int(os.getenv("CONFIRMATION_TIMEFRAME", "3"))

# ── Order Flow ────────────────────────────────────────────────────────────
ORDER_FLOW_ENABLED     = os.getenv("ORDER_FLOW_ENABLED", "True").lower() in ('true', '1', 't')
AGGRESSIVE_RATIO_THRESHOLD = float(os.getenv("AGGRESSIVE_RATIO_THRESHOLD", "1.3"))
LARGE_TRADE_PERCENTILE = float(os.getenv("LARGE_TRADE_PERCENTILE", "95"))

# ── Cooldown & Circuit Breaker ────────────────────────────────────────────
TRADE_COOLDOWN_SECONDS      = int(os.getenv("TRADE_COOLDOWN_SECONDS", "30"))
POST_LOSS_COOLDOWN_SECONDS  = int(os.getenv("POST_LOSS_COOLDOWN_SECONDS", "180"))
DAILY_LOSS_LIMIT_USDT       = float(os.getenv("DAILY_LOSS_LIMIT_USDT", "100.0"))
MAX_CONSECUTIVE_LOSSES      = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "5"))
CONSECUTIVE_LOSS_PAUSE      = int(os.getenv("CONSECUTIVE_LOSS_PAUSE", "300"))

# ── Kline Interval ────────────────────────────────────────────────────────
KLINE_INTERVAL         = int(os.getenv("KLINE_INTERVAL", "1"))

# ── WebSocket ─────────────────────────────────────────────────────────────
WS_URL = (
    "wss://stream-testnet.bybit.com/v5/public/linear"
    if IS_TESTNET else
    "wss://stream.bybit.com/v5/public/linear"
)
PRIVATE_WS_URL = (
    "wss://stream-testnet.bybit.com/v5/private"
    if IS_TESTNET else
    "wss://stream.bybit.com/v5/private"
)
PRIVATE_WS_URL = (
    "wss://stream-testnet.bybit.com/v5/private"
    if IS_TESTNET else
    "wss://stream.bybit.com/v5/private"
)
