import logging
import time
from pybit.unified_trading import WebSocket
import config

logger = logging.getLogger(__name__)

class MultiPairDataFeed:
    """
    MultiPairDataFeed v4.1
    Connects to WebSocket and routes messages to correct StrategyProcessor.
    Subscriptions: Orderbook (L2), Klines (1m), Trade Stream
    Health check: tracks last_seen to detect silent disconnects
    """
    def __init__(self, strategy_map: dict):
        self.strategy_map = strategy_map
        self.ws_public = WebSocket(
            testnet=config.IS_TESTNET,
            channel_type=config.CATEGORY,
        )
        self.pairs = list(strategy_map.keys())
        self.last_seen = time.time()
        self._timeout_seconds = 30

    def _mark_seen(self):
        self.last_seen = time.time()

    def is_alive(self) -> bool:
        return (time.time() - self.last_seen) < self._timeout_seconds

    def handle_orderbook(self, message):
        self._mark_seen()
        data = message.get("data", {})
        if not data:
            return

        symbol = data.get("s")
        if not symbol or symbol not in self.strategy_map:
            return

        msg_type = message.get("type", "delta")
        self.strategy_map[symbol].update_orderbook(data, msg_type=msg_type)

    def handle_kline(self, message):
        self._mark_seen()
        data = message.get("data", [])
        if not data:
            return

        kline = data[0]
        topic = message.get("topic", "")
        if not topic:
            return
            
        parts = topic.split(".")
        if len(parts) >= 3:
            symbol = parts[2]
            if symbol in self.strategy_map:
                self.strategy_map[symbol].update_kline(kline)

    def handle_trade(self, message):
        self._mark_seen()
        if not config.ORDER_FLOW_ENABLED:
            return
            
        data = message.get("data", [])
        if not data:
            return

        for trade in data:
            symbol = trade.get("s")
            if symbol and symbol in self.strategy_map:
                self.strategy_map[symbol].update_trade(trade)

    def start(self):
        logger.info(f"Starting DataFeed v4.1 for {len(self.pairs)} pairs (Testnet: {config.IS_TESTNET})")

        chunk_size = 10
        for i in range(0, len(self.pairs), chunk_size):
            chunk = self.pairs[i:i + chunk_size]

            self.ws_public.orderbook_stream(
                depth=50,
                symbol=chunk,
                callback=self.handle_orderbook,
            )

            self.ws_public.kline_stream(
                interval=config.KLINE_INTERVAL,
                symbol=chunk,
                callback=self.handle_kline,
            )

            if config.ORDER_FLOW_ENABLED:
                self.ws_public.trade_stream(
                    symbol=chunk,
                    callback=self.handle_trade,
                )

    def stop(self):
        logger.info("Stopping MultiPairDataFeed...")
        try:
            self.ws_public.exit()
        except Exception:
            pass
