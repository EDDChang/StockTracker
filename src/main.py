import os
import json
import sys
import yaml
import pandas as pd
import numpy as np
import mplfinance as mpf
from data_loader import get_stock_data
from analyzer import (
    find_higher_lows,
    check_structure_shift,
    detect_price_action,
    detect_ma_structure,
    days_since_new_high,
)

TODAY = pd.Timestamp.now().strftime("%Y-%m-%d")

CONFIG_PATH  = os.path.join(os.path.dirname(__file__), "..", "stocks.yaml")
DATA_DIR     = os.path.join(os.path.dirname(__file__), "..", "reports")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")
CHARTS_DIR   = os.path.join(os.path.dirname(__file__), "..", "charts")


# ── config & history ──────────────────────────────────────────────────────────

def load_config():
    with open(CONFIG_PATH, "r") as f:
        cfg = yaml.safe_load(f)
    return (cfg.get("market_references", []),
            cfg.get("stocks", []),
            cfg.get("stock_names", {}))

def load_history():
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH) as f:
            return json.load(f)
    return {}

def save_history(history):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def extract_signals(result):
    if result.get("error"):
        return None
    struct_status = "alert" if result["is_broken"] else "ok"
    sev = result["ma"].get("severity", "ok")
    ma_status = "alert" if sev == "alert" else ("warn" if sev in ("warn", "caution") else "ok")
    return {"struct": struct_status, "ma": ma_status}

def record_and_get_streaks(history, ticker, signals):
    if signals is None:
        return {"struct": 0, "ma": 0}
    entries = history.setdefault(ticker, [])
    if entries and entries[-1]["date"] == TODAY:
        entries[-1] = {"date": TODAY, **signals}
    else:
        entries.append({"date": TODAY, **signals})
    history[ticker] = entries[-60:]
    streaks = {}
    for key in ("struct", "ma"):
        count = 0
        for entry in reversed(entries):
            if entry.get(key, "ok") != "ok":
                count += 1
            else:
                break
        streaks[key] = count
    return streaks


# ── chart ─────────────────────────────────────────────────────────────────────

def generate_chart(ticker, df):
    cutoff = pd.Timestamp.now() - pd.DateOffset(days=200)
    df_c = df[df.index >= cutoff].copy()
    df_c.index = pd.DatetimeIndex(df_c.index)

    ma5  = df_c["Close"].rolling(5).mean()
    ma10 = df_c["Close"].rolling(10).mean()
    ma20 = df_c["Close"].rolling(20).mean()
    ma60 = df_c["Close"].rolling(60).mean()

    add_plots = [
        mpf.make_addplot(ma5,  color="#e74c3c", width=0.9, label="MA5",  linestyle="--"),
        mpf.make_addplot(ma10, color="#2ecc71", width=1.0, label="MA10"),
        mpf.make_addplot(ma20, color="#f5a623", width=1.2, label="MA20"),
        mpf.make_addplot(ma60, color="#4a90d9", width=1.4, label="MA60"),
    ]

    os.makedirs(CHARTS_DIR, exist_ok=True)
    chart_path = os.path.join(CHARTS_DIR, f"{ticker}_chart.png")
    mpf.plot(
        df_c,
        type="candle",
        style="yahoo",
        title=f"{ticker}  Daily Candlestick Chart (Last 200 Days)",
        addplot=add_plots,
        volume=True,
        figsize=(14, 7),
        savefig=dict(fname=chart_path, dpi=150, bbox_inches="tight"),
    )
    return chart_path


# ── analysis ──────────────────────────────────────────────────────────────────

def analyse(ticker):
    df = get_stock_data(ticker)
    hl_list  = find_higher_lows(df)
    is_broken, last_hl = check_structure_shift(df, hl_list)
    ma       = detect_ma_structure(df)
    pa       = detect_price_action(df)
    new_high = days_since_new_high(df)
    price    = float(df["Close"].dropna().iloc[-1])
    chart    = generate_chart(ticker, df)
    return dict(ticker=ticker, price=price, is_broken=is_broken,
                last_hl=last_hl, ma=ma, pa=pa, new_high=new_high, chart=chart)


# ── save data ─────────────────────────────────────────────────────────────────

def _json_default(obj):
    if isinstance(obj, np.bool_):    return bool(obj)
    if isinstance(obj, np.integer):  return int(obj)
    if isinstance(obj, np.floating): return float(obj)
    return str(obj)

def save_trend_data(ref_results, stock_results):
    def _ser(r):
        if r.get("error"):
            return {"ticker": r["ticker"], "error": r["error"]}
        ma = r["ma"]
        return {
            "ticker":    r["ticker"],
            "price":     r["price"],
            "is_broken": bool(r["is_broken"]),
            "last_hl":   r.get("last_hl"),
            "ma": {
                "status":          ma["status"],
                "severity":        ma["severity"],
                "ma_values":       ma["ma_values"],
                "above":           {k: bool(v) for k, v in ma["above"].items()},
                "slope_up":        {k: bool(v) for k, v in ma["slope_up"].items()},
                "aligned_bullish": bool(ma["aligned_bullish"]),
            },
            "pa":        {k: bool(v) for k, v in r["pa"].items()},
            "streaks":   r["streaks"],
            "new_high":  {
                "days":       r["new_high"]["days"],
                "peak_price": r["new_high"]["peak_price"],
                "peak_date":  str(r["new_high"]["peak_date"])[:10],
            } if r.get("new_high") else None,
            "chart":     os.path.basename(r["chart"]) if r.get("chart") else None,
        }
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "trend_data.json")
    with open(path, "w") as f:
        json.dump(
            {"updated": TODAY, "refs": [_ser(r) for r in ref_results],
             "stocks":  [_ser(r) for r in stock_results]},
            f, ensure_ascii=False, indent=2, default=_json_default,
        )


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    refs, stocks, names = load_config()
    history = load_history()

    ref_results, stock_results = [], []

    for ticker, bucket in [(t, "ref") for t in refs] + [(t, "stock") for t in stocks]:
        try:
            r = analyse(ticker)
            r["streaks"] = record_and_get_streaks(history, ticker, extract_signals(r))
            (ref_results if bucket == "ref" else stock_results).append(r)
            print(f"已分析: {ticker}")
        except Exception as e:
            err = dict(ticker=ticker, error=str(e), streaks={"struct": 0, "ma": 0})
            (ref_results if bucket == "ref" else stock_results).append(err)
            print(f"錯誤 {ticker}: {e}")
            import traceback; traceback.print_exc()

    save_history(history)
    save_trend_data(ref_results, stock_results)

    import build_web
    build_web.main()
    print("完成")
