from pybit.unified_trading import HTTP
import config

s = HTTP(testnet=config.IS_TESTNET, api_key=config.API_KEY, api_secret=config.API_SECRET)
r = s.get_tickers(category='linear')
pairs = [x for x in r['result']['list'] if x['symbol'].endswith('USDT')]
pairs_sorted = sorted(pairs, key=lambda x: float(x['turnover24h'] or 0), reverse=True)[:35]
for p in pairs_sorted:
    print(f"{p['symbol']:15s} vol24h={float(p['turnover24h'])/1e6:.0f}M  price={p['lastPrice']}")
