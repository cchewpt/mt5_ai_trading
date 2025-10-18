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
# -------------------------
# Load Config
# -------------------------
def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

TF_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1
}

# -------------------------
# MT5 init
# -------------------------
def mt5_initialize(cfg):
    if not mt5.initialize():
        print("mt5.initialize() failed")
        return False
    if cfg.get("login"):
        ok = mt5.login(cfg["login"], password=cfg.get("password"), server=cfg.get("server"))
        if not ok:
            print("mt5.login failed:", mt5.last_error())
            return False
    info = mt5.account_info()
    print("✅ MT5 initialized. Account:", info.login if info else "N/A")
    return True

# -------------------------
# Fetch OHLCV
# -------------------------
def fetch_ohlcv(symbol, timeframe, n=1000):
    tf = TF_MAP.get(timeframe.upper(), mt5.TIMEFRAME_M15)
    utc_to = datetime.now(timezone.utc)
    utc_from = utc_to - timedelta(days=365)
    rates = mt5.copy_rates_from(symbol, tf, utc_from, n)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    return df

# -------------------------
# Indicators
# -------------------------
def compute_indicators(df, cfg):
    df = df.copy()
    df['ema_fast'] = ta.ema(df['close'], length=cfg['strategy']['ema_fast'])
    df['ema_slow'] = ta.ema(df['close'], length=cfg['strategy']['ema_slow'])
    macd = ta.macd(df['close'], fast=cfg['strategy']['macd_fast'],
                   slow=cfg['strategy']['macd_slow'],
                   signal=cfg['strategy']['macd_signal'])
    df['macd'] = macd.iloc[:, 0]
    df['macd_sig'] = macd.iloc[:, 1]
    df['rsi'] = ta.rsi(df['close'], length=cfg['strategy']['rsi_period'])
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=cfg['strategy']['atr_period'])
    return df

# -------------------------
# Generate signal
# -------------------------
def generate_signal(latest, cfg):
    score = 0
    s = latest
    if s['ema_fast'] > s['ema_slow']:
        score += 1
    if s['macd'] > s['macd_sig']:
        score += 1
    if 45 < s['rsi'] < 75:
        score += 1
    if s['close'] > s['ema_fast']:
        score += 1
    if score >= 3:
        side = 'BUY'
    else:
        score_b = 0
        if s['ema_fast'] < s['ema_slow']:
            score_b += 1
        if s['macd'] < s['macd_sig']:
            score_b += 1
        if 25 < s['rsi'] < 55:
            score_b += 1
        if s['close'] < s['ema_fast']:
            score_b += 1
        if score_b >= 3:
            side = 'SELL'
        else:
            return None

    atr = s['atr'] if not pd.isna(s['atr']) and s['atr'] > 0 else 0.0001
    if side == 'BUY':
        sl = s['close'] - cfg['strategy']['atr_k'] * atr
        tp = s['close'] + cfg['strategy']['tp_r'] * (s['close'] - sl)
    else:
        sl = s['close'] + cfg['strategy']['atr_k'] * atr
        tp = s['close'] - cfg['strategy']['tp_r'] * (sl - s['close'])
    return {
        'symbol': cfg['strategy']['symbol'],
        'side': side,
        'entry_price': s['close'],
        'sl': sl,
        'tp': tp,
        'open_time': datetime.now(timezone.utc).isoformat()
    }

# -------------------------
# JSON logging helpers
# -------------------------
def load_trade_log(filename="trades_log.json"):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return []

def save_trade_log(data, filename="trades_log.json"):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

# -------------------------
# Main loop
# -------------------------
def main():
    cfg = load_config("config.yaml")
    if not mt5_initialize(cfg['mt5']):
        print("MT5 init failed")
        return

    symbol = cfg['strategy']['symbol']
    timeframe = cfg['strategy']['timeframe']
    df = fetch_ohlcv(symbol, timeframe, n=1000)
    df = compute_indicators(df, cfg)

    trade_log = load_trade_log()
    open_positions = []

    print(f"🚀 Starting auto loop on {symbol} ({timeframe})...")
    last_bar_time = df.index[-1]

    while True:
        df = fetch_ohlcv(symbol, timeframe, n=1000)
        df = compute_indicators(df, cfg)
        latest = df.iloc[-1]
        now_bar_time = df.index[-1]

        # new candle
        if now_bar_time > last_bar_time:
            print(f"\n🕐 New bar: {now_bar_time}")
            last_bar_time = now_bar_time

            signal = generate_signal(latest, cfg)
            if signal:
                print(f"📈 New signal: {signal['side']} at {signal['entry_price']:.5f}")
                open_positions.append(signal)

        # simulate TP/SL
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            current_price = tick.bid if len(open_positions) and open_positions[0]['side'] == 'SELL' else tick.ask

            for pos in open_positions[:]:
                side = pos['side']
                hit_tp = hit_sl = False
                if side == 'BUY':
                    if current_price >= pos['tp']:
                        hit_tp = True
                    elif current_price <= pos['sl']:
                        hit_sl = True
                else:
                    if current_price <= pos['tp']:
                        hit_tp = True
                    elif current_price >= pos['sl']:
                        hit_sl = True

                if hit_tp or hit_sl:
                    pos['exit_price'] = current_price
                    pos['close_time'] = datetime.now(timezone.utc).isoformat()
                    pos['profit_pips'] = (pos['exit_price'] - pos['entry_price']) * (10000 if "JPY" not in pos['symbol'] else 100)
                    pos['profit_usd'] = pos['profit_pips'] * 1  # assume $1/pip per 0.1 lot for paper
                    pos['result'] = "TP" if hit_tp else "SL"
                    trade_log.append(pos)
                    open_positions.remove(pos)
                    save_trade_log(trade_log)
                    print(f"✅ Closed {side} trade at {pos['exit_price']:.5f} ({pos['result']})")

        time.sleep(5)  # check every 5s

if __name__ == "__main__":
    main()
