from flask import Flask, render_template, request, redirect, url_for, jsonify
import threading
import pandas as pd
import numpy as np
import yfinance as yf
import time
import os
from datetime import datetime
import smtplib
from email.mime.text import MIMEText

app = Flask(__name__)
logs = []
running = False
scanner_thread = None
stock_file_path = "fno_list.txt"
signals_file = "buy_signals.csv"
email_file = "email.txt"

# === Replace these with your sender details ===
EMAIL_SENDER = "projparesh@gmail.com"
EMAIL_PASSWORD = "kcomjionidkoakcj"

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_msg = f"[{timestamp}] {message}"
    logs.append(full_msg)
    if len(logs) > 500:
        logs.pop(0)

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def to_scalar(value):
    try:
        if hasattr(value, "item"):
            return value.item()
        elif isinstance(value, (pd.Series, np.ndarray)):
            return float(value.values[0])
        else:
            return float(value)
    except Exception:
        return None

def load_stock_list():
    if os.path.exists(stock_file_path):
        with open(stock_file_path, "r") as f:
            return [line.strip() for line in f if line.strip()]
    return []

def get_email_recipient():
    if os.path.exists(email_file):
        with open(email_file, "r") as f:
            return f.read().strip()
    return ""

def send_email_alert(symbols):
    recipient = get_email_recipient()
    if not recipient:
        log("📭 No email address saved. Skipping email alert.")
        return

    body = "Buy signals generated for the following symbols:\n\n"
    body += "\n".join(symbols)

    msg = MIMEText(body)
    msg["Subject"] = "NSE F&O Buy Signal Alert"
    msg["From"] = EMAIL_SENDER
    msg["To"] = recipient

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        log(f"📧 Email alert sent to {recipient}")
    except Exception as e:
        log(f"❌ Email sending failed: {e}")

def run_scan_loop():
    global running
    while running:
        run_scan()
        for _ in range(900):  # 15-minute wait
            if not running:
                break
            time.sleep(1)

def run_scan():
    log("Scanner cycle started.")
    stock_list = load_stock_list()
    signals = []
    symbols_triggered = []

    for symbol in stock_list:
        try:
            log(f"📡 Scanning {symbol}...")
            data_15 = yf.download(symbol, interval="15m", period="3d", progress=False, auto_adjust=False)
            data_30 = yf.download(symbol, interval="30m", period="5d", progress=False, auto_adjust=False)
            data_1d = yf.download(symbol, interval="1d", period="7d", progress=False, auto_adjust=False)

            if data_15.empty or data_30.empty or data_1d.empty:
                log(f"⚠️ No data for {symbol}")
                continue

            if len(data_15) < 40 or len(data_30) < 15 or len(data_1d) < 2:
                log(f"⚠️ Insufficient data for {symbol}")
                continue

            today_close = to_scalar(data_1d['Close'].iloc[-1])
            max_15_high = to_scalar(data_15['High'].iloc[-39:-1].max())
            if today_close is None or max_15_high is None or today_close < max_15_high:
                log(f"ℹ️ {symbol} failed breakout check.")
                continue

            rsi_15 = rsi(data_15['Close']).dropna()
            if len(rsi_15) < 40:
                log(f"⚠️ Insufficient RSI(15) for {symbol}")
                continue
            current_rsi_15 = to_scalar(rsi_15.iloc[-1])
            prev_rsi_15 = rsi_15.iloc[-40:-1].dropna()
            max_rsi_prev_38 = to_scalar(prev_rsi_15.max())
            max_rsi_last_21 = to_scalar(prev_rsi_15[-21:].max())

            if None in [current_rsi_15, max_rsi_prev_38, max_rsi_last_21]:
                log(f"⚠️ Invalid RSI(15) for {symbol}")
                continue
            if current_rsi_15 > max_rsi_prev_38 or max_rsi_last_21 <= 65 or max_rsi_prev_38 >= 81:
                log(f"ℹ️ {symbol} failed RSI(15) check.")
                continue

            rsi_30 = rsi(data_30['Close']).dropna()
            if len(rsi_30) < 10:
                log(f"⚠️ Insufficient RSI(30) for {symbol}")
                continue
            current_rsi_30 = to_scalar(rsi_30.iloc[-1])
            sma_rsi_30 = to_scalar(rsi_30.rolling(10).mean().iloc[-1])
            if None in [current_rsi_30, sma_rsi_30] or current_rsi_30 > sma_rsi_30 or current_rsi_30 < 0.97 * sma_rsi_30:
                log(f"ℹ️ {symbol} failed RSI(30) check.")
                continue

            log(f"✅ Buy Signal: {symbol}")
            signals.append((datetime.now(), symbol))
            symbols_triggered.append(symbol)

        except Exception as e:
            log(f"❌ Error with {symbol}: {e}")

    if signals:
        df = pd.DataFrame(signals, columns=["Time", "Symbol"])
        df.to_csv(signals_file, mode='a', header=not os.path.exists(signals_file), index=False)
        send_email_alert(symbols_triggered)

@app.route("/")
def index():
    email = get_email_recipient()
    return render_template("index.html", email=email)

@app.route("/logs")
def get_logs():
    return jsonify(logs)

@app.route("/start", methods=["POST"])
def start():
    global running, scanner_thread
    if not running:
        running = True
        scanner_thread = threading.Thread(target=run_scan_loop)
        scanner_thread.start()
        log("✅ Scanner started.")
    return redirect(url_for("index"))

@app.route("/stop", methods=["POST"])
def stop():
    global running
    running = False
    log("⛔ Scanner stopped.")
    return redirect(url_for("index"))

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    if file:
        file.save(stock_file_path)
        log("📁 Stock list updated via upload.")
    return redirect(url_for("index"))

@app.route("/save_email", methods=["POST"])
def save_email():
    email = request.form.get("email")
    if email:
        with open(email_file, "w") as f:
            f.write(email)
        log(f"📧 Email saved: {email}")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)
