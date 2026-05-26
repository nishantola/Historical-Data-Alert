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
    webhook = os.getenv("SLACK_WEBHOOK")
    if not webhook:
        print("Slack webhook not set in environment variables.")
        return
    payload = {"text": message}
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
            "quantity": 35,
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

def get_api_exchange(groww_client, exchange: str):
    if exchange == "NSE":
        return groww_client.EXCHANGE_NSE
    elif exchange == "BSE":
        return groww_client.EXCHANGE_BSE
    else:
        raise ValueError(f"Unsupported exchange: {exchange}")

def probe_symbol(groww_client, display_name: str, test_end: str):
    """
    Tries all likely symbol formats for a BSE stock and returns the first one
    that gives back candle data. Prints a clear diagnostic table.
    """
    test_start = (
        datetime.strptime(test_end, '%Y-%m-%d %H:%M:%S') - timedelta(days=10)
    ).strftime('%Y-%m-%d %H:%M:%S')

    # Candidate formats to try, in priority order
    candidates = [
        ("BSE", "NSE",  display_name),          # maybe dual-listed on NSE
        ("BSE", "BSE",  display_name),           # BSE-NSDL  (original)
        ("BSE", "BSE",  "544185"),               # BSE scrip code
        ("BSE", "BSE",  display_name.upper()),   # uppercase just in case
    ]

    print(f"\n{'─'*60}")
    print(f"  Probing symbol formats for {display_name}:")
    print(f"{'─'*60}")

    for orig_exchange, try_exchange, try_symbol in candidates:
        groww_symbol = f"{try_exchange}-{try_symbol}"
        api_exchange = get_api_exchange(groww_client, try_exchange)
        try:
            response = groww_client.get_historical_candles(
                exchange=api_exchange,
                segment=groww_client.SEGMENT_CASH,
                groww_symbol=groww_symbol,
                start_time=test_start,
                end_time=test_end,
                candle_interval=groww_client.CANDLE_INTERVAL_DAY
            )
            count = len(response.get("candles", []))
            status = response.get("status", "?")
            marker = "✅ HIT" if count > 0 else "❌ empty"
            print(f"  {marker}  groww_symbol={groww_symbol:<20} "
                  f"exchange={try_exchange}  status={status}  candles={count}")
            if count > 0:
                print(f"{'─'*60}")
                return try_exchange, try_symbol   # caller uses this pair
        except Exception as e:
            print(f"  💥 ERR   groww_symbol={groww_symbol:<20} error={e}")

    print(f"{'─'*60}")
    print(f"  ⚠ All formats failed for {display_name}. "
          f"Check if the stock is supported by GrowwAPI.")
    print(f"{'─'*60}")
    return None, None

def fetch_historical_data(
    groww_client,
    exchange,
    segment,
    groww_symbol,
    start_time,
    end_time,
    candle_interval
) -> pd.DataFrame:
    try:
        response = groww_client.get_historical_candles(
            exchange=exchange,
            segment=segment,
            groww_symbol=groww_symbol,
            start_time=start_time,
            end_time=end_time,
            candle_interval=candle_interval
        )
    except Exception as e:
        print(f"  [ERROR] API call failed for {groww_symbol}: {e}")
        return pd.DataFrame()

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

    def fetch_data(self, symbol, exchange, start, end):
        groww_symbol = f"{exchange}-{symbol}"
        start_dt = datetime.strptime(start, '%Y-%m-%d %H:%M:%S')
        adjusted_start = (start_dt - timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S')
        api_exchange = get_api_exchange(self.groww, exchange)

        df = fetch_historical_data(
            groww_client=self.groww,
            exchange=api_exchange,
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

        total_pnl_by_date = {}

        for holding in self.holdings:
            symbol = holding["symbol"]
            exchange = holding["exchange"]
            quantity = holding["quantity"]
            display_name = holding.get("display_name", symbol)

            # ── Try the configured symbol first ──────────────────────────
            df = self.fetch_data(
                symbol=symbol,
                exchange=exchange,
                start=self.backtest_config["start_date"],
                end=self.backtest_config["end_date"]
            )

            # ── If empty, auto-probe alternative formats ─────────────────
            if df.empty:
                print(f"\n[INFO] No data for {display_name} with "
                      f"{exchange}-{symbol}. Running format probe...")
                resolved_exchange, resolved_symbol = probe_symbol(
                    self.groww,
                    display_name,
                    self.backtest_config["end_date"]
                )
                if resolved_symbol:
                    print(f"[INFO] Using resolved format: "
                          f"{resolved_exchange}-{resolved_symbol}")
                    df = self.fetch_data(
                        symbol=resolved_symbol,
                        exchange=resolved_exchange,
                        start=self.backtest_config["start_date"],
                        end=self.backtest_config["end_date"]
                    )

            if df.empty:
                report_lines.append(
                    f"\n⚠ No data for {display_name} "
                    f"({exchange}:{symbol}) — check console for probe results"
                )
                continue

            df = df.sort_values("timestamp")
            start_date = datetime.strptime(
                self.backtest_config["start_date"], '%Y-%m-%d %H:%M:%S'
            ).date()
            df = df[df['timestamp'].dt.date >= start_date]

            if df.empty:
                report_lines.append(
                    f"\n⚠ Data fetched but all rows predate start_date "
                    f"for {display_name}"
                )
                continue

            report_lines.append(f"\n🔹 *{display_name}*")

            for i in range(1, len(df)):
                prev_close     = df.iloc[i - 1]["close"]
                current_close  = df.iloc[i]["close"]
                date           = df.iloc[i]["timestamp"].date()
                day_pnl        = (current_close - prev_close) * quantity
                emoji          = "🟢" if day_pnl >= 0 else "🔴"

                report_lines.append(
                    f"{date.strftime('%d-%b-%Y')} | "
                    f"Prev: ₹{prev_close:.2f} → "
                    f"Close: ₹{current_close:.2f} | "
                    f"{emoji} Day P&L: ₹{day_pnl:,.2f}"
                )

                total_pnl_by_date[date] = (
                    total_pnl_by_date.get(date, 0) + day_pnl
                )

        # Portfolio daily summary
        if total_pnl_by_date:
            report_lines.append("\n" + "=" * 60)
            report_lines.append("📈 *PORTFOLIO SUMMARY*")
            for date in sorted(total_pnl_by_date):
                total = total_pnl_by_date[date]
                emoji = "🟢" if total >= 0 else "🔴"
                report_lines.append(
                    f"{date.strftime('%d-%b-%Y')} | "
                    f"{emoji} Total P&L: ₹{total:,.2f}"
                )

        final_report = "\n".join(report_lines)
        print("\n" + final_report)
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
        strategy = BacktestStrategy(groww, STRATEGY_CONFIG, BACKTEST_CONFIG)
        strategy.run()
    else:
        print("Only backtest mode supported.")
