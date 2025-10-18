import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import time
import talib
import os
from telegram import Bot
from telegram.error import TelegramError
# ===============================
# Bot telegram
# ===============================
CHAT_ID = "-4802152816"
TELEGRAM_TOKEN = "8250762395:AAEp9qozfMuD8KaZuGsalp87laUKfsGJdz0"
bot = Bot(token=TELEGRAM_TOKEN)
def send_telegram(message):
    try: 
        bot.send_message(chat_id=CHAT_ID, text=message)
        print("ส่งแล้ว")
    except Exception as e:
        print(f"⚠️ Failed to send Telegram message: {e}")
# ===============================
# Parameters & Configuration
# ===============================
LOGIN = int(input("Login ID:"))
PASSWORD = str(input("Password"))
SERVER = str(input("Server:"))
DRY_RUN = False                
SYMBOL = str(input("Symbol(For XM GOLD, BTCUSD):"))
tf_input = float(input("Timeframe(add number 1 or 5):"))
if tf_input == 1:
    tf = mt5.TIMEFRAME_M1
if tf_input == 5:
    tf = mt5.TIMEFRAME_M5
TIMEFRAME = tf
LOT = float(input("Lot size:"))   
DEVIATION = 400                 
MAGIC_NUMBER = 234000            
SL_USD = float(input("SL:"))
TP_USD = float(input("TP:"))
TRAILING_PRICE = float(input("Price needed before moving SL(Start trailing SL):"))
TRAILING_STOPLOSS = float(input("Trailing SL profit:"))
# ===============================
# MT5 Connection & Login
# ===============================
def connect_mt5():
    print("#" + "=" * 60 + "#")
    print("บอทหีหมา")
    print("#" + "=" * 60 + "#")
    if not mt5.initialize():
        print(f"❌ initialize() failed, error code = {mt5.last_error()}")
        return False
    print("✅ MT5 initialized successfully")
    authorized = mt5.login(LOGIN, password=PASSWORD, server=SERVER)
    if not authorized:
        print(f"❌ Login failed, error code = {mt5.last_error()}")
        mt5.shutdown()
        return False
    print(f"✅ Connected to account #{LOGIN}")
    account_info = mt5.account_info()
    if account_info:
        print("\U0001f600")
        print(f"Balance: {account_info.balance:.2f}, Equity: {account_info.equity:.2f}")
        print(f"Server: {account_info.server}, Company: {account_info.company}")
    return True

# ===============================
# Fetch Market Data (OHLC)
# ===============================
def get_data():
    # Retrieve last 200 bars of market data for SYMBOL and TIMEFRAME
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, 200)
    if rates is None or len(rates) == 0:
        print("Failed to get market data")
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

# ===============================
# Calculate EMA indicators with TA-Lib
# ===============================
def calc_ema(df, period):
    # Calculate exponential moving average for given period
    return talib.EMA(df['close'].values, timeperiod=period)


# ===============================
# Check for EMA Crossover Buy Signal
# ===============================
def check_signal(ema_fast, ema_slow):
    # Buy signal when EMA8 crosses above EMA20
    if ema_fast[-3] < ema_slow[-3] and ema_fast[-2] >= ema_slow[-2]:
        return "BUY"
    return None
# ===============================
# Check for EMA Crossunder Close Signal
# ===============================
def check_signal_close(ema_fast, ema_slow):
    # Close signal when EMA8 crossesunder EMA20
    if ema_fast[-3] > ema_slow[-3] and ema_fast[-2] <= ema_slow[-2]:
        return "Close"
    return None
# ===============================
# Send Market Buy Order
# ===============================
def send_order(symbol, lot, deviation, magic, dry_run=False):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        print(f"❌ Failed to get tick data for {symbol}")
        return None
    price = tick.ask
    sl_usd = SL_USD
    tp_usd = TP_USD
    contract_size = mt5.symbol_info(SYMBOL).trade_contract_size
    price_diff_for_tp = tp_usd / (LOT * contract_size)
    price_diff_for_sl = sl_usd / (LOT * contract_size)
    tp = price + price_diff_for_tp
    sl = price - price_diff_for_sl
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": mt5.ORDER_TYPE_BUY,
        "price": price,
        "deviation": deviation,
        "magic": magic,
        "comment": "Python Simple Buy Bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
        "sl": sl,
        "tp": tp,
    }
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Sending BUY order for {symbol} at {price:.2f}...")
    result = mt5.order_send(request)

    if result is None:
        print("❌ order_send() failed")
        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"❌ Order failed: retcode={result.retcode}, comment={result.comment}")
    else:
        print(f"✅ BUY order executed! Ticket: {result.order}")
    return result
#================================
# Traling stop fuction
#================================
def trailing_stop(symbol, positions):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print("❌ Failed to get tick data")
        return
    sl_usd = SL_USD
    tp_usd = TP_USD
    contract_size = mt5.symbol_info(SYMBOL).trade_contract_size
    positions = mt5.positions_get(symbol=SYMBOL)
    price = tick.ask
    ticket = positions[0].ticket
    open_price = positions[0].price_open
    price_diff_for_tp = tp_usd / (LOT * contract_size)
    price_diff_for_sl = sl_usd / (LOT * contract_size)
    Trailing_sl = TRAILING_STOPLOSS             # Profit when hit trailing stop
    Trailing_start = TRAILING_PRICE             # price move x $ before trailing
    trailing_amount = Trailing_sl / (LOT * contract_size)
    traling_activation = open_price + Trailing_start
    tp = open_price + price_diff_for_tp
    sl = open_price - price_diff_for_sl
    new_sl = open_price + trailing_amount
    if positions is None:
        print("❌ Failed to get Open order data")
        return
    if price < traling_activation:
        print("Price is not yet reach the Trailing activation price")
    if price >= traling_activation:
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": symbol,
                "sl": new_sl,
                "tp": tp,
                "position": ticket,
            }
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"✅ Trailing Stop moved to {new_sl:.2f}")
            else:
                print(f"⚠️ Trailing Stop update failed: {result.comment}")
    return None

#================================
#Function Close order when EMA crossunder
#================================
def close_when_EMA_cross(symbol, lot, deviation, magic, positions):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print("❌ Failed to get tick data")
        return
    positions = mt5.positions_get(symbol=SYMBOL)
    ticket = positions[0].ticket
    price = tick.bid
    request = {
    "action": mt5.TRADE_ACTION_DEAL,
    "symbol": symbol,
    "volume": lot,
    "type": mt5.ORDER_TYPE_SELL,     # Opposite of BUY
    "position": ticket,     # Tell MT5 which position to close
    "price": price,
    "magic": magic,
    "deviation": deviation,
    "type_time": mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_IOC
    }
    result = mt5.order_send(request)
    if result is None:
        print("❌ order_send() failed")
        return None
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"❌ Order failed: retcode={result.retcode}, comment={result.comment}")
    else:
        print(f"✅ Close order cause of crossunder EMA: {result.order}")
    return result
# ===============================
# Cooldown function
# ===============================
def cooldown_time():
    last_minute_run = 0
    Activation_Trailing = False
    Activation_Send = False
    Activation_Buy = False
    Activation_Sell = False
    current_min = int((time.time())/60)
    if current_min != last_minute_run:
        Activation_Trailing = False
        Activation_Send = False
        Activation_Buy = False
        Activation_Sell = False
# ===============================
# Main Trading Loop
# ===============================
def main_loop():
    if not connect_mt5():
        return
    print("Symbol =", (SYMBOL))
    print("TF =", (tf_input), "Minute")
    print("TP =", (TP_USD)), print ("SL =", (SL_USD))
    print("Need before trailing =", TRAILING_PRICE), print("New SL after trailing =", TRAILING_STOPLOSS)
    send_telegram(f"JOEJRA Trader Alpha 1.1 has Started!!!!!!!!\nUser = {LOGIN} \nTrading on {SYMBOL}\nLot size = {LOT}\nTimeframe = {tf_input} Min\nTp = {TP_USD}\nSl = {SL_USD}")
    try:
        last_minute_run = 0
        Activation_Trailing = False
        Activation_Send = False
        Activation_Buy = False
        Activation_Sell = False
        current_min = int((time.time())/60)
        while True:
            df = get_data()
            if df is None:
                time.sleep(10)
                continue
            # Calculate EMA8 and EMA20
            ema8 = calc_ema(df, 8)
            ema20 = calc_ema(df, 20)
            if current_min != last_minute_run:
                    Activation_Trailing = False
                    Activation_Send = False
                    Activation_Buy = False
                    Activation_Sell = False
            # Determine if buy signal exists
            signal = check_signal(ema8, ema20)
            signal_close = check_signal_close(ema8, ema20)
            os.system("cls" if os.name == "nt" else "clear")
            print("#" + "=" * 60 + "#")
            print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"📈 Symbol: {SYMBOL} | TF: {TIMEFRAME}")
            print(f"💰 Current Price:{df['close'].iloc[-1]:.2f}")
            print(f"📊 EMA8: {ema8[-1]:.2f} | EMA20: {ema20[-1]:.2f}")
            print(f"📍 Signal: {signal or 'None'} | Close Signal: {signal_close or 'None'}")
            print(f"Current order:{mt5.positions_get(symbol=SYMBOL)}")
            print("#" + "=" * 60 + "#")
            print(f"Activation Trailing: {Activation_Trailing}\nActvation Send: {Activation_Send}\nActivation Buy: {Activation_Buy}\nActivation Sell: {Activation_Sell}")
            positions = mt5.positions_get(symbol=SYMBOL)
            current_min = int((time.time())/60)
            if positions and len(positions) > 0:
                if Activation_Trailing == False:
                    trailing_stop(SYMBOL,positions=mt5.positions_get(symbol=SYMBOL))
                    last_minute_run = current_min
                    Activation_Trailing = True
            if signal == "BUY":
                if Activation_Send == False:
                    send_telegram(f"📈 EMA{SYMBOL} ตัดขึ้นแล้วลูกอีเหี้ย ตอน {datetime.now().strftime('%H:%M:%S')}")
                    Activation_Send = True
                    last_minute_run = current_min
                positions = mt5.positions_get(symbol=SYMBOL)
                if positions and len(positions) > 0:
                    print("Position already open, skipping new order")
                else:
                    if Activation_Buy == False:
                        send_order(SYMBOL, LOT, DEVIATION, MAGIC_NUMBER, dry_run=DRY_RUN)
                        last_minute_run = current_min
                        Activation_Buy = True
            if signal_close == "Close":
                positions = mt5.positions_get(symbol=SYMBOL)
                if Activation_Send == False:
                    send_telegram(f"📈 EMA{SYMBOL} ตัดลงแล้วลูกอีเหี้ย ตอน {datetime.now().strftime('%H:%M:%S')}")
                    last_minute_run = current_min
                    Activation_Send = True
                if positions and len(positions) > 0:
                    print("Not using close order rightnow")
                else:
                    print("No order To Close ไอ้สัส")
            time.sleep(1)

    except KeyboardInterrupt:
        print("Bot stopped by user")
        mt5.shutdown()
        print("MT5 connection closed")
        send_telegram("JOEJRA Trader Alpha 1.1 Shutdown XXXX")
    #finally:
       # mt5.shutdown()
        #print("MT5 connection closed")


# ===============================
# Entry Point
# ===============================
if __name__ == "__main__":
    main_loop()
