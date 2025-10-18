from flask import Flask, render_template, request, redirect, url_for
import threading
import bot  # import โค้ด bot.py ของคุณ
import time

app = Flask(__name__)

# ใช้ dict เก็บสถานะบอท
bot_status = {
    "running": False,
    "last_price": None,
    "ema8": None,
    "ema20": None,
    "signal": None,
    "positions": []
}

# ฟังก์ชัน run bot ใน thread
def run_bot_loop():
    bot_status["running"] = True
    while bot_status["running"]:
        df = bot.get_data()
        if df is not None:
            ema8 = bot.calc_ema(df, 8)
            ema20 = bot.calc_ema(df, 20)
            signal = bot.check_signal(ema8, ema20)
            signal_close = bot.check_signal_close(ema8, ema20)
            positions = bot.mt5.positions_get(symbol=bot.STRATEGY_SYMBOL)

            # update status
            bot_status["last_price"] = df['close'].iloc[-1]
            bot_status["ema8"] = ema8[-1]
            bot_status["ema20"] = ema20[-1]
            bot_status["signal"] = signal or signal_close
            bot_status["positions"] = positions

            # ตัวอย่าง trigger auto
            if signal == "BUY" and (not positions or len(positions)==0):
                bot.send_order(bot.STRATEGY_SYMBOL, bot.LOT, bot.DEVIATION, bot.MAGIC_NUMBER, dry_run=bot.DRY_RUN)
            elif signal_close == "Close" and positions:
                bot.close_when_EMA_cross(bot.STRATEGY_SYMBOL, bot.LOT, bot.DEVIATION, bot.MAGIC_NUMBER, positions)

        time.sleep(1)  # loop interval

@app.route("/")
def index():
    return render_template("index.html", status=bot_status)

@app.route("/start")
def start_bot():
    if not bot_status["running"]:
        threading.Thread(target=run_bot_loop, daemon=True).start()
    return redirect(url_for("index"))

@app.route("/stop")
def stop_bot():
    bot_status["running"] = False
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)
