from growwapi import GrowwAPI
import pyotp
import threading
import requests
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed


# ================= SLACK CONFIG =================
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")

def send_slack_alert(message):
    payload = {"text": message}
    try:
        response = requests.post(SLACK_WEBHOOK, json=payload, timeout=5)
        if response.status_code != 200:
            print("Slack notification failed:", response.text)
    except Exception as e:
        print("Slack error:", e)


# ================= AUTHENTICATION CONFIG =================
AUTH_CONFIG = {
    "api_key":     os.getenv("API_KEY"),
    "totp_secret": os.getenv("TOTP_SECRET"),
}

def authenticate():
    totp = pyotp.TOTP(AUTH_CONFIG["totp_secret"]).now()
    access_token = GrowwAPI.get_access_token(
        api_key=AUTH_CONFIG["api_key"],
        totp=totp
    )
    return GrowwAPI(access_token)


# ================= CIRCUIT CONFIG =================
# Alert when stock has moved 75% of its band toward circuit (last 25% triggers)
# Stocks AT or past circuit are never alerted
# Band 20% → alert within 5% | 10% → 2.5% | 5% → 1.25% | 2% → 0.5%
BAND_THRESHOLDS = {20: 5.0, 10: 2.5, 5: 1.25, 2: 0.5}

MAX_WORKERS = 20
CHUNK_SIZE  = 300


# ================= SHARED CLIENT =================
_groww       = None
_auth_count  = 0
_client_lock = threading.Lock()

def get_client():
    global _groww, _auth_count
    if _groww is None:
        with _client_lock:
            if _groww is None:
                _groww = authenticate()
                _auth_count += 1
                print(f"  [Auth] Token #{_auth_count} created (limit: 150/day)")
    return _groww

def refresh_client():
    global _groww, _auth_count
    with _client_lock:
        _groww = authenticate()
        _auth_count += 1
        print(f"  [Auth] Token refreshed — #{_auth_count}/150")


# ================= HELPERS =================
def get_threshold(prev_close, upper_circuit):
    if not prev_close or prev_close == 0:
        return 5.0, None
    band = round((upper_circuit / prev_close - 1) * 100)
    for standard in sorted(BAND_THRESHOLDS, reverse=True):
        if band >= standard - 1:
            return BAND_THRESHOLDS[standard], standard
    raw = (upper_circuit / prev_close - 1) * 100
    return raw * 0.25, round(raw)


def get_eq_symbols():
    groww = get_client()
    df    = groww._load_instruments()
    eq    = df[(df["instrument_type"].str.upper() == "EQ") &
               (df["exchange"].str.upper() == "NSE")]
    syms  = eq["trading_symbol"].dropna().unique().tolist()
    syms  = [s for s in syms if not s[0].isdigit() or s == "360ONE"]
    return syms


# ================= SYMBOL CHECK =================
def check_symbol(symbol):
    try:
        groww = get_client()
        q = groww.get_quote(
            exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_CASH,
            trading_symbol=symbol
        )
        ltp        = q.get("last_price", 0)
        uc         = q.get("upper_circuit_limit", 0)
        lc         = q.get("lower_circuit_limit", 0)
        prev_close = q.get("ohlc", {}).get("close", 0)

        if ltp <= 0 or uc <= 0:
            return symbol, []

        threshold, band = get_threshold(prev_close, uc)
        band_str = f"{band}% band" if band else "?"
        results  = []

        # Upper circuit — skip if already hit
        if ltp < uc:
            dist_uc = abs(ltp - uc) / uc * 100
            if dist_uc <= threshold:
                results.append({
                    "type":      "NEAR UPPER ▲",
                    "symbol":    symbol,
                    "ltp":       ltp,
                    "circuit":   uc,
                    "dist":      dist_uc,
                    "band":      band_str,
                    "threshold": threshold,
                })

        # Lower circuit — skip if already hit
        if lc > 0 and ltp > lc:
            dist_lc = abs(ltp - lc) / lc * 100
            if dist_lc <= threshold:
                results.append({
                    "type":      "NEAR LOWER ▼",
                    "symbol":    symbol,
                    "ltp":       ltp,
                    "circuit":   lc,
                    "dist":      dist_lc,
                    "band":      band_str,
                    "threshold": threshold,
                })

        return symbol, results

    except Exception as e:
        if any(k in str(e).lower() for k in ("auth", "token", "401")):
            refresh_client()
        return symbol, []


# ================= BATCH RUNNER =================
print_lock = threading.Lock()

def print_alert(a):
    ts = datetime.now().strftime("%H:%M:%S")
    with print_lock:
        print(
            f"[{ts}] {a['type']:<14}  {a['symbol']:<20}  "
            f"LTP: {a['ltp']:>10.2f}  Circuit: {a['circuit']:>10.2f}  "
            f"Dist: {a['dist']:>6.2f}%  [{a['band']}, alert@{a['threshold']}%]"
        )

def run_batch(batch):
    alerts = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(check_symbol, sym): sym for sym in batch}
        for future in as_completed(futures):
            _, results = future.result()
            for a in results:
                print_alert(a)
                alerts.append(a)
    return alerts


# ================= SLACK SUMMARY =================
def send_circuit_summary(scan, alerts):
    if not alerts:
        return
    upper = [a for a in alerts if "UPPER" in a["type"]]
    lower = [a for a in alerts if "LOWER" in a["type"]]
    msg   = f"*⚡ Circuit Alert | Scan #{scan}  {datetime.now().strftime('%H:%M:%S')}*\n"
    msg  += f"_(Stocks 75%+ toward circuit — circuit hits excluded)_\n"
    if upper:
        msg += f"\n*▲ Near Upper Circuit ({len(upper)})*\n"
        for a in upper:
            msg += (f"  • `{a['symbol']:<20}`  LTP: {a['ltp']:.2f}  "
                    f"UC: {a['circuit']:.2f}  Dist: {a['dist']:.2f}%  [{a['band']}]\n")
    if lower:
        msg += f"\n*▼ Near Lower Circuit ({len(lower)})*\n"
        for a in lower:
            msg += (f"  • `{a['symbol']:<20}`  LTP: {a['ltp']:.2f}  "
                    f"LC: {a['circuit']:.2f}  Dist: {a['dist']:.2f}%  [{a['band']}]\n")
    send_slack_alert(msg)


# ================= MAIN =================
def run_monitor():
    send_slack_alert("🟢 Circuit Monitor started")

    all_symbols = get_eq_symbols()
    print(f"Loaded {len(all_symbols)} symbols.\n")
    send_slack_alert(f"👁 Watching {len(all_symbols)} NSE EQ symbols | Alert: 75% toward UC/LC")

    print(f"{'─'*100}")
    print(f"  TIME    TYPE            SYMBOL                LTP          CIRCUIT      DIST    BAND")
    print(f"{'─'*100}")

    watchlist       = set()
    rotation_idx    = 0
    scan            = 1
    already_alerted = set()
    scanned_so_far  = set()

    while True:
        ts_start      = datetime.now()
        non_watchlist = [s for s in all_symbols if s not in watchlist]
        total_non     = max(len(non_watchlist), 1)
        chunk_start   = rotation_idx % total_non
        chunk         = non_watchlist[chunk_start : chunk_start + CHUNK_SIZE]
        if len(chunk) < CHUNK_SIZE:
            chunk += non_watchlist[: CHUNK_SIZE - len(chunk)]

        new_rotation_idx = (chunk_start + CHUNK_SIZE) % total_non
        if new_rotation_idx < rotation_idx:
            already_alerted.clear()
            scanned_so_far.clear()
            with print_lock:
                print("  [Rotation complete — alert history reset]")
        rotation_idx = new_rotation_idx

        scanned_so_far.update(chunk)
        to_check = list(watchlist) + chunk

        with print_lock:
            print(f"\n  ── Scan #{scan}  {ts_start.strftime('%H:%M:%S')}  "
                  f"Watchlist: {len(watchlist)}  Chunk: {len(chunk)}  "
                  f"Alerted this rotation: {len(already_alerted)}  Token #{_auth_count}/150 ──")

        all_alerts   = run_batch(to_check)
        alerted_syms = {a["symbol"] for a in all_alerts}

        # Only Slack-alert symbols not already sent this rotation
        new_alerts = [a for a in all_alerts if a["symbol"] not in already_alerted]
        already_alerted.update(a["symbol"] for a in new_alerts)

        # Update watchlist
        for sym in alerted_syms:
            watchlist.add(sym)
        for sym in list(watchlist):
            if sym not in alerted_syms and sym in to_check:
                watchlist.discard(sym)

        elapsed    = (datetime.now() - ts_start).seconds
        suppressed = len(all_alerts) - len(new_alerts)
        with print_lock:
            print(f"\r  Scan #{scan} done in {elapsed}s — "
                  f"Triggers: {len(all_alerts)}  New alerts: {len(new_alerts)}  "
                  f"Suppressed: {suppressed}  Watchlist: {len(watchlist)}" + " " * 10)

        send_circuit_summary(scan, new_alerts)
        scan += 1


# ================= ENTRY =================
if __name__ == "__main__":
    try:
        run_monitor()
    except Exception as e:
        send_slack_alert(f"❌ Circuit Monitor crashed: {str(e)}")
        raise
