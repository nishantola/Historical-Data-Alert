"""
Holdings Daily P&L Tracker Strategy
Tracks day-wise P&L based on previous day close vs current day close
Posts result to Slack
"""

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from growwapi import GrowwAPI
import pyotp


# ================= SLACK CONFIG =================
def send_slack_alert(message: str):
    webhook = os.getenv("SLACK_WEBHOOK")  # 👈 Read from GitHub ENV

    if not webhook:
        print("Slack webhook not set in environment variables.")
        return

    payload = {
        "text": message
    }

    try:
        response = requests.post(webhook, json=payload)

        if response.status_code != 200:
            print("Slack notification failed")
            print("Status Code:", response.status_code)
            print("Response:", response.text)
        else:
            print("Slack message sent successfully")

    except Exception as e:
        print("Slack error:", e)
    


# ================= AUTH CONFIG =================

# ===== AUTHENTICATION CONFIG =====
AUTH_CONFIG = {
    "api_key": os.getenv("API_KEY"),
    "totp_secret": os.getenv("TOTP_SECRET"),
}

# ================= STRATEGY CONFIG =================

STRATEGY_CONFIG = {
    "holdings": [
        {
            "symbol": "GROWW",
            "exchange": "NSE",
            "quantity": 3458,
            "average_price": 217.0
        },
        {
            "symbol": "PFOCUS",
            "exchange": "NSE",
            "quantity": 155,
            "average_price": 255.0
        },
        {
            "symbol": "CDSL",
            "exchange": "NSE",
            "quantity": 20,
            "average_price": 1167.0
        },
        {
            "symbol": "NSDL",
            "exchange": "BSE",
            "quantity": 20,
            "average_price": 815.0
        }
    ]
}


# ================= BACKTEST CONFIG =================

BACKTEST_CONFIG = {
    "start_date": (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d 09:15:00'),
    "end_date": datetime.now().strftime('%Y-%m-%d 15:30:00'),
    "candle_interval": "1day",
}

MODE = "backtest"


# ================= HELPER FUNCTIONS =================

def get_groww_symbol(exchange: str, trading_symbol: str) -> str:
    return f"{exchange}-{trading_symbol}"


def fetch_historical_data(
    groww_client,
    exchange,
    segment,
    groww_symbol,
    start_time,
    end_time,
    candle_interval
) -> pd.DataFrame:

    response = groww_client.get_historical_candles(
        exchange=exchange,
        segment=segment,
        groww_symbol=groww_symbol,
        start_time=start_time,
        end_time=end_time,
        candle_interval=candle_interval
    )

    candles = response.get('candles', [])
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(
        candles,
        columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi']
    )
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


# ================= STRATEGY =================

class BacktestStrategy:

    def __init__(self, groww, config, backtest_config):
        self.groww = groww
        self.holdings = config["holdings"]
        self.backtest_config = backtest_config
        self.historical_data = {}

    def fetch_data(self, symbol, exchange, start, end):
        groww_symbol = get_groww_symbol(exchange, symbol)

        start_dt = datetime.strptime(start, '%Y-%m-%d %H:%M:%S')
        adjusted_start = (start_dt - timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S')

        df = fetch_historical_data(
            groww_client=self.groww,
            exchange=self.groww.EXCHANGE_NSE,
            segment=self.groww.SEGMENT_CASH,
            groww_symbol=groww_symbol,
            start_time=adjusted_start,
            end_time=end,
            candle_interval=self.groww.CANDLE_INTERVAL_DAY
        )

        return df

    def run(self):

        report_lines = []
        report_lines.append("📊 *DAILY HOLDINGS P&L REPORT*")
        report_lines.append("=" * 60)

        for holding in self.holdings:

            symbol = holding["symbol"]
            quantity = holding["quantity"]

            df = self.fetch_data(
                symbol=symbol,
                exchange=holding["exchange"],
                start=self.backtest_config["start_date"],
                end=self.backtest_config["end_date"]
            )

            if df.empty:
                report_lines.append(f"⚠ No data for {symbol}")
                continue

            df = df.sort_values("timestamp")

            start_date = datetime.strptime(
                self.backtest_config["start_date"],
                '%Y-%m-%d %H:%M:%S'
            ).date()

            df = df[df['timestamp'].dt.date >= start_date]

            report_lines.append(f"\n🔹 *{symbol}*")

            for i in range(1, len(df)):

                prev_close = df.iloc[i-1]["close"]
                current_close = df.iloc[i]["close"]
                date = df.iloc[i]["timestamp"].date()

                day_pnl = (current_close - prev_close) * quantity

                emoji = "🟢" if day_pnl >= 0 else "🔴"

                report_lines.append(
                    f"{date.strftime('%d-%b-%Y')} | "
                    f"Prev: ₹{prev_close:.2f} → "
                    f"Close: ₹{current_close:.2f} | "
                    f"{emoji} Day P&L: ₹{day_pnl:,.2f}"
                )

        final_report = "\n".join(report_lines)

        print(final_report)
        send_slack_alert(final_report)

# ================= AUTH =================

def authenticate():
    try:
        totp_gen = pyotp.TOTP(AUTH_CONFIG["totp_secret"])
        totp = totp_gen.now()

        access_token = GrowwAPI.get_access_token(
            api_key=AUTH_CONFIG["api_key"],
            totp=totp
        )

        return GrowwAPI(access_token)

    except Exception as e:
        print("Authentication failed:", e)
        raise


# ================= MAIN =================

if __name__ == "__main__":
    send_slack_alert("✅ Test message from Holdings P&L script")

    groww = authenticate()

    if MODE == "backtest":
        strategy = BacktestStrategy(
            groww,
            STRATEGY_CONFIG,
            BACKTEST_CONFIG
        )
        strategy.run()
    else:
        print("Only backtest mode supported.")

