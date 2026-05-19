import logging
import pandas as pd
import numpy as np
import config
import time

logger = logging.getLogger(__name__)

class StrategyProcessor:
    """
    HFT Scalping Strategy v4.0 (Multi-Pair Instance)
    
    Features:
    - Multi-timeframe confirmation (1m + 3m)
    - Order flow analysis (aggressive ratio + large trades)
    - Volatility regime detection (dynamic SL/TP)
    - Signal fusion scoring system
    """

    def __init__(self, symbol: str, execution_engine):
        self.symbol = symbol
        self.execution = execution_engine

        # Orderbook State
        self.bids = {}  
        self.asks = {}  
        self.obi = 0.0
        self._ob_snapshot_received = False

        # Kline State (1m primary)
        self.klines_df = pd.DataFrame(
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover']
        )
        
        # 3m confirmation klines
        self.klines_3m = pd.DataFrame(
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover']
        )
        self._last_3m_ts = 0

        # Indicators
        self.vwap = 0.0
        self.stoch_rsi_k = 50.0 
        self.stoch_rsi_d = 50.0
        self.current_price = 0.0
        self.atr = 0.0
        
        # Trend
        self.ema_fast = 0.0
        self.ema_slow = 0.0
        self.adx = 0.0
        
        # Volatility / Squeeze
        self.bb_upper = 0.0
        self.bb_lower = 0.0
        self.bb_width = 1.0
        
        # Volume
        self.vol_ma = 0.0
        
        # 3m confirmation indicators
        self.ema_3m_fast = 0.0
        self.ema_3m_slow = 0.0
        self._3m_ready = False
        
        # Order Flow
        self.order_flow = OrderFlowAnalyzer()
        
        self._indicators_ready = False
        self._last_signal_time = 0

    def update_orderbook(self, data, msg_type: str):
        if msg_type == 'snapshot':
            self.bids.clear()
            self.asks.clear()
            self._ob_snapshot_received = True

        if not self._ob_snapshot_received:
            return 

        for price_str, size_str in data.get('b', []):
            price = float(price_str)
            size = float(size_str)
            if size == 0:
                self.bids.pop(price, None)
            else:
                self.bids[price] = size

        for price_str, size_str in data.get('a', []):
            price = float(price_str)
            size = float(size_str)
            if size == 0:
                self.asks.pop(price, None)
            else:
                self.asks[price] = size

        self._calculate_obi()

    def _calculate_obi(self):
        n = config.OBI_TOP_LEVELS
        top_bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[:n]
        top_asks = sorted(self.asks.items(), key=lambda x: x[0])[:n]

        bid_volume = sum(size for _, size in top_bids)
        ask_volume = sum(size for _, size in top_asks)

        total = bid_volume + ask_volume
        if total > 0:
            self.obi = (bid_volume - ask_volume) / total
        else:
            self.obi = 0.0

    def update_kline(self, kline_data):
        try:
            row = {
                'timestamp': int(kline_data.get('start', 0)),
                'open': float(kline_data.get('open', 0)),
                'high': float(kline_data.get('high', 0)),
                'low': float(kline_data.get('low', 0)),
                'close': float(kline_data.get('close', 0)),
                'volume': float(kline_data.get('volume', 0)),
                'turnover': float(kline_data.get('turnover', 0)),
            }
            self.current_price = row['close']
            is_confirmed = kline_data.get('confirm', False)

            ts = row['timestamp']
            mask = self.klines_df['timestamp'] == ts
            if mask.any():
                self.klines_df.loc[mask] = list(row.values())
            else:
                self.klines_df = pd.concat([self.klines_df, pd.DataFrame([row])], ignore_index=True)

            if len(self.klines_df) > 200:
                self.klines_df = self.klines_df.iloc[-200:].reset_index(drop=True)

            # Build 3m klines from 1m data
            self._build_3m_kline(row, is_confirmed)

            self._calculate_indicators()

            if is_confirmed:
                self._check_signals()

        except Exception as e:
            logger.error(f"Error updating kline for {self.symbol}: {e}", exc_info=True)

    def _build_3m_kline(self, row, is_confirmed):
        """Aggregate 1m klines into 3m klines"""
        ts = row['timestamp']
        # 3m candle: group by 3-minute intervals
        candle_ts = (ts // 180000) * 180000  # 180000ms = 3min
        
        if candle_ts != self._last_3m_ts:
            # New 3m candle
            if len(self.klines_3m) > 0:
                self._last_3m_ts = candle_ts
                new_row = {
                    'timestamp': candle_ts,
                    'open': row['open'],
                    'high': row['high'],
                    'low': row['low'],
                    'close': row['close'],
                    'volume': row['volume'],
                    'turnover': row['turnover'],
                }
                self.klines_3m = pd.concat([self.klines_3m, pd.DataFrame([new_row])], ignore_index=True)
            else:
                self._last_3m_ts = candle_ts
                self.klines_3m = pd.DataFrame([row])
        else:
            # Update current 3m candle
            if len(self.klines_3m) > 0:
                idx = len(self.klines_3m) - 1
                self.klines_3m.loc[idx, 'high'] = max(self.klines_3m.loc[idx, 'high'], row['high'])
                self.klines_3m.loc[idx, 'low'] = min(self.klines_3m.loc[idx, 'low'], row['low'])
                self.klines_3m.loc[idx, 'close'] = row['close']
                self.klines_3m.loc[idx, 'volume'] += row['volume']
                self.klines_3m.loc[idx, 'turnover'] += row['turnover']
        
        if len(self.klines_3m) > 100:
            self.klines_3m = self.klines_3m.iloc[-100:].reset_index(drop=True)

    def update_trade(self, trade_data):
        """Process trade stream data for order flow analysis"""
        if config.ORDER_FLOW_ENABLED:
            self.order_flow.update(trade_data)

    def _calculate_indicators(self):
        df = self.klines_df.copy()
        n = len(df)

        min_bars = max(config.EMA_SLOW_PERIOD, config.ATR_PERIOD, config.BB_PERIOD, config.ADX_PERIOD) + 5
        if n < min_bars:
            return

        # VWAP
        tp = (df['high'] + df['low'] + df['close']) / 3
        cum_vp = (tp * df['volume']).cumsum()
        cum_vol = df['volume'].cumsum()
        cum_vol_safe = cum_vol.replace(0, np.nan)
        df['vwap'] = cum_vp / cum_vol_safe
        self.vwap = df['vwap'].iloc[-1] if not np.isnan(df['vwap'].iloc[-1]) else self.current_price

        # EMA Trend
        df['ema_fast'] = df['close'].ewm(span=config.EMA_FAST_PERIOD, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=config.EMA_SLOW_PERIOD, adjust=False).mean()
        self.ema_fast = df['ema_fast'].iloc[-1]
        self.ema_slow = df['ema_slow'].iloc[-1]

        # ATR
        high_low = df['high'] - df['low']
        high_close_prev = (df['high'] - df['close'].shift(1)).abs()
        low_close_prev = (df['low'] - df['close'].shift(1)).abs()
        tr = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=config.ATR_PERIOD).mean()
        self.atr = df['atr'].iloc[-1] if not np.isnan(df['atr'].iloc[-1]) else 0.0

        # Bollinger Bands
        sma = df['close'].rolling(window=config.BB_PERIOD).mean()
        std = df['close'].rolling(window=config.BB_PERIOD).std()
        self.bb_upper = (sma + config.BB_STD * std).iloc[-1]
        self.bb_lower = (sma - config.BB_STD * std).iloc[-1]
        sma_val = sma.iloc[-1]
        if not np.isnan(self.bb_upper) and not np.isnan(self.bb_lower) and sma_val > 0:
            self.bb_width = (self.bb_upper - self.bb_lower) / sma_val
        else:
            self.bb_width = 1.0

        # Volume MA
        self.vol_ma = df['volume'].rolling(window=config.VOLUME_MA_PERIOD).mean().iloc[-1]

        # StochRSI
        rsi_period = 14
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=rsi_period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=rsi_period).mean()
        loss_safe = loss.replace(0, np.nan)
        rs = gain / loss_safe
        rsi = 100 - (100 / (1 + rs))

        stoch_period = 14
        rsi_min = rsi.rolling(window=stoch_period).min()
        rsi_max = rsi.rolling(window=stoch_period).max()
        rsi_range = (rsi_max - rsi_min).replace(0, np.nan)
        stoch_rsi = (rsi - rsi_min) / rsi_range

        self.stoch_rsi_k = stoch_rsi.rolling(window=3).mean().iloc[-1] * 100
        self.stoch_rsi_d = stoch_rsi.rolling(window=3).mean().rolling(window=3).mean().iloc[-1] * 100

        if np.isnan(self.stoch_rsi_k): self.stoch_rsi_k = 50.0
        if np.isnan(self.stoch_rsi_d): self.stoch_rsi_d = 50.0

        # ADX
        plus_dm = df['high'].diff()
        minus_dm = -df['low'].diff()
        plus_dm[plus_dm < 0] = 0
        plus_dm[plus_dm < minus_dm] = 0
        minus_dm[minus_dm < 0] = 0
        minus_dm[minus_dm < plus_dm] = 0
        
        atr14 = tr.rolling(window=14).mean()
        atr14_safe = atr14.replace(0, np.nan)
        plus_di = 100 * (plus_dm.rolling(window=14).mean() / atr14_safe)
        minus_di = 100 * (minus_dm.rolling(window=14).mean() / atr14_safe)
        
        dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan))
        self.adx = dx.rolling(window=14).mean().iloc[-1]
        if np.isnan(self.adx): self.adx = 20.0

        # 3m EMA confirmation
        if len(self.klines_3m) >= config.EMA_SLOW_PERIOD:
            self.ema_3m_fast = self.klines_3m['close'].ewm(span=config.EMA_FAST_PERIOD, adjust=False).mean().iloc[-1]
            self.ema_3m_slow = self.klines_3m['close'].ewm(span=config.EMA_SLOW_PERIOD, adjust=False).mean().iloc[-1]
            self._3m_ready = True

        self._indicators_ready = True

    def _get_volatility_regime(self) -> str:
        """Classify volatility regime based on ATR%"""
        if self.current_price == 0 or self.atr == 0:
            return "MEDIUM"
        
        atr_pct = self.atr / self.current_price
        
        if atr_pct < config.VOL_LOW_THRESHOLD:
            return "LOW"
        elif atr_pct < config.VOL_HIGH_THRESHOLD:
            return "MEDIUM"
        else:
            return "HIGH"

    def _get_dynamic_sl_tp(self, regime: str):
        """Dynamic SL/TP based on volatility regime"""
        if regime == "LOW":
            return self.atr * 0.3, self.atr * 0.4
        elif regime == "MEDIUM":
            return self.atr * 0.5, self.atr * 0.6
        else:  # HIGH
            return self.atr * 0.8, self.atr * 1.0

    def _confirm_multi_timeframe(self, signal: str) -> bool:
        """Confirm 1m signal with 3m trend"""
        if not self._3m_ready:
            return True  # No 3m data yet, allow trade
        
        if signal == "Buy":
            return self.ema_3m_fast >= self.ema_3m_slow
        else:  # Sell
            return self.ema_3m_fast <= self.ema_3m_slow

    def _calculate_signal_score(self, signal: str) -> float:
        """Calculate composite signal score (0.0 - 1.0)"""
        scores = []
        
        # OBI Score
        obi_strength = min(abs(self.obi) / config.OBI_THRESHOLD, 1.0)
        scores.append(obi_strength * 0.25)
        
        # Multi-timeframe Score
        tf_score = 1.0 if self._confirm_multi_timeframe(signal) else 0.0
        scores.append(tf_score * 0.25)
        
        # Order Flow Score
        if config.ORDER_FLOW_ENABLED:
            of_score = self.order_flow.get_strength(signal)
            scores.append(of_score * 0.25)
        else:
            scores.append(0.5 * 0.25)  # Neutral
        
        # Regime Score
        regime = self._get_volatility_regime()
        regime_score = 1.0 if regime in ["LOW", "MEDIUM"] else 0.5
        scores.append(regime_score * 0.25)
        
        return sum(scores)

    def _check_signals(self):
        if not self._indicators_ready or self.current_price == 0:
            return

        # Cooldown check
        now = time.time()
        if now - self._last_signal_time < 30:
            return

        uptrend = self.ema_fast > self.ema_slow
        downtrend = self.ema_fast < self.ema_slow
        current_vol = self.klines_df['volume'].iloc[-1]
        
        signal = None
        strategy_name = ""

        # 1. Bollinger Squeeze Breakout
        if self.bb_width < config.BB_SQUEEZE_THRESHOLD:
            if self.current_price > self.bb_upper and self.obi > config.OBI_THRESHOLD:
                signal = "Buy"
                strategy_name = "BB_Squeeze"
            elif self.current_price < self.bb_lower and self.obi < -config.OBI_THRESHOLD:
                signal = "Sell"
                strategy_name = "BB_Squeeze"

        # 2. Volume Spike Momentum Breakout
        elif self.adx > config.ADX_TREND_THRESHOLD:
            vol_spike = current_vol > (self.vol_ma * config.VOLUME_SPIKE_MULT)
            
            if vol_spike and uptrend and self.obi > config.OBI_THRESHOLD:
                signal = "Buy"
                strategy_name = "Vol_Spike"
            elif vol_spike and downtrend and self.obi < -config.OBI_THRESHOLD:
                signal = "Sell"
                strategy_name = "Vol_Spike"

        # 3. VWAP Mean Reversion
        else:
            if (uptrend and self.current_price < self.vwap and 
                self.obi > config.OBI_THRESHOLD and 
                self.stoch_rsi_k < config.STOCH_RSI_OVERSOLD and 
                self.stoch_rsi_k > self.stoch_rsi_d):
                signal = "Buy"
                strategy_name = "VWAP_Reversion"
                
            elif (downtrend and self.current_price > self.vwap and 
                  self.obi < -config.OBI_THRESHOLD and 
                  self.stoch_rsi_k > config.STOCH_RSI_OVERBOUGHT and 
                  self.stoch_rsi_k < self.stoch_rsi_d):
                signal = "Sell"
                strategy_name = "VWAP_Reversion"

        if signal:
            # Signal fusion scoring
            score = self._calculate_signal_score(signal)
            
            if score < 0.6:
                logger.debug(f"[{self.symbol}] Signal score {score:.2f} < 0.6 threshold. Skipping.")
                return
            
            # Dynamic SL/TP based on regime
            regime = self._get_volatility_regime()
            sl_distance, tp_distance = self._get_dynamic_sl_tp(regime)

            logger.info(
                f"[{self.symbol}] SIGNAL ({strategy_name}) Score:{score:.2f} | "
                f"Price: {self.current_price:.4f} | OBI: {self.obi:.2f} | "
                f"ADX: {self.adx:.1f} | Regime: {regime} | ATR%: {(self.atr/self.current_price*100):.2f}%"
            )
            
            self.execution.place_order(
                symbol=self.symbol,
                side=signal,
                price=self.current_price,
                sl_distance=sl_distance,
                tp_distance=tp_distance,
                strategy_name=strategy_name
            )
            
            self._last_signal_time = now


class OrderFlowAnalyzer:
    """
    Analyzes trade stream data for order flow signals
    - Aggressive buyer/seller ratio
    - Large trade detection
    """
    
    def __init__(self):
        self.aggressive_buys = 0
        self.aggressive_sells = 0
        self.trade_sizes = []
        self._last_reset = time.time()
        self._window_seconds = 60  # 1-minute rolling window
    
    def update(self, trade_data):
        """Process incoming trade data"""
        try:
            side = trade_data.get("S", "")  # Buy or Sell
            size = float(trade_data.get("v", 0))
            
            # Reset window if needed
            now = time.time()
            if now - self._last_reset > self._window_seconds:
                self.aggressive_buys = 0
                self.aggressive_sells = 0
                self.trade_sizes = []
                self._last_reset = now
            
            if side == "Buy":
                self.aggressive_buys += size
            elif side == "Sell":
                self.aggressive_sells += size
            
            self.trade_sizes.append(size)
            
        except Exception as e:
            logger.debug(f"Order flow update error: {e}")
    
    def get_strength(self, signal: str) -> float:
        """
        Return order flow strength (0.0 - 1.0) for given signal direction
        """
        total = self.aggressive_buys + self.aggressive_sells
        if total == 0:
            return 0.5  # Neutral
        
        buy_ratio = self.aggressive_buys / total
        
        if signal == "Buy":
            # Strong if aggressive buyers dominate
            return min(buy_ratio / config.AGGRESSIVE_RATIO_THRESHOLD, 1.0)
        else:  # Sell
            # Strong if aggressive sellers dominate
            sell_ratio = 1 - buy_ratio
            return min(sell_ratio / config.AGGRESSIVE_RATIO_THRESHOLD, 1.0)
        self.vwap = 0.0
        self.stoch_rsi_k = 50.0 
        self.stoch_rsi_d = 50.0
        self.current_price = 0.0
        self.atr = 0.0
        
        # Trend
        self.ema_fast = 0.0
        self.ema_slow = 0.0
        self.adx = 0.0
        
        # Volatility / Squeeze
        self.bb_upper = 0.0
        self.bb_lower = 0.0
        self.bb_width = 1.0
        
        # Volume
        self.vol_ma = 0.0
        
        self._indicators_ready = False

    # ──────────────────────────────────────────────────────────────────
    #  ORDER BOOK
    # ──────────────────────────────────────────────────────────────────

    def update_orderbook(self, data, msg_type: str):
        if msg_type == 'snapshot':
            self.bids.clear()
            self.asks.clear()
            self._ob_snapshot_received = True

        if not self._ob_snapshot_received:
            return 

        for price_str, size_str in data.get('b', []):
            price = float(price_str)
            size = float(size_str)
            if size == 0:
                self.bids.pop(price, None)
            else:
                self.bids[price] = size

        for price_str, size_str in data.get('a', []):
            price = float(price_str)
            size = float(size_str)
            if size == 0:
                self.asks.pop(price, None)
            else:
                self.asks[price] = size

        self._calculate_obi()

    def _calculate_obi(self):
        n = config.OBI_TOP_LEVELS
        top_bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[:n]
        top_asks = sorted(self.asks.items(), key=lambda x: x[0])[:n]

        bid_volume = sum(size for _, size in top_bids)
        ask_volume = sum(size for _, size in top_asks)

        total = bid_volume + ask_volume
        if total > 0:
            self.obi = (bid_volume - ask_volume) / total
        else:
            self.obi = 0.0

    # ──────────────────────────────────────────────────────────────────
    #  KLINE / CANDLE DATA
    # ──────────────────────────────────────────────────────────────────

    def update_kline(self, kline_data):
        try:
            row = {
                'timestamp': int(kline_data.get('start', 0)),
                'open': float(kline_data.get('open', 0)),
                'high': float(kline_data.get('high', 0)),
                'low': float(kline_data.get('low', 0)),
                'close': float(kline_data.get('close', 0)),
                'volume': float(kline_data.get('volume', 0)),
                'turnover': float(kline_data.get('turnover', 0)),
            }
            self.current_price = row['close']
            is_confirmed = kline_data.get('confirm', False)

            ts = row['timestamp']
            mask = self.klines_df['timestamp'] == ts
            if mask.any():
                self.klines_df.loc[mask] = list(row.values())
            else:
                self.klines_df = pd.concat([self.klines_df, pd.DataFrame([row])], ignore_index=True)

            if len(self.klines_df) > 200:
                self.klines_df = self.klines_df.iloc[-200:].reset_index(drop=True)

            self._calculate_indicators()

            if is_confirmed:
                self._check_signals()

        except Exception as e:
            logger.error(f"Error updating kline for {self.symbol}: {e}", exc_info=True)

    # ──────────────────────────────────────────────────────────────────
    #  INDICATORS
    # ──────────────────────────────────────────────────────────────────

    def _calculate_indicators(self):
        df = self.klines_df.copy()
        n = len(df)

        min_bars = max(config.EMA_SLOW_PERIOD, config.ATR_PERIOD, config.BB_PERIOD, config.ADX_PERIOD) + 5
        if n < min_bars:
            return

        # VWAP
        tp = (df['high'] + df['low'] + df['close']) / 3
        cum_vp = (tp * df['volume']).cumsum()
        cum_vol = df['volume'].cumsum()
        cum_vol_safe = cum_vol.replace(0, np.nan)
        df['vwap'] = cum_vp / cum_vol_safe
        self.vwap = df['vwap'].iloc[-1] if not np.isnan(df['vwap'].iloc[-1]) else self.current_price

        # EMA Trend
        df['ema_fast'] = df['close'].ewm(span=config.EMA_FAST_PERIOD, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=config.EMA_SLOW_PERIOD, adjust=False).mean()
        self.ema_fast = df['ema_fast'].iloc[-1]
        self.ema_slow = df['ema_slow'].iloc[-1]

        # ATR
        high_low = df['high'] - df['low']
        high_close_prev = (df['high'] - df['close'].shift(1)).abs()
        low_close_prev = (df['low'] - df['close'].shift(1)).abs()
        tr = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=config.ATR_PERIOD).mean()
        self.atr = df['atr'].iloc[-1] if not np.isnan(df['atr'].iloc[-1]) else 0.0

        # Bollinger Bands
        sma = df['close'].rolling(window=config.BB_PERIOD).mean()
        std = df['close'].rolling(window=config.BB_PERIOD).std()
        self.bb_upper = (sma + config.BB_STD * std).iloc[-1]
        self.bb_lower = (sma - config.BB_STD * std).iloc[-1]
        sma_val = sma.iloc[-1]
        if not np.isnan(self.bb_upper) and not np.isnan(self.bb_lower) and sma_val > 0:
            self.bb_width = (self.bb_upper - self.bb_lower) / sma_val
        else:
            self.bb_width = 1.0

        # Volume MA
        self.vol_ma = df['volume'].rolling(window=config.VOLUME_MA_PERIOD).mean().iloc[-1]

        # StochRSI
        rsi_period = 14
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=rsi_period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=rsi_period).mean()
        loss_safe = loss.replace(0, np.nan)
        rs = gain / loss_safe
        rsi = 100 - (100 / (1 + rs))

        stoch_period = 14
        rsi_min = rsi.rolling(window=stoch_period).min()
        rsi_max = rsi.rolling(window=stoch_period).max()
        rsi_range = (rsi_max - rsi_min).replace(0, np.nan)
        stoch_rsi = (rsi - rsi_min) / rsi_range

        self.stoch_rsi_k = stoch_rsi.rolling(window=3).mean().iloc[-1] * 100
        self.stoch_rsi_d = stoch_rsi.rolling(window=3).mean().rolling(window=3).mean().iloc[-1] * 100

        if np.isnan(self.stoch_rsi_k): self.stoch_rsi_k = 50.0
        if np.isnan(self.stoch_rsi_d): self.stoch_rsi_d = 50.0

        # ADX Approximation (Simplified for performance, using pure ATR/DMI logic)
        plus_dm = df['high'].diff()
        minus_dm = -df['low'].diff()
        plus_dm[plus_dm < 0] = 0
        plus_dm[plus_dm < minus_dm] = 0
        minus_dm[minus_dm < 0] = 0
        minus_dm[minus_dm < plus_dm] = 0
        
        atr14 = tr.rolling(window=14).mean()
        atr14_safe = atr14.replace(0, np.nan)
        plus_di = 100 * (plus_dm.rolling(window=14).mean() / atr14_safe)
        minus_di = 100 * (minus_dm.rolling(window=14).mean() / atr14_safe)
        
        dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan))
        self.adx = dx.rolling(window=14).mean().iloc[-1]
        if np.isnan(self.adx): self.adx = 20.0

        self._indicators_ready = True

    # ──────────────────────────────────────────────────────────────────
    #  SIGNAL LOGIC
    # ──────────────────────────────────────────────────────────────────

    def _check_signals(self):
        if not self._indicators_ready or self.current_price == 0 or self.atr == 0:
            return

        uptrend = self.ema_fast > self.ema_slow
        downtrend = self.ema_fast < self.ema_slow
        current_vol = self.klines_df['volume'].iloc[-1]
        
        signal = None
        strategy_name = ""

        # 1. Bollinger Squeeze Breakout (Volatility Regime)
        if self.bb_width < config.BB_SQUEEZE_THRESHOLD:
            if self.current_price > self.bb_upper and self.obi > config.OBI_THRESHOLD:
                signal = "Buy"
                strategy_name = "BB_Squeeze"
            elif self.current_price < self.bb_lower and self.obi < -config.OBI_THRESHOLD:
                signal = "Sell"
                strategy_name = "BB_Squeeze"

        # 2. Volume Spike Momentum Breakout (Trending Regime)
        elif self.adx > config.ADX_TREND_THRESHOLD:
            vol_spike = current_vol > (self.vol_ma * config.VOLUME_SPIKE_MULT)
            
            if vol_spike and uptrend and self.obi > config.OBI_THRESHOLD:
                signal = "Buy"
                strategy_name = "Vol_Spike"
            elif vol_spike and downtrend and self.obi < -config.OBI_THRESHOLD:
                signal = "Sell"
                strategy_name = "Vol_Spike"

        # 3. VWAP Mean Reversion (Ranging Regime)
        else:
            if (uptrend and self.current_price < self.vwap and 
                self.obi > config.OBI_THRESHOLD and 
                self.stoch_rsi_k < config.STOCH_RSI_OVERSOLD and 
                self.stoch_rsi_k > self.stoch_rsi_d):
                signal = "Buy"
                strategy_name = "VWAP_Reversion"
                
            elif (downtrend and self.current_price > self.vwap and 
                  self.obi < -config.OBI_THRESHOLD and 
                  self.stoch_rsi_k > config.STOCH_RSI_OVERBOUGHT and 
                  self.stoch_rsi_k < self.stoch_rsi_d):
                signal = "Sell"
                strategy_name = "VWAP_Reversion"

        # Dispatch Signal
        if signal:
            sl_distance = self.atr * config.ATR_SL_MULTIPLIER
            tp_distance = sl_distance * config.RISK_REWARD_RATIO

            logger.info(
                f"[{self.symbol}] ★ {signal.upper()} SIGNAL ({strategy_name}) | "
                f"Price: {self.current_price:.4f} | OBI: {self.obi:.2f} | "
                f"ADX: {self.adx:.1f} | BBW: {self.bb_width:.3f} | ATR: {self.atr:.4f}"
            )
            
            self.execution.place_order(
                symbol=self.symbol,
                side=signal,
                price=self.current_price,
                sl_distance=sl_distance,
                tp_distance=tp_distance,
                strategy_name=strategy_name
            )

