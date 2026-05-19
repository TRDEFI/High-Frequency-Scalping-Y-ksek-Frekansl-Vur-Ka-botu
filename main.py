import time
import logging
import logging.handlers
import signal
import sys
from pair_manager import PairManager
from data_feed import MultiPairDataFeed
from strategy import StrategyProcessor
from execution import ExecutionEngine
import config

# Configure Logging with Rotation
log_handler = logging.handlers.RotatingFileHandler(
    "bot.log",
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)
log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        log_handler,
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class MultiPairBotOrchestrator:
    def __init__(self):
        self.running = False
        
        # 1. Execution Engine
        self.execution_engine = ExecutionEngine()
        
        # 2. Pair Manager
        self.pair_manager = PairManager(self.execution_engine)
        self.pairs = self.pair_manager.get_top_pairs()
        
        # 3. Strategy Processors
        self.strategy_map = {}
        for symbol in self.pairs:
            self.strategy_map[symbol] = StrategyProcessor(symbol, self.execution_engine)
            
        # 4. Data Feed
        self.data_feed = MultiPairDataFeed(self.strategy_map)

    def start(self):
        logger.info("=" * 80)
        logger.info("  Bybit HFT Scalping Bot v4.0 (MULTI-PAIR) — Starting Up")
        logger.info("=" * 80)
        logger.info(f"  Pairs:         {len(self.pairs)} (Top Vol USDT)")
        logger.info(f"  Category:      {config.CATEGORY}")
        logger.info(f"  Testnet:       {config.IS_TESTNET}")
        logger.info(f"  Size per Pos:  ${config.POSITION_SIZE_USDT} (Adaptive: ${config.MIN_POSITION_SIZE}-${config.MAX_POSITION_SIZE})")
        logger.info(f"  Leverage:      {config.LEVERAGE}x")
        logger.info(f"  Max Concurrent: {config.MAX_OPEN_POSITIONS}")
        logger.info(f"  Strategies:    VWAP Reversion, VolSpike Breakout, BB Squeeze")
        logger.info(f"  Multi-TF:      {config.PRIMARY_TIMEFRAME}m + {config.CONFIRMATION_TIMEFRAME}m confirmation")
        logger.info(f"  Order Flow:    {'Enabled' if config.ORDER_FLOW_ENABLED else 'Disabled'}")
        logger.info(f"  ATR SL Mult:   {config.ATR_SL_MULTIPLIER}x (Dynamic by regime)")
        logger.info(f"  Risk/Reward:   1:{config.RISK_REWARD_RATIO}")
        logger.info(f"  Daily Limit:   {config.DAILY_LOSS_LIMIT_USDT} USDT")
        logger.info(f"  Vol Regimes:   Low<{config.VOL_LOW_THRESHOLD:.1%} | Med<{config.VOL_HIGH_THRESHOLD:.1%} | High")
        logger.info("=" * 80)

        self.running = True
        self.data_feed.start()

        try:
            while self.running:
                time.sleep(3)
                
                if self.execution_engine.active_positions:
                    self.execution_engine.update_positions_status()
                    self.execution_engine.update_funding_pnl()
                    
        except KeyboardInterrupt:
            self.stop()
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
            self.stop()

    def stop(self):
        if not self.running: return
        logger.info("Shutting down bot...")
        self.running = False
        self.data_feed.stop()
        sys.exit(0)

if __name__ == "__main__":
    bot = MultiPairBotOrchestrator()

    signal.signal(signal.SIGINT, lambda s, f: bot.stop())
    signal.signal(signal.SIGTERM, lambda s, f: bot.stop())

    bot.start()
