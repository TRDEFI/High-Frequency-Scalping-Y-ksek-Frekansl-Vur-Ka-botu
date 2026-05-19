import logging
import time
import threading
from datetime import datetime, timezone
from pybit.unified_trading import HTTP
import config

logger = logging.getLogger(__name__)

class ExecutionEngine:
    """
    Execution Engine v4.0 (Thread-safe Multi-Pair HFT)
    
    Features:
    - Dynamic qtyStep from instrument_info API
    - Adaptive position sizing (last 5 trades win rate)
    - Funding fee tracking
    - Trade history for adaptive sizing
    - Smart cooldown with frequency control
    """
    
    def __init__(self):
        self.session = HTTP(
            testnet=config.IS_TESTNET,
            api_key=config.API_KEY,
            api_secret=config.API_SECRET,
        )
        
        self.lock = threading.Lock()
        
        # State tracking
        self.active_positions = {}
        self.last_loss_time = 0
        self.last_trade_time = 0
        
        # Instrument info cache (for qtyStep)
        self.instrument_cache = {}
        
        # Trade history for adaptive sizing
        self.trade_history = []
        
        # Circuit Breaker
        self.daily_pnl = 0.0
        self.funding_pnl = 0.0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.consecutive_losses = 0
        self.circuit_breaker_active = False
        self._day_start = datetime.now(timezone.utc).date()
        
        # Frequency control
        self.trades_last_hour = []
        self.symbol_last_trade_time = {}
        
        # Load initial instrument info
        self._preload_instrument_info()

    def _get_decimal_count(self, value_str: str) -> int:
        """Extract decimal count from a numeric string (e.g. '0.001' → 3, '1' → 0)"""
        if "." in value_str:
            return len(value_str.split(".")[-1])
        return 0

    def _preload_instrument_info(self):
        """Preload instrument info for common symbols"""
        try:
            r = self.session.get_instruments_info(category=config.CATEGORY, limit=100)
            for inst in r.get("result", {}).get("list", []):
                symbol = inst.get("symbol")
                if symbol:
                    ls_filter = inst.get("lotSizeFilter", {})
                    pr_filter = inst.get("priceFilter", {})
                    qty_step_str = ls_filter.get("qtyStep", "0.001")
                    tick_size_str = pr_filter.get("tickSize", "0.01")
                    self.instrument_cache[symbol] = {
                        "qtyStep": float(qty_step_str),
                        "qtyStepStr": qty_step_str,
                        "qtyDecimals": self._get_decimal_count(qty_step_str),
                        "tickSize": float(tick_size_str),
                        "tickSizeStr": tick_size_str,
                        "priceDecimals": self._get_decimal_count(tick_size_str),
                    }
            logger.info(f"Preloaded {len(self.instrument_cache)} instrument configs")
        except Exception as e:
            logger.warning(f"Failed to preload instrument info: {e}")

    def _get_instrument_info(self, symbol: str):
        """Get instrument info with caching"""
        if symbol not in self.instrument_cache:
            try:
                r = self.session.get_instruments_info(category=config.CATEGORY, symbol=symbol)
                inst = r.get("result", {}).get("list", [{}])[0]
                ls_filter = inst.get("lotSizeFilter", {})
                pr_filter = inst.get("priceFilter", {})
                qty_step_str = ls_filter.get("qtyStep", "0.001")
                tick_size_str = pr_filter.get("tickSize", "0.01")
                self.instrument_cache[symbol] = {
                    "qtyStep": float(qty_step_str),
                    "qtyStepStr": qty_step_str,
                    "qtyDecimals": self._get_decimal_count(qty_step_str),
                    "tickSize": float(tick_size_str),
                    "tickSizeStr": tick_size_str,
                    "priceDecimals": self._get_decimal_count(tick_size_str),
                }
            except Exception as e:
                logger.warning(f"Failed to get instrument info for {symbol}: {e}")
                self.instrument_cache[symbol] = {
                    "qtyStep": 0.001, "qtyStepStr": "0.001", "qtyDecimals": 3,
                    "tickSize": 0.01, "tickSizeStr": "0.01", "priceDecimals": 2,
                }
        return self.instrument_cache[symbol]

    def _reset_daily_stats(self):
        today = datetime.now(timezone.utc).date()
        if today != self._day_start:
            logger.info(
                f"New day. Prev: Trades={self.trade_count}, W/L={self.win_count}/{self.loss_count}, "
                f"PnL={self.daily_pnl:+.4f}, Funding={self.funding_pnl:+.4f}"
            )
            self.daily_pnl = 0.0
            self.funding_pnl = 0.0
            self.trade_count = 0
            self.win_count = 0
            self.loss_count = 0
            self.consecutive_losses = 0
            self.circuit_breaker_active = False
            self.trade_history = []
            self.trades_last_hour = []
            self._day_start = today

    def _get_adaptive_position_size(self) -> float:
        """Adjust position size based on last N trades win rate"""
        if not config.ADAPTIVE_SIZING_ENABLED or len(self.trade_history) < config.ADAPTIVE_LOOKBACK_TRADES:
            return config.POSITION_SIZE_USDT
        
        recent = self.trade_history[-config.ADAPTIVE_LOOKBACK_TRADES:]
        win_rate = sum(1 for t in recent if t['pnl'] >= 0) / len(recent)
        
        if win_rate >= 0.60:
            size = config.POSITION_SIZE_USDT * 1.25
            logger.debug(f"Adaptive sizing: WR={win_rate:.0%} → ${size:.0f} (scale up)")
        elif win_rate < 0.40:
            size = config.POSITION_SIZE_USDT * 0.75
            logger.debug(f"Adaptive sizing: WR={win_rate:.0%} → ${size:.0f} (scale down)")
        else:
            size = config.POSITION_SIZE_USDT
        
        return max(config.MIN_POSITION_SIZE, min(config.MAX_POSITION_SIZE, size))

    def _get_dynamic_qty(self, symbol: str, price: float) -> str:
        """Calculate qty using instrument_info qtyStep, enforcing minimum contract size"""
        inst = self._get_instrument_info(symbol)
        qty_step = inst["qtyStep"]
        decimals = inst["qtyDecimals"]
        
        target_size = self._get_adaptive_position_size()
        raw_qty = target_size / price
        
        qty = round(raw_qty / qty_step) * qty_step
        
        if qty < qty_step:
            qty = qty_step
        
        return f"{qty:.{decimals}f}"

    def _round_price(self, symbol: str, price: float) -> str:
        """Round price to valid tickSize precision"""
        inst = self._get_instrument_info(symbol)
        tick_size = inst["tickSize"]
        decimals = inst["priceDecimals"]
        rounded = round(price / tick_size) * tick_size
        return f"{rounded:.{decimals}f}"

    def _get_spread_pct(self, symbol: str):
        """Get bid-ask spread percentage. Returns None if orderbook unavailable."""
        try:
            r = self.session.get_orderbook(category=config.CATEGORY, symbol=symbol, limit=1)
            book = r.get("result", {})
            bids = book.get("b", [])
            asks = book.get("a", [])
            if bids and asks:
                bid = float(bids[0][0])
                ask = float(asks[0][0])
                if bid > 0:
                    return round((ask - bid) / bid * 100, 2)
            return None
        except Exception:
            return None

    def _check_frequency_limit(self) -> bool:
        """Check if trading frequency is within limits"""
        now = time.time()
        # Remove trades older than 1 hour
        self.trades_last_hour = [t for t in self.trades_last_hour if now - t < 3600]
        
        # If more than 20 trades in last hour, add cooldown
        if len(self.trades_last_hour) > 20:
            logger.debug(f"Frequency limit: {len(self.trades_last_hour)} trades/hour. Cooldown active.")
            return False
        return True

    def place_order(self, symbol: str, side: str, price: float, sl_distance: float, tp_distance: float, strategy_name: str):
        with self.lock:
            self._reset_daily_stats()

            if self.circuit_breaker_active:
                return

            if self.daily_pnl < 0 and abs(self.daily_pnl) >= config.DAILY_LOSS_LIMIT_USDT:
                self.circuit_breaker_active = True
                logger.warning(f"DAILY LOSS LIMIT ({self.daily_pnl:+.2f}). Stopping.")
                return

            if self.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
                elapsed = time.time() - self.last_loss_time
                if elapsed < config.CONSECUTIVE_LOSS_PAUSE:
                    return
                else:
                    logger.info("Consecutive loss pause expired. Resuming.")
                    self.consecutive_losses = 0

            if len(self.active_positions) >= config.MAX_OPEN_POSITIONS:
                return

            if symbol in self.active_positions:
                return
                
            now = time.time()

            # Per-symbol cooldown: prevent re-trading same symbol within 5 minutes
            last_sym = self.symbol_last_trade_time.get(symbol, 0)
            if now - last_sym < 300:
                return

            if self.consecutive_losses > 0 and (now - self.last_loss_time < config.POST_LOSS_COOLDOWN_SECONDS):
                return

            if now - self.last_trade_time < config.TRADE_COOLDOWN_SECONDS:
                return

            if not self._check_frequency_limit():
                return

            # Spread check: reject if bid-ask spread > 2% or orderbook unavailable
            spread_pct = self._get_spread_pct(symbol)
            if spread_pct is None:
                logger.warning(f"[{symbol}] Orderbook unavailable (no bids/asks). Skipping.")
                return
            if spread_pct > 2.0:
                logger.warning(f"[{symbol}] Spread too high: {spread_pct:.1f}% (max 2%). Skipping.")
                return

            # Ensure minimum SL distance (0.5% of price safety floor)
            min_sl_dist = price * config.FALLBACK_SL_PCT
            sl_distance = max(sl_distance, min_sl_dist)
            tp_distance = max(tp_distance, min_sl_dist * config.RISK_REWARD_RATIO)

            sl_price = price - sl_distance if side == "Buy" else price + sl_distance
            tp_price = price + tp_distance if side == "Buy" else price - tp_distance

            # Round FIRST, then validate
            sl_str = self._round_price(symbol, sl_price)
            tp_str = self._round_price(symbol, tp_price)
            qty_str = self._get_dynamic_qty(symbol, price)

            if qty_str == "0" or qty_str == "" or float(qty_str) <= 0:
                logger.warning(f"[{symbol}] Invalid qty ({qty_str}). Skipping.")
                return

            # Post-rounding validation: ensure SL != TP and correct direction
            if side == "Buy":
                if float(sl_str) >= price or float(tp_str) <= price or sl_str == tp_str:
                    sl_str = self._round_price(symbol, price * (1 - config.FALLBACK_SL_PCT))
                    tp_str = self._round_price(symbol, price * (1 + config.FALLBACK_TP_PCT))
            else:
                if float(sl_str) <= price or float(tp_str) >= price or sl_str == tp_str:
                    sl_str = self._round_price(symbol, price * (1 + config.FALLBACK_SL_PCT))
                    tp_str = self._round_price(symbol, price * (1 - config.FALLBACK_TP_PCT))

            try:
                logger.info(
                    f"[{symbol}] {side.upper()} ({strategy_name}) | "
                    f"Entry: {price:.4f} | Qty: {qty_str} | "
                    f"SL: {sl_str} | TP: {tp_str}"
                )

                # Step 1: Market order WITHOUT SL/TP to avoid Bybit cancelling conditional orders
                response = self.session.place_order(
                    category=config.CATEGORY,
                    symbol=symbol,
                    side=side,
                    orderType="Market",
                    qty=qty_str,
                    timeInForce="GTC",
                    positionIdx=0,
                )

                if response.get("retCode") == 0:
                    order_id = response["result"]["orderId"]
                    self.active_positions[symbol] = {
                        "side": side,
                        "time": time.time(),
                        "qty": qty_str
                    }
                    self.trade_count += 1
                    self.last_trade_time = now
                    self.trades_last_hour.append(now)
                    self.symbol_last_trade_time[symbol] = now
                    logger.info(f"[{symbol}] FILLED: {order_id}")

                    # Step 2: Set SL/TP separately via set_trading_stop (with retry)
                    sl_set = False
                    for attempt in range(3):
                        try:
                            if attempt > 0:
                                time.sleep(0.5 * attempt)
                            self.session.set_trading_stop(
                                category=config.CATEGORY,
                                symbol=symbol,
                                side=side,
                                stopLoss=sl_str,
                                takeProfit=tp_str,
                                positionIdx=0,
                            )
                            logger.info(f"[{symbol}] SL/TP set: SL={sl_str} TP={tp_str}")
                            sl_set = True
                            break
                        except Exception as sl_e:
                            if "10001" in str(sl_e):
                                logger.warning(f"[{symbol}] Position closed before SL/TP set (attempt {attempt+1})")
                                break
                            if attempt < 2:
                                logger.warning(f"[{symbol}] SL/TP retry {attempt+1}: {sl_e}")
                            else:
                                logger.error(f"[{symbol}] Failed to set SL/TP after 3 attempts: {sl_e}")
                    if not sl_set:
                        logger.warning(f"[{symbol}] Position running WITHOUT SL/TP protection!")
                else:
                    logger.error(f"[{symbol}] REJECTED: {response}")

            except Exception as e:
                logger.error(f"[{symbol}] Order error: {e}", exc_info=True)

    def update_positions_status(self):
        with self.lock:
            if not self.active_positions:
                return

            self._reset_daily_stats()

            try:
                positions = self.session.get_positions(
                    category=config.CATEGORY,
                    settleCoin="USDT"
                )
                
                live_symbols = set()
                for pos in positions.get("result", {}).get("list", []):
                    if float(pos.get("size", 0)) > 0:
                        live_symbols.add(pos.get("symbol"))

                closed_symbols = [sym for sym in self.active_positions if sym not in live_symbols]
                        
                for sym in closed_symbols:
                    self._record_closed_trade(sym)
                    del self.active_positions[sym]

            except Exception as e:
                logger.error(f"Error checking positions: {e}")

    def _record_closed_trade(self, symbol: str):
        try:
            result = self.session.get_closed_pnl(
                category=config.CATEGORY,
                symbol=symbol,
                limit=1,
            )
            trades = result.get("result", {}).get("list", [])
            if trades:
                pnl = float(trades[0].get("closedPnl", 0))
                self.daily_pnl += pnl

                self.trade_history.append({
                    "symbol": symbol,
                    "pnl": pnl,
                    "timestamp": time.time()
                })

                if pnl >= 0:
                    self.win_count += 1
                    self.consecutive_losses = 0
                    logger.info(f"[{symbol}] TP HIT | PnL: {pnl:+.4f} | Total: {self.daily_pnl:+.4f}")
                else:
                    self.loss_count += 1
                    self.consecutive_losses += 1
                    self.last_loss_time = time.time()
                    logger.info(f"[{symbol}] SL HIT | PnL: {pnl:+.4f} | Total: {self.daily_pnl:+.4f}")

        except Exception as e:
            logger.error(f"[{symbol}] Error fetching closed PnL: {e}")

    def update_funding_pnl(self):
        """Track funding fees separately"""
        try:
            result = self.session.get_transaction_log(
                category=config.CATEGORY,
                limit=20
            )
            for tx in result.get("result", {}).get("list", []):
                if tx.get("type") == "FUNDING":
                    fee = float(tx.get("fee", 0))
                    if fee != 0:
                        self.funding_pnl += fee
        except Exception as e:
            logger.debug(f"Funding fee tracking error: {e}")
