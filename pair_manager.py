import logging
import time
from pybit.unified_trading import HTTP
import config

logger = logging.getLogger(__name__)

class PairManager:
    """
    Manages the dynamic list of pairs and sets leverage.
    Fetches the top N USDT pairs by 24h turnover.
    """
    def __init__(self, execution_engine):
        self.session = HTTP(
            testnet=config.IS_TESTNET,
            api_key=config.API_KEY,
            api_secret=config.API_SECRET,
        )
        self.execution = execution_engine
        self.pairs = []
        self.last_update = 0

    def get_top_pairs(self) -> list:
        """
        Fetch top pairs and cache them for PAIR_REFRESH_SECONDS.
        """
        now = time.time()
        if self.pairs and (now - self.last_update) < config.PAIR_REFRESH_SECONDS:
            return self.pairs

        logger.info(f"Fetching top {config.TOP_N_PAIRS} USDT pairs by volume...")
        try:
            r = self.session.get_tickers(category=config.CATEGORY)
            all_pairs = [x for x in r['result']['list'] if x['symbol'].endswith('USDT')]
            
            # Sort by 24h turnover (volume in USDT)
            sorted_pairs = sorted(
                all_pairs, 
                key=lambda x: float(x['turnover24h'] or 0), 
                reverse=True
            )
            
            # Keep top N
            self.pairs = [p['symbol'] for p in sorted_pairs[:config.TOP_N_PAIRS]]
            self.last_update = now
            
            logger.info(f"Top pairs selected: {', '.join(self.pairs[:5])}... (Total: {len(self.pairs)})")
            
            # Automatically set leverage for all selected pairs
            self._set_leverage_for_pairs()
            
            return self.pairs
            
        except Exception as e:
            logger.error(f"Failed to fetch pairs: {e}", exc_info=True)
            # Fallback to single pair if API fails
            if not self.pairs:
                logger.warning(f"Using fallback single pair: {config.SYMBOL}")
                self.pairs = [config.SYMBOL]
            return self.pairs

    def _set_leverage_for_pairs(self):
        """
        Attempt to set the configured leverage for all active pairs.
        """
        logger.info(f"Setting leverage to {config.LEVERAGE}x for {len(self.pairs)} pairs...")
        success_count = 0
        for symbol in self.pairs:
            try:
                self.session.set_leverage(
                    category=config.CATEGORY,
                    symbol=symbol,
                    buyLeverage=str(config.LEVERAGE),
                    sellLeverage=str(config.LEVERAGE),
                )
                success_count += 1
                time.sleep(0.1) # Rate limit protection
            except Exception as e:
                # 110043 means leverage not modified (already set)
                if "110043" not in str(e):
                    logger.debug(f"Could not set leverage for {symbol}: {e}")
                else:
                    success_count += 1
                    
        logger.info(f"Leverage verified/set for {success_count}/{len(self.pairs)} pairs.")

