import sys
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')

from pybit.unified_trading import HTTP
import config
import logging

logging.basicConfig(level=logging.INFO)

print("Starting API Test...")
print(f"API Key: {config.API_KEY[:4]}...{config.API_KEY[-4:]}")
print(f"Is Testnet: {config.IS_TESTNET}")

session = HTTP(
    testnet=config.IS_TESTNET,
    api_key=config.API_KEY,
    api_secret=config.API_SECRET,
)

try:
    balance = session.get_wallet_balance(accountType="UNIFIED")
    print("SUCCESS: Balance retrieved successfully!")
    print(balance)
except Exception as e:
    print("FAILED to retrieve wallet balance:")
    print(e)

try:
    leverage = session.set_leverage(
        category=config.CATEGORY,
        symbol=config.SYMBOL,
        buyLeverage=str(config.LEVERAGE),
        sellLeverage=str(config.LEVERAGE)
    )
    print("SUCCESS: Leverage set successfully!")
    print(leverage)
except Exception as e:
    print("FAILED to set leverage:")
    print(e)

try:
    print("Testing placing a test order...")
    # Try placing a small Limit order far away from the market price so it doesn't fill
    order = session.place_order(
        category=config.CATEGORY,
        symbol=config.SYMBOL,
        side="Buy",
        orderType="Limit",
        qty="0.001",
        price="70000", # set a valid price within 10% range to avoid 110003 error
        timeInForce="GTC"
    )
    print("SUCCESS: Limit Order placed successfully!")
    print(order)
    
    order_id = order.get("result", {}).get("orderId")
    if order_id:
        print(f"Cancelling order {order_id}...")
        cancel = session.cancel_order(
            category=config.CATEGORY,
            symbol=config.SYMBOL,
            orderId=order_id
        )
        print("SUCCESS: Order cancelled successfully!")
        print(cancel)
except Exception as e:
    print("FAILED to place/cancel order:")
    print(e)
