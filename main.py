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


# ===== VALIDATION CONFIG =====
VALIDATION_CONFIG = {
    "symbols": [
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
    ],
    "exchange": ["NSE", "BSE"],
    "segment": "CASH",
    "candle_interval": "1day",
}

# ===== HELPER FUNCTIONS =====

def is_weekend(date_obj):
    """Check if date is Saturday (5) or Sunday (6)"""
    return date_obj.weekday() >= 5

def get_all_trading_days(start_date, end_date):
    """Generate list of all weekdays between start and end date"""
    current = start_date
    trading_days = []

    while current <= end_date:
        if not is_weekend(current):
            trading_days.append(current.date())
        current += timedelta(days=1)

    return trading_days

def split_date_range(start_date_str, end_date_str, max_days=180):
    """Split date range into chunks of max_days"""
    start_dt = datetime.strptime(start_date_str, '%Y-%m-%d %H:%M:%S')
    end_dt = datetime.strptime(end_date_str, '%Y-%m-%d %H:%M:%S')

    chunks = []
    current_start = start_dt

    while current_start < end_dt:
        chunk_end = min(current_start + timedelta(days=max_days), end_dt)
        chunks.append((
            current_start.strftime('%Y-%m-%d %H:%M:%S'),
            chunk_end.strftime('%Y-%m-%d %H:%M:%S')
        ))
        current_start = chunk_end

    return chunks

def fetch_historical_data_paginated(groww_client, symbol, exchange, start_dt, end_dt):
    """Fetch historical candle data with automatic pagination"""

    groww_symbol = f"{exchange}-{symbol}"

    # Split into 180-day chunks
    chunks = split_date_range(
        start_dt.strftime('%Y-%m-%d %H:%M:%S'),
        end_dt.strftime('%Y-%m-%d %H:%M:%S'),
        max_days=180
    )
    all_candles = []

    for i, (chunk_start, chunk_end) in enumerate(chunks):
        try:
            response = groww_client.get_historical_candles(
                exchange=exchange,
                segment=groww_client.SEGMENT_CASH,
                groww_symbol=groww_symbol,
                start_time=chunk_start,
                end_time=chunk_end,
                candle_interval=groww_client.CANDLE_INTERVAL_DAY
            )

            candles = response.get('candles', [])

            if candles:
                all_candles.extend(candles)

            # Rate limiting: max 3 requests/second for historical data
            time.sleep(0.34)

        except Exception as e:
            print(f"[{symbol}] ERROR fetching chunk {i+1}: {e}")
            continue

    if not all_candles:
        return pd.DataFrame()

    # Convert to DataFrame
    df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = df['timestamp'].dt.date

    # Remove duplicates and sort
    df = df.drop_duplicates(subset=['date'], keep='first')
    df = df.sort_values('timestamp').reset_index(drop=True)

    return df

def validate_data_completeness(df, start_date, end_date):
    """Check for missing dates in candle data"""

    # Get all expected trading days (weekdays)
    expected_days = get_all_trading_days(start_date, end_date)

    # Get actual dates from candle data
    actual_dates = set(df['date'].tolist())

    # Find missing dates
    missing_dates = [date for date in expected_days if date not in actual_dates]

    return missing_dates, expected_days

def categorize_missing_dates(missing_dates):
    """Categorize missing dates as weekdays or weekends"""
    weekday_missing = []
    weekend_missing = []

    for date in missing_dates:
        date_obj = datetime.combine(date, datetime.min.time())
        if is_weekend(date_obj):
            weekend_missing.append(date)
        else:
            weekday_missing.append(date)

    return weekday_missing, weekend_missing

def get_known_holidays():
    """Return comprehensive Indian market holidays (2020-2026)"""
    holidays = {
        # 2020
        datetime(2020, 1, 26).date(): "Republic Day",
        datetime(2020, 2, 21).date(): "Maha Shivratri",
        datetime(2020, 3, 10).date(): "Holi",
        datetime(2020, 4, 2).date(): "Ram Navami",
        datetime(2020, 4, 6).date(): "Mahavir Jayanti",
        datetime(2020, 4, 10).date(): "Good Friday",
        datetime(2020, 4, 14).date(): "Dr. Ambedkar Jayanti",
        datetime(2020, 5, 1).date(): "Maharashtra Day",
        datetime(2020, 5, 25).date(): "Id-Ul-Fitr",
        datetime(2020, 8, 1).date(): "Bakri Id",
        datetime(2020, 8, 15).date(): "Independence Day",
        datetime(2020, 10, 2).date(): "Gandhi Jayanti",
        datetime(2020, 10, 25).date(): "Dussehra",
        datetime(2020, 11, 14).date(): "Diwali",
        datetime(2020, 11, 16).date(): "Diwali",
        datetime(2020, 11, 30).date(): "Gurunanak Jayanti",
        datetime(2020, 12, 25).date(): "Christmas",

        # 2021
        datetime(2021, 1, 26).date(): "Republic Day",
        datetime(2021, 3, 11).date(): "Maha Shivratri",
        datetime(2021, 3, 29).date(): "Holi",
        datetime(2021, 4, 2).date(): "Good Friday",
        datetime(2021, 4, 14).date(): "Mahavir Jayanti",
        datetime(2021, 4, 21).date(): "Ram Navami",
        datetime(2021, 5, 13).date(): "Id-Ul-Fitr",
        datetime(2021, 7, 21).date(): "Bakri Id",
        datetime(2021, 8, 15).date(): "Independence Day",
        datetime(2021, 8, 19).date(): "Muharram",
        datetime(2021, 9, 10).date(): "Ganesh Chaturthi",
        datetime(2021, 10, 2).date(): "Gandhi Jayanti",
        datetime(2021, 10, 15).date(): "Dussehra",
        datetime(2021, 11, 4).date(): "Diwali",
        datetime(2021, 11, 5).date(): "Diwali",
        datetime(2021, 11, 19).date(): "Gurunanak Jayanti",

        # 2022
        datetime(2022, 1, 26).date(): "Republic Day",
        datetime(2022, 3, 1).date(): "Maha Shivratri",
        datetime(2022, 3, 18).date(): "Holi",
        datetime(2022, 4, 14).date(): "Dr. Ambedkar Jayanti",
        datetime(2022, 4, 15).date(): "Good Friday",
        datetime(2022, 5, 3).date(): "Id-Ul-Fitr",
        datetime(2022, 7, 10).date(): "Bakri Id",
        datetime(2022, 8, 9).date(): "Muharram",
        datetime(2022, 8, 15).date(): "Independence Day",
        datetime(2022, 8, 31).date(): "Ganesh Chaturthi",
        datetime(2022, 10, 2).date(): "Gandhi Jayanti",
        datetime(2022, 10, 5).date(): "Dussehra",
        datetime(2022, 10, 24).date(): "Diwali",
        datetime(2022, 10, 26).date(): "Diwali",
        datetime(2022, 11, 8).date(): "Gurunanak Jayanti",

        # 2023
        datetime(2023, 1, 26).date(): "Republic Day",
        datetime(2023, 2, 18).date(): "Maha Shivratri",
        datetime(2023, 3, 7).date(): "Holi",
        datetime(2023, 3, 30).date(): "Ram Navami",
        datetime(2023, 4, 4).date(): "Mahavir Jayanti",
        datetime(2023, 4, 7).date(): "Good Friday",
        datetime(2023, 4, 14).date(): "Dr. Ambedkar Jayanti",
        datetime(2023, 4, 22).date(): "Id-Ul-Fitr",
        datetime(2023, 5, 1).date(): "Maharashtra Day",
        datetime(2023, 6, 29).date(): "Bakri Id",
        datetime(2023, 7, 29).date(): "Muharram",
        datetime(2023, 8, 15).date(): "Independence Day",
        datetime(2023, 9, 19).date(): "Ganesh Chaturthi",
        datetime(2023, 10, 2).date(): "Gandhi Jayanti",
        datetime(2023, 10, 24).date(): "Dussehra",
        datetime(2023, 11, 12).date(): "Diwali",
        datetime(2023, 11, 13).date(): "Diwali",
        datetime(2023, 11, 14).date(): "Diwali",
        datetime(2023, 11, 27).date(): "Gurunanak Jayanti",
        datetime(2023, 12, 25).date(): "Christmas",

        # 2024
        datetime(2024, 1, 22).date(): "Special Holiday (Clearing)",
        datetime(2024, 1, 26).date(): "Republic Day",
        datetime(2024, 3, 8).date(): "Maha Shivratri",
        datetime(2024, 3, 25).date(): "Holi",
        datetime(2024, 3, 29).date(): "Good Friday",
        datetime(2024, 4, 11).date(): "Id-Ul-Fitr",
        datetime(2024, 4, 17).date(): "Ram Navami",
        datetime(2024, 4, 21).date(): "Mahavir Jayanti",
        datetime(2024, 5, 1).date(): "Maharashtra Day",
        datetime(2024, 5, 20).date(): "Election Holiday",
        datetime(2024, 6, 17).date(): "Bakri Id",
        datetime(2024, 7, 17).date(): "Muharram",
        datetime(2024, 8, 15).date(): "Independence Day",
        datetime(2024, 10, 2).date(): "Gandhi Jayanti",
        datetime(2024, 11, 1).date(): "Diwali",
        datetime(2024, 11, 15).date(): "Gurunanak Jayanti",
        datetime(2024, 12, 25).date(): "Christmas",

        # 2025
        datetime(2025, 1, 26).date(): "Republic Day",
        datetime(2025, 2, 26).date(): "Maha Shivratri",
        datetime(2025, 3, 14).date(): "Holi",
        datetime(2025, 3, 31).date(): "Eid-Ul-Fitr",
        datetime(2025, 4, 10).date(): "Mahavir Jayanti",
        datetime(2025, 4, 14).date(): "Dr. Ambedkar Jayanti",
        datetime(2025, 4, 18).date(): "Good Friday",
        datetime(2025, 5, 1).date(): "Maharashtra Day",
        datetime(2025, 8, 15).date(): "Independence Day",
        datetime(2025, 8, 27).date(): "Ganesh Chaturthi",
        datetime(2025, 10, 2).date(): "Gandhi Jayanti / Dussehra",
        datetime(2025, 10, 22).date(): "Balipratipada",
        datetime(2025, 11, 5).date(): "Guru Nanak Jayanti",
        datetime(2025, 12, 25).date(): "Christmas",

        # 2026
        datetime(2026, 1, 15).date(): "Municipal Election",
        datetime(2026, 1, 26).date(): "Republic Day",
    }

    return holidays

def check_for_holidays(missing_weekdays):
    """Identify potential market holidays among missing weekdays"""
    known_holidays = get_known_holidays()

    likely_holidays = []
    unexplained_missing = []

    for date in missing_weekdays:
        if date in known_holidays:
            likely_holidays.append((date, known_holidays[date]))
        else:
            unexplained_missing.append(date)

    return likely_holidays, unexplained_missing

def print_symbol_report(symbol, missing_dates, expected_days):
    """Print concise report for a single symbol"""

    if len(missing_dates) == 0:
        print(f"[{symbol}] ✓ Complete - No missing dates")
        return

    # Categorize missing dates
    weekday_missing, weekend_missing = categorize_missing_dates(missing_dates)

    # Check for holidays
    likely_holidays, unexplained_missing = check_for_holidays(weekday_missing)

    if len(unexplained_missing) == 0:
        print(f"[{symbol}] ✓ Complete - All missing dates are holidays/weekends")
    else:
        print(f"[{symbol}] ⚠ Data Gaps Found: {len(unexplained_missing)} unexplained missing weekdays")
        for date in sorted(unexplained_missing):
            day_name = datetime.combine(date, datetime.min.time()).strftime('%A')
            print(f"  {date} ({day_name})")

def print_summary_report(all_results, start_date, end_date):
    """Print comprehensive summary report for all symbols"""

    print("\n" + "="*80)
    print("MULTI-INSTRUMENT DATA VALIDATION SUMMARY")
    print("="*80)

    print(f"\nValidation Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print(f"Total Instruments Validated: {len(all_results)}")

    complete_symbols = []
    symbols_with_gaps = []
    failed_symbols = []

    for result in all_results:
        symbol = result['symbol']
        status = result['status']

        if status == 'failed':
            failed_symbols.append(symbol)
        elif status == 'complete':
            complete_symbols.append(symbol)
        elif status == 'gaps':
            symbols_with_gaps.append((symbol, result['gap_count'], result['gap_dates']))

    print(f"\n--- VALIDATION RESULTS ---")
    print(f"Complete (No gaps): {len(complete_symbols)}")
    print(f"With data gaps: {len(symbols_with_gaps)}")
    print(f"Failed to fetch: {len(failed_symbols)}")

    if complete_symbols:
        print(f"\n--- COMPLETE INSTRUMENTS ({len(complete_symbols)}) ---")
        for symbol in sorted(complete_symbols):
            print(f"  ✓ {symbol}")

    if symbols_with_gaps:
        print(f"\n--- INSTRUMENTS WITH DATA GAPS ({len(symbols_with_gaps)}) ---")
        for symbol, gap_count, gap_dates in sorted(symbols_with_gaps, key=lambda x: x[1], reverse=True):
            print(f"\n  {symbol}: {gap_count} missing weekdays")
            for date in sorted(gap_dates):
                day_name = datetime.combine(date, datetime.min.time()).strftime('%A')
                print(f"    {date} ({day_name})")

    if failed_symbols:
        print(f"\n--- FAILED TO FETCH ({len(failed_symbols)}) ---")
        for symbol in sorted(failed_symbols):
            print(f"  ✗ {symbol}")

    print("\n" + "="*80)

# ===== MAIN VALIDATION SCRIPT =====

def authenticate():
    """Authenticate with Groww API using TOTP"""
    try:
        totp_gen = pyotp.TOTP(AUTH_CONFIG["totp_secret"])
        totp = totp_gen.now()
        access_token = GrowwAPI.get_access_token(
            api_key=AUTH_CONFIG["api_key"],
            totp=totp
        )
        return GrowwAPI(access_token)
    except Exception as e:
        print(f"Authentication failed: {e}")
        raise

# ===== EXPORT =====

# ================= EXPORT =================

def export_to_log(results):

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Ensure Log directory exists
    log_dir = "./Log"
    os.makedirs(log_dir, exist_ok=True)

    filename = f"historical_missing_report_{timestamp}.csv"
    filepath = os.path.join(log_dir, filename)

    rows = []

    for r in results:
        missing = ",".join(str(d) for d in r["gap_dates"]) if r["gap_dates"] else ""

        rows.append({
            "symbol": r["symbol"],
            "status": r["status"],
            "missing_days": missing
        })

    pd.DataFrame(rows).to_csv(filepath, index=False)

    print(f"\n✅ Log created → {filepath}")


# ================= MAIN =================

def get_previous_trading_day():
    """Return the previous trading day (skipping weekends)"""
    today = datetime.now()
    prev_day = today - timedelta(days=1)
    while prev_day.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        prev_day -= timedelta(days=1)
    return prev_day

def run_validation():

    send_slack_alert("🔵 Validator job started")
    send_slack_alert("----Fetching Started ---")
    missing_dates = []

    start_time = datetime.now()

    groww = authenticate()

    prev_day = get_previous_trading_day()

    ist = pytz.timezone("Asia/Kolkata")

    start_dt = prev_day.replace(hour=9, minute=0, second=0, microsecond=0)
    end_dt = prev_day.replace(hour=16, minute=0, second=0, microsecond=0)

    start_str = start_dt.strftime('%Y-%m-%d %H:%M:%S')
    end_str = end_dt.strftime('%Y-%m-%d %H:%M:%S')

    all_results = []

    for symbol in VALIDATION_CONFIG["symbols"]:
        for exchange in VALIDATION_CONFIG["exchange"]:

            print(f"Processing {exchange}-{symbol}...")

            df = fetch_historical_data_paginated(
                groww,
                symbol,
                exchange,
                start_dt,
                end_dt
            )

            if df.empty:
                all_results.append({
                    "symbol": f"{exchange}-{symbol}",
                    "status": "failed",
                    "gap_dates": []
                })
                continue

            missing_dates, _ = validate_data_completeness(df, start_dt, end_dt)

        # Categorize
        weekday_missing, _ = categorize_missing_dates(missing_dates)

        # Remove holidays
        _, unexplained_missing = check_for_holidays(weekday_missing)

        gaps = unexplained_missing  # only real unexplained weekdays

        if gaps:
            status = "gaps"
        else:
            status = "complete"

            all_results.append({
                "symbol": f"{exchange}-{symbol}",
                "status": status,
                "gap_dates": gaps
            })

     # ===== Slack Summary with Detailed Gaps =====

    complete_count = sum(1 for r in all_results if r["status"] == "complete")
    gap_results = [r for r in all_results if r["status"] == "gaps"]
    failed_count = sum(1 for r in all_results if r["status"] == "failed")

    end_time = datetime.now()
    duration = round((end_time - start_time).total_seconds(), 2)

    status_icon = "🟢" if len(gap_results) == 0 and failed_count == 0 else "🔴"

    message = f"""
{status_icon} *Historical Data Validation Report*

📅 Period: {start_dt.date()} → {end_dt.date()}
📊 Total Checked: {len(all_results)}

✅ Complete: {complete_count}
⚠ With Gaps: {len(gap_results)}
❌ Failed: {failed_count}

⏱ Execution Time: {duration} sec
🕒 Run Time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}
"""

    # ===== Add Detailed Gap List =====

    if gap_results:
        message += "\n\n⚠ *Missing Data Details:*\n"

        # Limit detailed output to avoid Slack overflow
        max_instruments_to_show = 10

        for r in gap_results[:max_instruments_to_show]:
            missing_dates_str = ", ".join(str(d) for d in r["gap_dates"])
            message += f"\n• {r['symbol']} → {missing_dates_str}"

        if len(gap_results) > max_instruments_to_show:
            message += f"\n\n...and {len(gap_results) - max_instruments_to_show} more instruments"

    send_slack_alert(message)

    export_to_log(all_results)


# ================= ENTRY =================

if __name__ == "__main__":
    try:
        run_validation()
    except Exception as e:
        send_slack_alert(f"❌ Validator Crashed: {str(e)}")
        raise
