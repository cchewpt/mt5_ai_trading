import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import time
import talib
import os
from telegram import Bot
from telegram.error import TelegramError
import asyncio
import threading
# ===============================
# Bot telegram
# ===============================
CHAT_ID = "-4802152816"
TELEGRAM_TOKEN = "8250762395:AAEp9qozfMuD8KaZuGsalp87laUKfsGJdz0"
bot = Bot(token=TELEGRAM_TOKEN)
async def send_telegram(message):
    try: 
        await bot.send_message(chat_id=CHAT_ID, text=message)
        print("ส่งแล้ว")
    except Exception as e:
        print(f"⚠️ Failed to send Telegram message: {e}")
def notify(message):
    asyncio.run(send_telegram(message))
# ===============================
# Parameters & Configuration
# ===============================
LOGIN = 91834901
PASSWORD = "Joe@##12425"
SERVER = "XMGlobal-MT5 5"
DRY_RUN = False                
SYMBOL = "GOLD"
tf_input = float(input("Timeframe(add number 1 or 5):"))
if tf_input == 1:
    tf = mt5.TIMEFRAME_M1
if tf_input == 5:
    tf = mt5.TIMEFRAME_M5
TIMEFRAME = tf
LOT = 0.01 
DEVIATION = 400                 
MAGIC_NUMBER = 234000            
SL_USD = 8
TP_USD = 10
TRAILING_PRICE = 5
TRAILING_STOPLOSS = 0
ADX_period = 14
ATR_period = 7
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
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, 800)
    if rates is None or len(rates) == 0:
        print("Failed to get market data")
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df
# ===============================
# Candle close strategy
# ===============================
def get_candle():
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, 3)
    if rates is None or len(rates) < 2:
        print("Can't get last candle")
        return None
    previous_candle = rates[-3]
    last_candle = rates[-2]
    return {
        "previous_open": previous_candle["open"],
        "previous_high": previous_candle["high"],
        "previous_low": previous_candle["low"],
        "previous_close": previous_candle["close"],
        "last_high": last_candle["high"],
        "last_low": last_candle["low"],
        "last_open": last_candle["open"],
        "last_close": last_candle["close"]
    }
# ===============================
# order conndition
# ===============================
def signal_order(ema_fast, ema_slow, ema_trend, last_candle_close, last_candle_high, previous_candle_high, last_candle_low, previous_candle_low):
    if ema_fast[-2] > ema_slow[-2] and last_candle_close > ema_trend[-2] and ema_fast[-2] > ema_trend[-2] and ema_slow[-2] > ema_trend[-2]:
        return "BUY"
    if ema_fast[-2] < ema_slow[-2] and last_candle_close < ema_trend[-2] and ema_fast[-2] < ema_trend[-2] and ema_slow[-2] < ema_trend[-2]:
        return "SELL"
# ===============================   
# Calculate EMA indicators with TA-Lib
# ===============================
def calc_ema(df, period):
    # Calculate exponential moving average for given period
    return talib.EMA(df['close'].values, timeperiod=period)
# ===============================
# ADX 
# ===============================
def get_adx(symbol=SYMBOL, timeframe=TIMEFRAME, period=ADX_period, bars=150):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None or len(rates) < period:
        print("⚠️ Not enough data for ADX calculation")
        return None
    df = pd.DataFrame(rates)
    adx = talib.ADX(df['high'], df['low'], df['close'], timeperiod=ADX_period)
    latest_adx = adx.iloc[-2]
    return float(latest_adx)
#================================
# ATR
#================================
def get_ATR(symbol=SYMBOL, timeframe=TIMEFRAME, period=ATR_period, bars=500):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None or len(rates) < period:
        print("⚠️ Not enough data for ATR calculation")
        return None
    df = pd.DataFrame(rates)
    atr = talib.ATR(df['high'], df['low'], df['close'], timeperiod=ATR_period)
    latest_atr = atr.iloc[-2]
    return float(latest_atr)
# ===============================
# Check for EMA Crossover Buy Signal
# ===============================
def check_signal(ema_fast, ema_slow, ema_trend):
    # Buy signal when EMA8 crosses above EMA20
    if ema_fast[-3] < ema_trend[-3] and ema_fast[-2] >= ema_trend[-2]:
        return "BUY"
    return None
# ===============================
# Check for EMA Crossunder Close Signal
# ===============================
def check_signal_close(ema_fast, ema_slow, ema_trend):
    # Close signal when EMA8 crossesunder EMA20
    if ema_fast[-3] > ema_trend[-3] and ema_fast[-2] <= ema_trend[-2]:
        return "SELL"
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
    atr_value = get_ATR(symbol=SYMBOL, timeframe=TIMEFRAME, period=ATR_period, bars=800)
    sl_usd = SL_USD
    tp_usd = TP_USD
    contract_size = mt5.symbol_info(SYMBOL).trade_contract_size
    price_diff_for_tp = tp_usd / (LOT * contract_size)
    price_diff_for_sl = sl_usd / (LOT * contract_size)
    tp = price + price_diff_for_tp
    sl = price - price_diff_for_sl
    #sl = price - (atr_value * 2)
    #tp = price + (atr_value * 2 * 1.5)
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
# ===============================
# Send Market Sell Order
# ===============================
def send_order_sell(symbol, lot, deviation, magic, dry_run=False):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        print(f"❌ Failed to get tick data for {symbol}")
        return None
    price = tick.bid
    atr_value = get_ATR(symbol=SYMBOL, timeframe=TIMEFRAME, period=ATR_period, bars=800)
    sl_usd = SL_USD
    tp_usd = TP_USD
    contract_size = mt5.symbol_info(SYMBOL).trade_contract_size
    price_diff_for_tp = tp_usd / (LOT * contract_size)
    price_diff_for_sl = sl_usd / (LOT * contract_size)
    tp = price - price_diff_for_tp 
    sl = price + price_diff_for_sl
    #sl = price + (atr_value * 2)
    #tp = price - (atr_value * 2 *1.5)
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": mt5.ORDER_TYPE_SELL,
        "price": price,
        "deviation": deviation,
        "magic": magic,
        "comment": "Python Simple Sell Bot",
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
        print(f"✅ Sell order executed! Ticket: {result.order}")
    return result
#================================
# Traling stop fuction
#================================
def trailing_stop_buy(symbol, positions):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print("❌ Failed to get tick data")
        return
    atr_value = get_ATR(symbol=SYMBOL, timeframe=TIMEFRAME, period=ATR_period, bars=800)
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
                notify(f"กันหน้าทุนแล้วนะไอ้สัส SL ที่ {TRAILING_STOPLOSS} ดอล")
            else:
                print(f"⚠️ Trailing Stop update failed: {result.comment}")
    return None

def trailing_stop_sell(symbol, positions):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print("❌ Failed to get tick data")
        return
    atr_value = get_ATR(symbol=SYMBOL, timeframe=TIMEFRAME, period=ATR_period, bars=800)
    sl_usd = SL_USD
    tp_usd = TP_USD
    contract_size = mt5.symbol_info(SYMBOL).trade_contract_size
    positions = mt5.positions_get(symbol=SYMBOL)
    price = tick.bid
    ticket = positions[0].ticket
    open_price = positions[0].price_open
    price_diff_for_tp = tp_usd / (LOT * contract_size)
    price_diff_for_sl = sl_usd / (LOT * contract_size)
    Trailing_sl = TRAILING_STOPLOSS             # Profit when hit trailing stop
    Trailing_start = TRAILING_PRICE             # price move x $ before trailing
    trailing_amount = Trailing_sl / (LOT * contract_size)
    traling_activation = open_price - Trailing_start
    tp = open_price - price_diff_for_tp
    sl = open_price - price_diff_for_sl
    new_sl = open_price - trailing_amount
    print(f"Trailing amount need {traling_activation}\n New SL: {new_sl}")
    if positions is None:
        print("❌ Failed to get Open order data")
        return
    if price > traling_activation:
        print("Price is not yet reach the Trailing activation price")
    if price <= traling_activation:
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
                notify(f"กันหน้าทุนแล้วนะไอ้สัส SL ที่ {TRAILING_STOPLOSS} ดอล")
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
    notify(f"JOEJRA Trader Alpha 1.1 has Started!!!!!!!!\nUser = {LOGIN} \nTrading on {SYMBOL}\nLot size = {LOT}\nTimeframe = {tf_input} Min\nTp = {TP_USD}\nSl = {SL_USD}")
    try:
        last_minute_run = 0
        Activation_Trailing = False
        Activation_Send = False
        Activation_Buy = True
        Activation_Sell = True
        current_min = int((time.time())/60)
        while True:
            df = get_data()
            if df is None:
                time.sleep(10)
                continue
            # Calculate EMA8 and EMA20
            ema8 = calc_ema(df, 8)
            ema20 = calc_ema(df, 20)
            ema200 = calc_ema(df, 200)
            # Caculate candle
            candle = get_candle()
            last_candle_close = candle['last_close']
            last_candle_open = candle['last_open']
            previous_candle_close = candle['previous_close']
            previous_candle_open = candle['previous_open']
            last_candle_high = candle['last_high']
            last_candle_low = candle['last_low']
            previous_candle_high = candle['previous_high']
            previous_candle_low = candle ['previous_low']
            # Determine if buy signal exists
            adx_value = get_adx(symbol=SYMBOL, timeframe=TIMEFRAME, period=ADX_period, bars=800)
            atr_value = get_ATR(symbol=SYMBOL, timeframe=TIMEFRAME, period=ATR_period, bars=800)
            ema_crossover = check_signal(ema8, ema20, ema200)
            ema_crossunder = check_signal_close(ema8, ema20, ema200)
            if current_min != last_minute_run:
                Activation_Trailing = False
                Activation_Send = False
                if ema_crossover == "BUY":
                    Activation_Buy = False
                    notify("พร้อมบายแล้วไอ้สัส เตรียมตัว")
                    last_minute_run = current_min
                if ema_crossunder == "SELL":
                    Activation_Sell = False
                    notify("พร้อมเซลแล้วไอ้สัส เตรียมตัว")
                    last_minute_run = current_min
            signal = signal_order(ema8, ema20, ema200, last_candle_close, last_candle_high, previous_candle_high, last_candle_low, previous_candle_low)
            os.system("cls" if os.name == "nt" else "clear")
            print("#" + "=" * 60 + "#")
            print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"📈 Symbol: {SYMBOL} | TF: {TIMEFRAME}")
            print(f"💰 Current Price:{df['close'].iloc[-1]:.2f}")
            print(f"📊 EMA8: {ema8[-1]:.2f} | EMA20: {ema20[-1]:.2f} | EMA200: {ema200[-1]:.2f}" )
            print(f"📍 Signal: {ema_crossover or 'None'} | Close Signal: {ema_crossunder or 'None'}")
            print(f"Current order:{mt5.positions_get(symbol=SYMBOL)}")
            print("#" + "=" * 60 + "#")
            print(f"Activation Trailing: {Activation_Trailing}\nActvation Send: {Activation_Send}\nActivation Buy: {Activation_Buy}\nActivation Sell: {Activation_Sell}")
            positions = mt5.positions_get(symbol=SYMBOL)
            current_min = int((time.time())/60)
            # Condition check
            if ema8[-2] > ema20[-2]:
                print("EMA 8 > EMA 20 now")
            else:
                print("EMA 8 < EMA 20 now")
            if ema8[-2] > ema200[-2] and ema20[-2] > ema200[-2]:
                print("Uptrend")
            if ema8[-2] < ema200[-2] and ema20[-2] < ema200[-2]:
                print("Downtrend")
            if last_candle_high > previous_candle_high:
                print("PA buy win")
            if last_candle_low < previous_candle_low:
                print("PA sell win")
            if last_candle_close > ema200[-2]:
                print("Price is above EMA 200")
            else:
                print("Price is under EMA 200")
            if adx_value > 25:
                print("ADX is over 25")
            else:
                print("ADX is under 25")
            if positions and len(positions) > 0:
                pos = mt5.positions_get(symbol=SYMBOL)[0]
                if pos.type == mt5.POSITION_TYPE_BUY:
                    trailing_stop_buy(SYMBOL,positions=mt5.positions_get(symbol=SYMBOL))
                if pos.type == mt5.POSITION_TYPE_SELL:
                    trailing_stop_sell(SYMBOL,positions=mt5.positions_get(symbol=SYMBOL))
            if signal == "BUY":
                positions = mt5.positions_get(symbol=SYMBOL)
                if positions and len(positions) > 0:
                    print("Position already open, skipping new order")
                else:
                    if Activation_Buy == False:
                        send_order(SYMBOL, LOT, DEVIATION, MAGIC_NUMBER, dry_run=DRY_RUN)
                        notify(f"กูบายให้แล้วนะ ที่ราคา{mt5.symbol_info_tick(SYMBOL).ask}")
                        last_minute_run = current_min
                        Activation_Buy = True
            if signal =="SELL":
                positions = mt5.positions_get(symbol=SYMBOL)
                if positions and len(positions) > 0:
                    print("Position already open, skipping new order")  
                else:  
                    if Activation_Sell == False:
                            send_order_sell(SYMBOL, LOT, DEVIATION, MAGIC_NUMBER, dry_run=DRY_RUN)
                            notify(f"กูเซลแล้วนะ ที่ราคา{mt5.symbol_info_tick(SYMBOL).bid}")
                            last_minute_run = current_min
                            Activation_Sell = True
            time.sleep(1)

    except KeyboardInterrupt:
        print("Bot stopped by user")
        mt5.shutdown()
        print("MT5 connection closed")
        notify("JOEJRA Trader Alpha 1.1 Shutdown XXXX")
    #finally:
       # mt5.shutdown()
        #print("MT5 connection closed")


# ===============================
# Entry Point
# ===============================
if __name__ == "__main__":
    main_loop()
