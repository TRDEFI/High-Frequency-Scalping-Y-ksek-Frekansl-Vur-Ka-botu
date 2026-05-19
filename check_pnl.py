from pybit.unified_trading import HTTP
import config

session = HTTP(testnet=config.IS_TESTNET, api_key=config.API_KEY, api_secret=config.API_SECRET)

# Get closed PnL history
result = session.get_closed_pnl(category='linear', symbol='BTCUSDT', limit=20)
print("=" * 120)
print(f"{'#':>2} | {'Side':>5} | {'Qty':>6} | {'Entry Price':>12} | {'Exit Price':>12} | {'PnL (USDT)':>12} | {'Time (UTC)'}")
print("-" * 120)
for i, trade in enumerate(result['result']['list'], 1):
    from datetime import datetime
    ts = datetime.utcfromtimestamp(int(trade['createdTime']) / 1000).strftime('%Y-%m-%d %H:%M:%S')
    pnl = float(trade['closedPnl'])
    marker = "SL HIT" if pnl < 0 else "TP HIT"
    print(f"{i:>2} | {trade['side']:>5} | {trade['qty']:>6} | {trade['avgEntryPrice']:>12} | {trade['avgExitPrice']:>12} | {pnl:>+12.4f} | {ts} ({marker})")

print("=" * 120)
total_pnl = sum(float(t['closedPnl']) for t in result['result']['list'])
print(f"Total Trades: {len(result['result']['list'])}")
print(f"Total PnL: {total_pnl:+.4f} USDT")
wins = sum(1 for t in result['result']['list'] if float(t['closedPnl']) >= 0)
losses = sum(1 for t in result['result']['list'] if float(t['closedPnl']) < 0)
print(f"Wins: {wins} | Losses: {losses} | Win Rate: {wins/(wins+losses)*100 if (wins+losses) > 0 else 0:.1f}%")

# Get current balance
bal = session.get_wallet_balance(accountType='UNIFIED')
for coin in bal['result']['list'][0]['coin']:
    if coin['coin'] == 'USDT':
        print(f"Current Balance: {coin['walletBalance']} USDT (started with 10000)")
        print(f"Net Change: {float(coin['walletBalance']) - 10000:+.4f} USDT")
