import os
import json
import yaml
import pandas as pd
import numpy as np
import mplfinance as mpf
from data_loader import get_stock_data
from analyzer import (
    find_higher_lows,
    check_structure_shift,
    detect_price_action,
    detect_ma_breakdown,
    detect_trendline_break,
)

TODAY = pd.Timestamp.now().strftime("%Y-%m-%d")

CONFIG_PATH   = os.path.join(os.path.dirname(__file__), "..", "stocks.yaml")
REPORT_DIR    = os.path.join(os.path.dirname(__file__), "..", "reports")
REPORT_PATH   = os.path.join(REPORT_DIR, f"report_{TODAY}.md")   # 帶日期的報告
REPORT_LATEST = os.path.join(REPORT_DIR, "report.md")             # 永遠指向最新
HISTORY_PATH  = os.path.join(REPORT_DIR, "history.json")
CHARTS_DIR    = os.path.join(os.path.dirname(__file__), "..", "charts")


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
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def extract_signals(result):
    """將分析結果轉為三個訊號的 ok/warn/alert 狀態。"""
    if result.get("error"):
        return None
    is_broken = result["is_broken"]
    ma = result["ma_bd"]
    tl = result["tl"]

    struct_status = "alert" if is_broken else "ok"

    if ma["below_ma_long"] and ma["ma_long_slope_down"]:
        ma_status = "alert"
    elif ma["below_ma_long"] or (ma["below_ma_short"] and ma["ma_short_slope_down"]):
        ma_status = "warn"
    else:
        ma_status = "ok"

    if tl["trendline_value"] is None:
        tl_status = "ok"
    elif "🚨" in tl["status"]:
        tl_status = "alert"
    elif "⚠️" in tl["status"]:
        tl_status = "warn"
    else:
        tl_status = "ok"

    return {"struct": struct_status, "ma": ma_status, "tl": tl_status}

def record_and_get_streaks(history, ticker, signals):
    """儲存今日訊號並回傳各訊號連續天數（包含今天）。"""
    if signals is None:
        return {"struct": 0, "ma": 0, "tl": 0}

    entries = history.setdefault(ticker, [])
    if entries and entries[-1]["date"] == TODAY:
        entries[-1] = {"date": TODAY, **signals}   # 同天重跑則覆寫
    else:
        entries.append({"date": TODAY, **signals})
    history[ticker] = entries[-60:]                 # 只保留最近 60 天

    streaks = {}
    for key in ("struct", "ma", "tl"):
        count = 0
        for entry in reversed(entries):
            if entry.get(key, "ok") != "ok":
                count += 1
            else:
                break
        streaks[key] = count
    return streaks


# ── icon helpers ──────────────────────────────────────────────────────────────

def _struct_icon(is_broken):
    return "🚨" if is_broken else "✅"

def _ma_icon(ma_bd):
    if ma_bd["below_ma_long"] and ma_bd["ma_long_slope_down"]: return "🚨"
    if ma_bd["below_ma_long"] or (ma_bd["below_ma_short"] and ma_bd["ma_short_slope_down"]): return "⚠️"
    return "✅"

def _tl_icon(tl):
    if tl["trendline_value"] is None: return "—"
    s = tl["status"]
    if "🚨" in s: return "🚨"
    if "⚠️" in s: return "⚠️"
    return "✅"

def _overall(is_broken, ma_bd, tl):
    icons = [_struct_icon(is_broken), _ma_icon(ma_bd), _tl_icon(tl)]
    reds = icons.count("🚨")
    if reds >= 2:          return "🚨 多重警示"
    if reds == 1:          return "⚠️ 留意"
    if "⚠️" in icons:     return "⚠️ 觀察"
    return "✅ 多頭維持"

def _with_streak(icon, n):
    """在異常 icon 後附加連續天數（>= 2 天才標注）。"""
    if n >= 2 and icon in ("🚨", "⚠️"):
        return f"{icon}({n}天)"
    return icon

def _streak_note(n):
    """在詳細報告的文字中附加連續天數。"""
    if n >= 2:
        return f"（連續 {n} 天）"
    return ""


# ── overview table ────────────────────────────────────────────────────────────

def _anchor(ticker):
    """HTML anchor ID for a ticker (safe for any ticker name)."""
    return "s-" + ticker.replace(".", "-").replace("^", "").replace("=", "")

def build_overview(ref_results, stock_results, names=None):
    names = names or {}
    lines = [
        '<a id="overview"></a>',
        "",
        "## 快速總覽",
        "",
        "| 股票 | 名稱 | 收盤價 | 結構 | 均線 | 趨勢線 | 綜合訊號 |",
        "|------|------|-------:|:----:|:----:|:------:|--------|",
    ]

    def row(r):
        ticker = r["ticker"]
        name   = names.get(ticker, "")
        if r.get("error"):
            return f"| {ticker} | {name} | — | — | — | — | ❌ 錯誤 |"
        sk = r["streaks"]
        s = _with_streak(_struct_icon(r["is_broken"]),  sk["struct"])
        m = _with_streak(_ma_icon(r["ma_bd"]),           sk["ma"])
        t = _with_streak(_tl_icon(r["tl"]),              sk["tl"])
        o = _overall(r["is_broken"], r["ma_bd"], r["tl"])
        price = f"{r['price']:,.0f}" if r["price"] > 1000 else f"{r['price']:.2f}"
        link  = f"[{ticker}](#{_anchor(ticker)})"
        return f"| {link} | {name} | {price} | {s} | {m} | {t} | {o} |"

    if ref_results:
        lines.append("| **市場指數** | | | | | |")
        lines.extend(row(r) for r in ref_results)
        lines.append("| **個股** | | | | | |")
    lines.extend(row(r) for r in stock_results)
    lines += ["", "---", ""]
    return "\n".join(lines)


# ── chart ─────────────────────────────────────────────────────────────────────

def generate_chart(ticker, df, hl_list):
    cutoff = pd.Timestamp.now() - pd.DateOffset(days=200)
    df_c = df[df.index >= cutoff].copy()
    df_c.index = pd.DatetimeIndex(df_c.index)

    ma5   = df_c["Close"].rolling(5).mean()
    ma20  = df_c["Close"].rolling(20).mean()
    ema50 = df_c["Close"].ewm(span=50, adjust=False).mean()

    add_plots = [
        mpf.make_addplot(ma5,   color="#e74c3c", width=1.0, label="MA 5",   linestyle="--"),
        mpf.make_addplot(ma20,  color="#f5a623", width=1.2, label="MA 20"),
        mpf.make_addplot(ema50, color="#4a90d9", width=1.2, label="EMA 50"),
    ]

    chart_hls = [(d, v) for d, v in hl_list if d >= df_c.index[0]]
    if len(chart_hls) >= 2:
        (d0, v0), (d1, v1) = chart_hls[-2], chart_hls[-1]
        span = (d1 - d0).days
        if span > 0:
            slope = (v1 - v0) / span
            tl_vals = pd.Series(
                [v0 + slope * (d - d0).days for d in df_c.index],
                index=df_c.index, dtype=float,
            )
            tl_vals[df_c.index < d0] = float("nan")
            add_plots.append(
                mpf.make_addplot(tl_vals, color="#2ecc71", width=1.2, label="Trendline", linestyle="--")
            )

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


# ── per-stock report section ──────────────────────────────────────────────────

def build_report(ticker, current_price, chart_path,
                 is_broken, last_hl, ma_bd, tl, pa, streaks, name=""):

    sk = streaks

    # 規則 1
    if is_broken:
        r1 = f"🚨 多頭結構遭破壞（收盤跌破前低 {last_hl:.2f}，形成 Lower Low）{_streak_note(sk['struct'])}"
    elif last_hl is not None:
        r1 = f"✅ 多頭結構完整（HH/HL 上升序列維持，最後 HL: {last_hl:.2f}）"
    else:
        r1 = "⚠️ 尚無足夠波段低點判斷結構"

    # 規則 2
    r2 = ma_bd["status"]
    if sk["ma"] >= 2 and ("🚨" in r2 or "⚠️" in r2):
        r2 += _streak_note(sk["ma"])

    # 規則 3
    tl_val = f"（趨勢線參考值: {tl['trendline_value']:.2f}）" if tl["trendline_value"] else ""
    r3 = tl["status"] + tl_val
    if sk["tl"] >= 2 and ("🚨" in r3 or "⚠️" in r3):
        r3 += _streak_note(sk["tl"])

    pa_notes = []
    if pa["long_shadow"]: pa_notes.append("⚠️ 長上影線/墓碑線（多頭受壓）")
    if pa["engulfing"]:   pa_notes.append("⚠️ 空頭吞噬（反轉訊號）")
    pa_str = "、".join(pa_notes) if pa_notes else "✅ 無明顯轉弱 K 線"

    chart_rel = os.path.relpath(chart_path, REPORT_DIR)

    title = f"{ticker}　{name}" if name else ticker
    return f"""<a id="{_anchor(ticker)}"></a>

## {title}

[↑ 回到總覽](#overview)

| 項目 | 數值 |
|------|------|
| 分析日期 | {TODAY} |
| 目前收盤價 | {current_price:,.2f} |

![{ticker} K線圖]({chart_rel})

### 規則 1: 價格結構變化 (Price Structure)
- **狀態**: {r1}

### 規則 2: 短期均線與動能
- **狀態**: {r2}
- MA 5: {ma_bd['ma_short']:.2f}　|　MA 20: {ma_bd['ma_long']:.2f}

### 規則 3: 上升趨勢線
- **狀態**: {r3}
- **K線訊號**: {pa_str}

---
"""


# ── analysis ──────────────────────────────────────────────────────────────────

def analyse(ticker):
    df = get_stock_data(ticker)
    hl_list = find_higher_lows(df)
    is_broken, last_hl = check_structure_shift(df, hl_list)
    ma_bd = detect_ma_breakdown(df)
    tl    = detect_trendline_break(df, hl_list)
    pa    = detect_price_action(df)
    price = float(df["Close"].dropna().iloc[-1])
    chart = generate_chart(ticker, df, hl_list)
    return dict(ticker=ticker, price=price, is_broken=is_broken,
                last_hl=last_hl, ma_bd=ma_bd, tl=tl, pa=pa, chart=chart)


# ── main ──────────────────────────────────────────────────────────────────────

def _json_default(obj):
    import numpy as np
    if isinstance(obj, (np.bool_,)):      return bool(obj)
    if isinstance(obj, (np.integer,)):    return int(obj)
    if isinstance(obj, (np.floating,)):   return float(obj)
    return str(obj)

def save_trend_data(ref_results, stock_results):
    def _ser(r):
        if r.get("error"):
            return {"ticker": r["ticker"], "error": r["error"]}
        return {
            "ticker":     r["ticker"],
            "price":      r["price"],
            "is_broken":  bool(r["is_broken"]),
            "last_hl":    r.get("last_hl"),
            "ma_bd":      r["ma_bd"],
            "tl":         r["tl"],
            "pa":         {k: bool(v) for k, v in r["pa"].items()},
            "streaks":    r["streaks"],
            "chart":      os.path.basename(r["chart"]) if r.get("chart") else None,
        }
    data = {
        "updated": TODAY,
        "refs":    [_ser(r) for r in ref_results],
        "stocks":  [_ser(r) for r in stock_results],
    }
    path = os.path.join(REPORT_DIR, "trend_data.json")
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=_json_default)


if __name__ == "__main__":
    refs, stocks, names = load_config()
    history = load_history()

    ref_results, stock_results, sections = [], [], []

    for ticker, bucket in [(t, "ref") for t in refs] + [(t, "stock") for t in stocks]:
        try:
            r = analyse(ticker)
            signals = extract_signals(r)
            r["streaks"] = record_and_get_streaks(history, ticker, signals)
            section = build_report(
                r["ticker"], r["price"], r["chart"],
                r["is_broken"], r["last_hl"],
                r["ma_bd"], r["tl"], r["pa"],
                r["streaks"],
                name=names.get(ticker, ""),
            )
            (ref_results if bucket == "ref" else stock_results).append(r)
            sections.append(section)
            print(f"已分析: {ticker}")
        except Exception as e:
            err = dict(ticker=ticker, error=str(e),
                       streaks={"struct": 0, "ma": 0, "tl": 0})
            (ref_results if bucket == "ref" else stock_results).append(err)
            sections.append(f"## {ticker}\n\n> 錯誤: {e}\n\n---\n")
            print(f"分析 {ticker} 時發生錯誤: {e}")
            import traceback; traceback.print_exc()

    save_history(history)
    save_trend_data(ref_results, stock_results)

    header   = f"# 股票趨勢分析報告（多頭視角）\n\n更新時間: {TODAY}\n\n---\n\n"
    overview = build_overview(ref_results, stock_results, names)
    content  = header + overview + "\n".join(sections)

    os.makedirs(REPORT_DIR, exist_ok=True)
    for path in (REPORT_PATH, REPORT_LATEST):
        with open(path, "w") as f:
            f.write(content)
    print(f"\n報告已生成: {REPORT_PATH}")
