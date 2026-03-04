import pandas as pd
from datetime import datetime, timedelta
import time
import pyotp
from growwapi import GrowwAPI
import pytz
import requests
import os

# ================= SLACK CONFIG =================

# 🔴 FOR LOCAL TESTING (paste webhook directly)
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")  # Use env variable if set

def send_slack_alert(message):
    payload = {"text": message}
    try:
        response = requests.post(SLACK_WEBHOOK, json=payload)
        if response.status_code != 200:
            print("Slack notification failed:", response.text)
    except Exception as e:
        print("Slack error:", e)

# ===== AUTHENTICATION CONFIG =====

AUTH_CONFIG = {
    "api_key": os.getenv("API_KEY"),
    "totp_secret": os.getenv("TOTP_SECRET"),
}



def authenticate():
    totp = pyotp.TOTP(AUTH_CONFIG["totp_secret"]).now()
    access_token = GrowwAPI.get_access_token(
        api_key=AUTH_CONFIG["api_key"],
        totp=totp
    )
    return GrowwAPI(access_token)

# ================= VALIDATION CONFIG =================


SYMBOLS = [
        "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTY", "NIFTYNXT50",
        "360ONE", "ABB", "ABCAPITAL", "ADANIENSOL", "ADANIENT", "ADANIGREEN", "ADANIPORTS",
        "ALKEM", "AMBER", "AMBUJACEM", "ANGELONE", "APLAPOLLO", "APOLLOHOSP", "ASHOKLEY",
        "ASIANPAINT", "ASTRAL", "AUBANK", "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV",
        "BAJAJHLDNG", "BAJFINANCE", "BANDHANBNK", "BANKBARODA", "BANKINDIA", "BDL", "BEL",
        "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON", "BLUESTARCO", "BOSCHLTD", "BPCL",
        "BRITANNIA", "BSE", "CAMS", "CANBK", "CDSL", "CGPOWER", "CHOLAFIN", "CIPLA",
        "COALINDIA", "COFORGE", "COLPAL", "CONCOR", "CROMPTON", "CUMMINSIND", "DABUR",
        "DALBHARAT", "DELHIVERY", "DIVISLAB", "DIXON", "DLF", "DMART", "DRREDDY",
        "EICHERMOT", "ETERNAL", "EXIDEIND", "FEDERALBNK", "FORTIS", "GAIL", "GLENMARK",
        "GMRAIRPORT", "GODREJCP", "GODREJPROP", "GRASIM", "HAL", "HAVELLS", "HCLTECH",
        "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDPETRO", "HINDUNILVR",
        "HINDZINC", "HUDCO", "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA", "IDFCFIRSTB",
        "IEX", "INDHOTEL", "INDIANB", "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY",
        "INOXWIND", "IOC", "IRCTC", "IREDA", "IRFC", "ITC", "JINDALSTEL", "JIOFIN",
        "JSWENERGY", "JSWSTEEL", "JUBLFOOD", "KALYANKJIL", "KAYNES", "KEI", "KFINTECH",
        "KOTAKBANK", "KPITTECH", "LAURUSLABS", "LICHSGFIN", "LICI", "LODHA", "LT",
        "LTF", "LTIM", "LUPIN", "M&M", "MANAPPURAM", "MANKIND", "MARICO", "MARUTI",
        "MAXHEALTH", "MAZDOCK", "MCX", "MFSL", "MOTHERSON", "MPHASIS", "MUTHOOTFIN",
        "NATIONALUM", "NAUKRI", "NBCC", "NESTLEIND", "NHPC", "NMDC", "NTPC", "NUVAMA",
        "NYKAA", "OBEROIRLTY", "OFSS", "OIL", "ONGC", "PAGEIND", "PATANJALI", "PAYTM",
        "PERSISTENT", "PETRONET", "PFC", "PGEL", "PHOENIXLTD", "PIDILITIND", "PIIND",
        "PNB", "PNBHOUSING", "POLICYBZR", "POLYCAB", "POWERGRID", "POWERINDIA", "PPLPHARMA",
        "PREMIERENE", "PRESTIGE", "RBLBANK", "RECLTD", "RELIANCE", "RVNL", "SAIL",
        "SAMMAANCAP", "SBICARD", "SBILIFE", "SBIN", "SHREECEM", "SHRIRAMFIN", "SIEMENS",
        "SOLARINDS", "SONACOMS", "SRF", "SUNPHARMA", "SUPREMEIND", "SUZLON", "SWIGGY",
        "SYNGENE", "TATACONSUM", "TATAELXSI", "TATAPOWER", "TATASTEEL", "TATATECH", "TCS",
        "TECHM", "TIINDIA", "TITAN", "TMPV", "TORNTPHARM", "TORNTPOWER", "TRENT",
        "TVSMOTOR", "ULTRACEMCO", "UNIONBANK", "UNITDSPR", "UNOMINDA", "UPL", "VBL",
        "VEDL", "VOLTAS", "WAAREEENER", "WIPRO", "YESBANK", "ZYDUSLIFE","SENSEX","BANKEX"
    ]

EXCHANGES = ["NSE", "BSE"]

# ================= HELPERS =================

def get_previous_trading_day():
    today = datetime.now()
    prev_day = today - timedelta(days=1)

    while prev_day.weekday() >= 5:
        prev_day -= timedelta(days=1)

    return prev_day

# ================= DATA FETCH =================

def fetch_previous_day_candle(groww, symbol, exchange, start_dt, end_dt):

    groww_symbol = f"{exchange}-{symbol}"

    try:
        response = groww.get_historical_candles(
            exchange=exchange,
            segment=groww.SEGMENT_CASH,
            groww_symbol=groww_symbol,
            start_time=start_dt.strftime('%Y-%m-%d %H:%M:%S'),
            end_time=end_dt.strftime('%Y-%m-%d %H:%M:%S'),
            candle_interval=groww.CANDLE_INTERVAL_DAY
        )

        candles = response.get("candles", [])

        if not candles:
            return pd.DataFrame()

        df = pd.DataFrame(
            candles,
            columns=["timestamp", "open", "high", "low", "close", "volume", "oi"]
        )

        df["timestamp"] = pd.to_datetime(df["timestamp"])

        return df

    except Exception as e:
        print(f"{exchange}-{symbol} fetch failed:", e)
        return pd.DataFrame()

# ================= EXPORT =================

def export_to_log(results):

    os.makedirs("Log", exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"Log/validation_report_{timestamp}.csv"

    pd.DataFrame(results).to_csv(filepath, index=False)

    print("Log saved:", filepath)

# ================= MAIN =================

def run_validation():

    send_slack_alert("🔵 Validator job started")

    groww = authenticate()

    prev_day = get_previous_trading_day()

    start_dt = prev_day.replace(hour=9, minute=15, second=0)
    end_dt = prev_day.replace(hour=16, minute=0, second=0)

    results = []

    for symbol in SYMBOLS:
        for exchange in EXCHANGES:

            print(f"Checking {exchange}-{symbol}")

            df = fetch_previous_day_candle(
                groww,
                symbol,
                exchange,
                start_dt,
                end_dt
            )

            if df.empty:
                status = "missing"
            else:
                status = "complete"

            results.append({
                "symbol": f"{exchange}-{symbol}",
                "date_checked": prev_day.date(),
                "status": status
            })

    # ===== SUMMARY =====

    complete = sum(r["status"] == "complete" for r in results)
    missing = sum(r["status"] == "missing" for r in results)

    message = f"""
📊 *Daily Historical Data Validation*

📅 Date Checked: {prev_day.date()}
📊 Total Instruments: {len(results)}

✅ Complete: {complete}
❌ Missing: {missing}
"""

    if missing > 0:
        message += "\n⚠ Missing Data:\n"
        for r in results:
            if r["status"] == "missing":
                message += f"\n• {r['symbol']}"

    send_slack_alert(message)

    export_to_log(results)

# ================= ENTRY =================

if __name__ == "__main__":
    try:
        run_validation()
    except Exception as e:
        send_slack_alert(f"❌ Validator crashed: {str(e)}")
        raise
