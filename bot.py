import time
import yaml
import json
import pandas as pd
import numpy as np
import pandas_ta as ta
import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
import os
import talib
from telegram import Bot
from telegram.error import TelegramError
import requests

# ===============================
# Config setup
# ===============================

with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# ===============================
# MT5 Account Credentials
# ===============================
MT5_LOGIN = config["mt5"]["login"]        # เลขบัญชี MT5 ของผู้ใช้งาน
MT5_PASSWORD = config["mt5"]["password"]  # รหัสผ่าน MT5
MT5_SERVER = config["mt5"]["server"]      # ชื่อ Server ที่เชื่อมต่อ MT5

# ===============================
# Strategy & Symbol Configuration
# ===============================

DRY_RUN = config["trading"]["dry_run"]
LOT = config["trading"]["lot"]
DEVIATION = config["trading"]["deviation"]
MAGIC_NUMBER = config["trading"]["magic_number"]

SL_USD = config["risk_levels"]["sl_usd"]
TP_USD = config["risk_levels"]["tp_usd"]
TRAILING_PRICE = config["risk_levels"]["trailing_price"]
TRAILING_STOPLOSS = config["risk_levels"]["trailing_stoploss"]

STRATEGY_SYMBOL = config["strategy"]["symbol"]          # สัญลักษณ์ที่บอทจะเทรด เช่น "EURUSD"
TIMEFRAME_STR = config["strategy"]["timeframe"].upper() # Timeframe ของกราฟ เช่น "M1", "M5", "M15", "H1"

# Mapping Timeframe string -> MetaTrader5 constant
TF_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}
TIMEFRAME = TF_MAP.get(TIMEFRAME_STR, mt5.TIMEFRAME_M5)  # ถ้าไม่เจอ Timeframe ให้ default เป็น M5

# ===============================
# Risk Management Parameters
# ===============================
RISK_EQUITY = config["risk"]["equity"]                 # จำนวนเงินทุนทั้งหมดสำหรับคำนวณ risk
RISK_PCT = config["risk"]["risk_per_trade_pct"]       # % ของ equity ที่พร้อมจะเสี่ยงต่อการเทรดหนึ่งครั้ง

# ===============================
# Strategy Indicator Parameters
# ===============================
EMA_FAST = config["strategy"]["ema_fast"]             # ค่า period ของ EMA ตัวเร็ว
EMA_SLOW = config["strategy"]["ema_slow"]             # ค่า period ของ EMA ตัวช้า
ATR_K = config["strategy"]["atr_k"]                   # ตัวคูณ SL distance จาก ATR
TP_R = config["strategy"]["tp_r"]                     # Take Profit เป็น multiple ของความเสี่ยง (R)

# ===============================
# Execution & Trading Settings
# ===============================
MAX_SPREAD = config["execution"]["max_spread"]        # Spread สูงสุดที่ยอมรับได้ (เช็คก่อนเปิด order)
SLIPPAGE = config["execution"]["slippage"]           # Slippage ที่ยอมรับได้ (points)
ALLOW_LIVE = config["trading"]["allow_live"]         # ถ้าเป็น False จะไม่ส่ง order จริง
ALLOW_SEND_ORDERS = config["trading"]["allow_send_orders"] # ถ้า False -> บอทจะ print เฉยๆ

# ===============================
# Debug / Logging
# ===============================
DEBUG = config["logging"]["debug"]                   # ถ้า True จะ print ข้อมูล debug เยอะ


# ===============================
# Variables
# ===============================

TELEGRAM_API_BASE = config["telegram"]["api"]
BOT_TOKEN = config["telegram"]["bot_token"]
CHAT_ID = config["telegram"]["chat_id"]

# ===============================
# Bot telegram
# ===============================
def send_telegram(message: str):
    """
    ส่งข้อความ Telegram โดยอิงข้อมูลจาก config.yaml
    """
    url = f"{TELEGRAM_API_BASE}/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"[❌ Telegram Error] {response.text}")
        else:
            print(f"[✅ Telegram] Sent: {message}")
    except Exception as e:
        print(f"[⚠️ Telegram Exception] {e}")

# ===============================
# Initialize MT5 Terminal
# ===============================
def initialize_mt5():
    """
    Initialize MT5 terminal.
    Returns True if successful, False otherwise.
    """
    if not mt5.initialize():
        print(f"❌ MT5 initialize() failed, error code = {mt5.last_error()}")
        return False
    print("✅ MT5 initialized successfully")
    return True


# ===============================
# Login to MT5 Account
# ===============================
def login_mt5(login: int, password: str, server: str):
    """
    Login to MT5 account.
    Returns True if login successful, False otherwise.
    """
    authorized = mt5.login(login, password=password, server=server)
    if not authorized:
        print(f"❌ MT5 login failed, error code = {mt5.last_error()}")
        mt5.shutdown()
        return False

    print(f"✅ Connected to MT5 account #{login}")
    account_info = mt5.account_info()
    if account_info:
        print(f"Balance: {account_info.balance:.2f}, Equity: {account_info.equity:.2f}")
        print(f"Server: {account_info.server}, Company: {account_info.company}")
    return True


# ===============================
# Combined MT5 Connect
# ===============================
def connect_mt5():
    """
    Wrapper function to initialize and login to MT5.
    Returns True if both steps succeed, False otherwise.
    """
    print("#" + "=" * 60 + "#")
    print("🚀 Connecting to MT5...")
    print("#" + "=" * 60 + "#")

    if not initialize_mt5():
        return False
    if not login_mt5(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER):
        return False

    return True

# ===============================
# Fetch Market Data (OHLC)
# ===============================
def get_data(symbol: str = STRATEGY_SYMBOL, timeframe: int = TIMEFRAME, bars: int = 200):
    """
    Retrieve OHLC market data from MT5.

    Parameters:
        symbol (str): The symbol to fetch data for.
        timeframe (int): MT5 timeframe constant.
        bars (int): Number of bars to retrieve.

    Returns:
        pd.DataFrame or None: DataFrame with OHLCV and time, or None if failed.
    """
    # Check if symbol is available and active
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"❌ Symbol '{symbol}' not found in MT5.")
        return None

    if not symbol_info.visible:
        # Try to activate symbol in Market Watch
        if not mt5.symbol_select(symbol, True):
            print(f"❌ Failed to activate symbol '{symbol}' in Market Watch.")
            return None

    # Fetch historical rates
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None or len(rates) == 0:
        print(f"❌ Failed to get market data for '{symbol}'.")
        return None

    # Convert to DataFrame
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
def check_signal(ema_fast: np.ndarray, ema_slow: np.ndarray) -> str | None:
    """
    ตรวจจับสัญญาณ EMA Cross Up (BUY)
    
    Parameters:
        ema_fast (np.ndarray): EMA ตัวเร็ว
        ema_slow (np.ndarray): EMA ตัวช้า
        
    Returns:
        str | None: "BUY" ถ้าเกิดสัญญาณตัดขึ้น, None ถ้าไม่มี
    """
    # ต้องมีข้อมูลอย่างน้อย 2 ค่า
    if len(ema_fast) < 2 or len(ema_slow) < 2:
        return None
    
    # Cross Up เกิดเมื่อ EMA fast ตัดขึ้น EMA slow
    if ema_fast[-2] < ema_slow[-2] and ema_fast[-1] >= ema_slow[-1]:
        return "BUY"
    
    return None


# ===============================
# Check for EMA Crossunder Close Signal
# ===============================
def check_signal_close(ema_fast: np.ndarray, ema_slow: np.ndarray) -> str | None:
    # ตรวจสอบว่ามีข้อมูลอย่างน้อย 2 แท่ง
    if len(ema_fast) < 2 or len(ema_slow) < 2:
        return None
    
    # ตรวจสอบ EMA Cross Down
    if ema_fast[-2] > ema_slow[-2] and ema_fast[-1] <= ema_slow[-1]:
        return "Close"
    
    return None

# ===============================
# Send Market Buy Order
# ===============================
def calc_sl_tp(price: float, lot: float, sl_usd: float, tp_usd: float, contract_size: float, order_type: str):
    """
    คำนวณ SL และ TP จาก SL/TP เป็น USD สำหรับ order
    order_type: 'BUY' หรือ 'SELL'
    """
    if order_type.upper() == "BUY":
        sl = price - sl_usd / (lot * contract_size)
        tp = price + tp_usd / (lot * contract_size)
    elif order_type.upper() == "SELL":
        sl = price + sl_usd / (lot * contract_size)
        tp = price - tp_usd / (lot * contract_size)
    else:
        raise ValueError("order_type must be 'BUY' or 'SELL'")
    return sl, tp


def send_order(symbol: str, lot: float, deviation: float, magic: int, dry_run=False):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"❌ Failed to get tick data for {symbol}")
        return None

    price = tick.ask
    contract_size = mt5.symbol_info(symbol).trade_contract_size
    sl, tp = calc_sl_tp(price, lot, SL_USD, TP_USD, contract_size, "BUY")

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

    if dry_run:
        print(f"[DRY RUN] Would send BUY order: {request}")
        return None

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"❌ BUY order failed: {result.comment if result else 'No response'}")
        return None

    print(f"✅ BUY order executed! Ticket: {result.order}")
    return result

#================================
# Traling stop fuction
#================================
def calculate_trailing_sl(open_price: float, lot: float, trailing_profit_usd: float, symbol: str) -> float:
    """
    คำนวณ SL ใหม่เมื่อราคาไปไกลตาม trailing stop
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        raise ValueError(f"Symbol info not found: {symbol}")
    contract_size = info.trade_contract_size
    return open_price + trailing_profit_usd / (lot * contract_size)


def trailing_stop(symbol: str, lot: float):
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        print(f"❌ No open positions for trailing stop on {symbol}")
        return

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"❌ Failed to get tick data for {symbol}")
        return

    contract_size = mt5.symbol_info(symbol).trade_contract_size
    for pos in positions:
        if pos.type != mt5.ORDER_TYPE_BUY:
            continue

        open_price = pos.price_open
        price = tick.ask
        traling_activation = open_price + TRAILING_PRICE
        trailing_amount = TRAILING_STOPLOSS

        if price >= traling_activation:
            new_sl = open_price + trailing_amount / (lot * contract_size)
            tp = open_price + TP_USD / (lot * contract_size)
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": symbol,
                "sl": new_sl,
                "tp": tp,
                "position": pos.ticket,
            }
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"✅ Trailing Stop moved to {new_sl:.2f}")
            else:
                print(f"⚠️ Trailing Stop update failed: {result.comment}")

#================================
#Function Close order when EMA crossunder
#================================
def close_position(symbol: str, lot: float, deviation: float, magic: int):
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        print(f"❌ No open positions to close for {symbol}")
        return

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"❌ Failed to get tick data for {symbol}")
        return

    contract_size = mt5.symbol_info(symbol).trade_contract_size

    for pos in positions:
        if pos.type != mt5.ORDER_TYPE_BUY:
            continue

        price = tick.bid
        sl, tp = calc_sl_tp(price, pos.volume, SL_USD, TP_USD, contract_size, "SELL")

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": mt5.ORDER_TYPE_SELL,
            "position": pos.ticket,
            "price": price,
            "magic": magic,
            "deviation": deviation,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
            "sl": sl,
            "tp": tp,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"❌ Close order failed: {result.comment if result else 'No response'}")
        else:
            print(f"✅ Closed position {pos.ticket} due to EMA cross down")

# ===============================
# Main Trading Loop
# ===============================
def reset_flags_if_new_minute(current_min, last_minute_run, flags):
    if current_min != last_minute_run:
        last_minute_run = current_min
        for key in flags:
            flags[key] = False
    return last_minute_run, flags


def handle_trailing(symbol, positions, flags):
    if positions and not flags["trailing"]:
        trailing_stop(symbol, positions)
        flags["trailing"] = True


def handle_buy_signal(signal, symbol, flags):
    positions = mt5.positions_get(symbol=symbol)
    if signal == "BUY":
        if not flags["send"]:
            send_telegram(f"📈 {symbol} EMA crossed up at {datetime.now().strftime('%H:%M:%S')}")
            flags["send"] = True
        if positions and len(positions) > 0:
            print("Position already open, skipping new order")
        else:
            if not flags["buy"]:
                send_order(symbol, LOT, DEVIATION, MAGIC_NUMBER, dry_run=DRY_RUN)
                flags["buy"] = True


def handle_close_signal(signal_close, symbol, flags):
    positions = mt5.positions_get(symbol=symbol)
    if signal_close == "Close":
        if not flags["send"]:
            send_telegram(f"📉 {symbol} EMA crossed down at {datetime.now().strftime('%H:%M:%S')}")
            flags["send"] = True
        if positions and len(positions) > 0:
            print("Closing position not implemented yet")
        else:
            print("No order to close")


def main_loop():
    send_telegram("Trader Alpha 1.1 is Starting!")
    if not connect_mt5():
        return

    flags = {
        "trailing": False,
        "send": False,
        "buy": False,
        "sell": False
    }
    last_minute_run = 0

    try:
        while True:
            df = get_data()
            if df is None:
                time.sleep(10)
                continue

            ema8 = calc_ema(df, 8)
            ema20 = calc_ema(df, 20)
            signal = check_signal(ema8, ema20)
            signal_close = check_signal_close(ema8, ema20)

            positions = mt5.positions_get(symbol=STRATEGY_SYMBOL)
            current_min = int(time.time() / 60)
            last_minute_run, flags = reset_flags_if_new_minute(current_min, last_minute_run, flags)

            handle_trailing(STRATEGY_SYMBOL, positions, flags)
            handle_buy_signal(signal, STRATEGY_SYMBOL, flags)
            handle_close_signal(signal_close, STRATEGY_SYMBOL, flags)

            # Clear console + print status
            os.system("cls" if os.name == "nt" else "clear")
            print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Price: {df['close'].iloc[-1]:.2f}")
            print(f"EMA8: {ema8[-1]:.2f}, EMA20: {ema20[-1]:.2f}")
            print(f"Signal: {signal or 'None'}, Close Signal: {signal_close or 'None'}")
            print(f"Positions: {positions}")
            print(f"Flags: {flags}")
            time.sleep(1)

    except KeyboardInterrupt:
        print("Bot stopped by user")
    finally:
        mt5.shutdown()
        send_telegram("Trader Alpha 1.1 Shutdown")



# ===============================
# Entry Point
# ===============================
if __name__ == "__main__":
    main_loop()
