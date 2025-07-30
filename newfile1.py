import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import time
import os
import traceback

class StockScannerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NSE F&O Stock Breakout Scanner")
        self.running = False
        self.stock_file_path = "fno_list.txt"
        self.log_file = open("scanner_log.txt", "a")
        self.create_widgets()
        self.load_stock_list()

    def create_widgets(self):
        frame = ttk.Frame(self.root)
        frame.pack(padx=10, pady=10)

        self.start_btn = ttk.Button(frame, text="Start", command=self.start_scanner)
        self.start_btn.grid(row=0, column=0, padx=5)

        self.stop_btn = ttk.Button(frame, text="Stop", command=self.stop_scanner)
        self.stop_btn.grid(row=0, column=1, padx=5)

        self.exit_btn = ttk.Button(frame, text="Exit", command=self.root.quit)
        self.exit_btn.grid(row=0, column=2, padx=5)

        self.upload_btn = ttk.Button(frame, text="Update Stock List", command=self.update_stock_file)
        self.upload_btn.grid(row=0, column=3, padx=5)

        self.log_text = scrolledtext.ScrolledText(self.root, width=100, height=25)
        self.log_text.pack(padx=10, pady=(10, 5))

        self.progress_label = ttk.Label(self.root, text="Progress: 0/0")
        self.progress_label.pack(padx=10, anchor='w')

        self.progress_bar = ttk.Progressbar(self.root, length=700, mode='determinate')
        self.progress_bar.pack(padx=10, pady=(0, 10))

    def load_stock_list(self):
        if os.path.exists(self.stock_file_path):
            with open(self.stock_file_path, "r") as f:
                self.stock_list = [line.strip() for line in f if line.strip()]
        else:
            self.stock_list = []

    def update_stock_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("Text Files", "*.txt")])
        if file_path:
            self.stock_file_path = file_path
            self.load_stock_list()
            messagebox.showinfo("Success", "Stock list updated!")

    def start_scanner(self):
        if not self.running:
            self.running = True
            self.log("Scanner started.")
            self.thread = threading.Thread(target=self.scan_loop)
            self.thread.start()

    def stop_scanner(self):
        self.running = False
        self.log("Scanner stopped.")

    def log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_msg = f"[{timestamp}] {message}"
        self.log_text.insert(tk.END, full_msg + "\n")
        self.log_text.see(tk.END)
        self.log_file.write(full_msg + "\n")
        self.log_file.flush()

    def scan_loop(self):
        while self.running:
            self.run_scan()
            for _ in range(900):  # 15-minute wait
                if not self.running:
                    break
                time.sleep(1)

    def rsi(self, series, period=14):
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def to_scalar(self, value):
        try:
            if hasattr(value, "item"):
                return value.item()
            elif isinstance(value, (pd.Series, np.ndarray)):
                return float(value.values[0])
            else:
                return float(value)
        except Exception:
            return None

    def run_scan(self):
        signals = []
        total = len(self.stock_list)
        self.progress_bar['value'] = 0
        self.progress_bar['maximum'] = total
        self.progress_label.config(text=f"Progress: 0/{total}")
        self.root.update_idletasks()

        for i, symbol in enumerate(self.stock_list, start=1):
            self.log(f"📡 Scanning {symbol}...")

            try:
                data_15 = yf.download(symbol, interval="15m", period="3d", progress=False, auto_adjust=False)
                data_30 = yf.download(symbol, interval="30m", period="5d", progress=False, auto_adjust=False)
                data_1d = yf.download(symbol, interval="1d", period="7d", progress=False, auto_adjust=False)

                if data_15.empty or data_30.empty or data_1d.empty:
                    self.log(f"⚠️ No data for {symbol}, skipping.")
                    continue

                if len(data_15) < 40 or len(data_30) < 15 or len(data_1d) < 2:
                    self.log(f"⚠️ Not enough data for {symbol}, skipping.")
                    continue

                today_close = self.to_scalar(data_1d['Close'].iloc[-1])
                max_15_high = self.to_scalar(data_15['High'].iloc[-39:-1].max())
                if today_close is None or max_15_high is None:
                    self.log(f"⚠️ Price data missing for {symbol}")
                    continue
                if today_close < max_15_high:
                    self.log(f"ℹ️ {symbol} failed breakout check.")
                    continue

                self.log(f"✅ {symbol} passed breakout check")

                rsi_15 = self.rsi(data_15['Close']).dropna()
                if len(rsi_15) < 40:
                    self.log(f"⚠️ Insufficient RSI(15) for {symbol}")
                    continue
                current_rsi_15 = self.to_scalar(rsi_15.iloc[-1])
                prev_rsi_15 = rsi_15.iloc[-40:-1].dropna()
                max_rsi_prev_38 = self.to_scalar(prev_rsi_15.max())
                max_rsi_last_21 = self.to_scalar(prev_rsi_15[-21:].max())

                if None in [current_rsi_15, max_rsi_prev_38, max_rsi_last_21]:
                    self.log(f"⚠️ RSI(15) values invalid for {symbol}")
                    continue
                if current_rsi_15 > max_rsi_prev_38 or max_rsi_last_21 <= 65 or max_rsi_prev_38 >= 81:
                    self.log(f"ℹ️ {symbol} failed RSI(15) check.")
                    continue

                rsi_30 = self.rsi(data_30['Close']).dropna()
                if len(rsi_30) < 10:
                    self.log(f"⚠️ Insufficient RSI(30) for {symbol}")
                    continue
                current_rsi_30 = self.to_scalar(rsi_30.iloc[-1])
                sma_rsi_30 = self.to_scalar(rsi_30.rolling(10).mean().iloc[-1])
                if None in [current_rsi_30, sma_rsi_30]:
                    self.log(f"⚠️ RSI(30) SMA data invalid for {symbol}")
                    continue
                if current_rsi_30 > sma_rsi_30 or current_rsi_30 < 0.97 * sma_rsi_30:
                    self.log(f"ℹ️ {symbol} failed RSI(30) check.")
                    continue

                self.log(f"✅ Buy Signal: {symbol}")
                signals.append((datetime.now(), symbol))

            except Exception as e:
                self.log(f"❌ Error fetching {symbol}: {e}")
                traceback.print_exc()

            self.progress_bar['value'] = i
            self.progress_label.config(text=f"Progress: {i}/{total}")
            self.root.update_idletasks()

        if signals:
            df_signals = pd.DataFrame(signals, columns=["Time", "Symbol"])
            df_signals.to_csv("buy_signals.csv", mode="a", header=not os.path.exists("buy_signals.csv"), index=False)

if __name__ == "__main__":
    root = tk.Tk()
    app = StockScannerApp(root)
    root.mainloop()
