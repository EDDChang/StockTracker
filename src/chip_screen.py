#!/usr/bin/env python3
"""
chip_screen.py — 台股籌碼分析篩選工具

針對 stocks.yaml 中的台股，從三個維度分析籌碼強弱：
  1. 三大法人動向  — 外資/投信連續買超天數（門檻: 3 日）
  2. 集保大戶持股  — 400 張以上大戶（Level 12-15）持股比例
                    從 TDCC OpenAPI 取得；每次執行後快取，供下次比較趨勢
  3. 融資變化      — 融資餘額5日變化：降幅>5% → 籌碼沉澱；漲幅>10% → 警示

使用方式：
  pip install FinMind
  python src/chip_screen.py

  # 可選：設定環境變數登入以取得更高 FinMind API 限額
  export FINMIND_USER=你的帳號
  export FINMIND_PASSWORD=你的密碼
"""

import os
import sys
import json
import time
import requests
import yaml
import pandas as pd
from datetime import date, timedelta

CONFIG_PATH   = os.path.join(os.path.dirname(__file__), "..", "stocks.yaml")
REPORT_DIR    = os.path.join(os.path.dirname(__file__), "..", "reports")
TDCC_CACHE    = os.path.join(REPORT_DIR, "tdcc_cache.json")
TODAY         = date.today().strftime("%Y-%m-%d")
START_30      = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")

CONSEC_THRESH = 3     # 連續買超天數門檻
MARGIN_SURGE  = 0.10  # 融資5日增幅超過此比例 → 爆增警示
MARGIN_SETTLE = 0.05  # 融資5日降幅超過此比例 → 沉澱訊號
RATE_DELAY    = 1.5   # FinMind free tier 呼叫間隔（秒）

# TDCC 集保：Level 12-15 = 400張以上大戶（400,001股以上）
BIG_LEVELS = {"12", "13", "14", "15"}


# ── 載入設定 ──────────────────────────────────────────────────────────────────

def load_tw_tickers():
    """從 stocks.yaml 篩出台股，回傳不含 .TW/.TWO 後綴的 stock_id 列表。"""
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    all_tickers = cfg.get("stocks", []) + cfg.get("market_references", [])
    result = []
    for t in all_tickers:
        upper = t.upper()
        if upper.endswith(".TW") or upper.endswith(".TWO"):
            result.append(t.split(".")[0])
    return result


# ── FinMind DataLoader ────────────────────────────────────────────────────────

def get_loader():
    try:
        from FinMind.data import DataLoader
    except ImportError:
        print("錯誤：請先安裝 FinMind：  pip install FinMind")
        sys.exit(1)
    try:
        dl = DataLoader()
    except Exception as e:
        print(f"  [FinMind] DataLoader 初始化失敗（{e}），重試不帶快取...")
        # 清除可能損壞的快取 token 再重建
        import importlib, FinMind.data as _fm
        importlib.reload(_fm)
        dl = _fm.DataLoader()
    user = os.environ.get("FINMIND_USER", "").strip()
    pw   = os.environ.get("FINMIND_PASSWORD", "").strip()
    if user and pw:
        try:
            dl.login(user_id=user, password=pw)
            print("  [FinMind] 已登入帳號")
        except Exception as e:
            print(f"  [FinMind] 登入失敗（{e}），改用免費額度")
    else:
        print("  [FinMind] 未登入，使用免費額度（每日 200 次）")
    return dl


def _fetch(fn, label, *args, **kwargs):
    try:
        df = fn(*args, **kwargs)
        time.sleep(RATE_DELAY)
        return df if df is not None and not df.empty else pd.DataFrame()
    except Exception as e:
        print(f"    [{label}] 取資料失敗: {e}")
        return pd.DataFrame()


# ── 三大法人 ──────────────────────────────────────────────────────────────────

def fetch_institutional(dl, sid):
    return _fetch(
        dl.taiwan_stock_institutional_investors,
        f"{sid}/法人", stock_id=sid, start_date=START_30, end_date=TODAY,
    )


def analyse_institutional(df):
    """
    FinMind 回傳的 name 欄位為英文。
    外資: Foreign_Investor；投信: Investment_Trust；自營商: Dealer_self / Dealer_Hedging
    """
    result = {"fi": 0, "it": 0, "dealer": 0}
    if df.empty:
        return result

    name_map = {
        "Foreign_Investor": "fi",
        "Investment_Trust": "it",
        "Dealer_self":      "dealer",
    }

    for eng_name, key in name_map.items():
        sub = df[df["name"] == eng_name].copy()
        if sub.empty:
            continue
        sub = sub.sort_values("date")
        buy  = pd.to_numeric(sub["buy"],  errors="coerce").fillna(0)
        sell = pd.to_numeric(sub["sell"], errors="coerce").fillna(0)
        net  = (buy - sell).tolist()
        streak = 0
        for v in reversed(net):
            if v > 0:
                streak += 1
            else:
                break
        result[key] = streak

    return result


# ── 集保大戶持股（TDCC OpenAPI + 本地快取）────────────────────────────────────

def _tdcc_big_ratio(sid):
    """
    從 TDCC OpenAPI 取得最新一期集保分散表，加總 Level 12-15（400張以上）的持股比例。
    回傳 (report_date_str, big_ratio_float) 或 (None, None)。
    """
    try:
        r = requests.get(
            "https://openapi.tdcc.com.tw/v1/opendata/1-5",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"    [{sid}] TDCC API 失敗: {e}")
        return None, None

    date_key = next((k for k in data[0].keys() if "日期" in k), None) if data else None
    rows = [x for x in data if sid in str(x.get("證券代號", "")).strip()]
    if not rows or date_key is None:
        return None, None

    report_date = rows[0][date_key]
    big_ratio = sum(
        float(x["占集保庫存數比例%"])
        for x in rows
        if x.get("持股分級") in BIG_LEVELS
    )
    return report_date, round(big_ratio, 2)


def load_tdcc_cache():
    if os.path.exists(TDCC_CACHE):
        with open(TDCC_CACHE) as f:
            return json.load(f)
    return {}


def save_tdcc_cache(cache):
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(TDCC_CACHE, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def analyse_shareholding(sid, tdcc_cache):
    """
    取得最新一期 TDCC 集保大戶比例，與快取中的前一期比較。
    更新快取，回傳分析結果。
    """
    na = {"big_holder_rising": False, "big_holder_ratio": None,
          "big_holder_chg": None, "report_date": None}

    report_date, big_ratio = _tdcc_big_ratio(sid)
    if report_date is None:
        return na

    history = tdcc_cache.setdefault(sid, [])

    # 避免同週重複寫入
    if not history or history[-1]["date"] != report_date:
        history.append({"date": report_date, "big_ratio": big_ratio})
        tdcc_cache[sid] = history[-12:]  # 保留最近 12 週

    if len(history) < 2:
        return {"big_holder_rising": False, "big_holder_ratio": big_ratio,
                "big_holder_chg": 0.0, "report_date": report_date}

    prev_ratio = history[-2]["big_ratio"]
    chg = big_ratio - prev_ratio
    return {
        "big_holder_rising": chg > 0,
        "big_holder_ratio":  big_ratio,
        "big_holder_chg":    round(chg, 2),
        "report_date":       report_date,
    }


# ── 融資融券 ──────────────────────────────────────────────────────────────────

def fetch_margin(dl, sid):
    return _fetch(
        dl.taiwan_stock_margin_purchase_short_sale,
        f"{sid}/融資", stock_id=sid, start_date=START_30, end_date=TODAY,
    )


def analyse_margin(df):
    na = {"chip_settle": False, "margin_surge": False, "margin_5d_chg": None}
    if df.empty:
        return na

    # FinMind 欄位名稱
    bal_col = next(
        (c for c in ("MarginPurchaseTodayBalance", "MarginPurchaseBalance",
                     "margin_purchase_today_balance")
         if c in df.columns),
        None,
    )
    if bal_col is None:
        candidates = [c for c in df.columns if "balance" in c.lower()]
        bal_col = candidates[0] if candidates else None
    if bal_col is None:
        return na

    df = df.sort_values("date").copy()
    df[bal_col] = pd.to_numeric(df[bal_col], errors="coerce")
    series = df[bal_col].dropna()

    if len(series) < 5:
        return na

    old, new = float(series.iloc[-5]), float(series.iloc[-1])
    if old == 0:
        return na

    chg = (new - old) / old
    return {
        "chip_settle":   chg < -MARGIN_SETTLE,
        "margin_surge":  chg >  MARGIN_SURGE,
        "margin_5d_chg": chg,
    }


# ── 綜合評分 ──────────────────────────────────────────────────────────────────

def score(inst, margin, shareholding):
    signals = {
        "fi_buy":        inst["fi"]   >= CONSEC_THRESH,
        "it_buy":        inst["it"]   >= CONSEC_THRESH,
        "big_holder_up": shareholding["big_holder_rising"],
        "chip_settle":   margin["chip_settle"],
    }
    return signals, sum(signals.values())


# ── 報告生成 ──────────────────────────────────────────────────────────────────

def _icon(ok):
    return "✅" if ok else "—"


def build_report(results):
    lines = [
        f"# 台股籌碼分析篩選報告",
        f"",
        f"更新時間: {TODAY}　　法人連買門檻: ≥ {CONSEC_THRESH} 日",
        f"",
        f"> 集保大戶定義：持股 400 張（400,000股）以上（Level 12–15），比較前後兩期週報。",
        f"",
        f"---",
        f"",
        f'<a id="overview"></a>',
        f"",
        f"## 快速總覽",
        f"",
        f"| 股票 | 外資連買 | 投信連買 | 大戶持股↑ | 籌碼沉澱 | 得分 | 評估 |",
        f"|------|:--------:|:--------:|:---------:|:--------:|:----:|------|",
    ]

    for r in sorted(results, key=lambda x: -x["score"]):
        if r.get("error"):
            lines.append(f"| {r['ticker']} | — | — | — | — | — | ❌ 錯誤 |")
            continue
        sig = r["signals"]
        fi  = f"✅ {r['inst']['fi']} 天" if sig["fi_buy"]  else f"{r['inst']['fi']} 天"
        it  = f"✅ {r['inst']['it']} 天" if sig["it_buy"]  else f"{r['inst']['it']} 天"
        bh  = _icon(sig["big_holder_up"])
        cs  = _icon(sig["chip_settle"])
        sc  = r["score"]
        verdict = "🚀 強力關注" if sc >= 3 else ("⚠️ 值得留意" if sc == 2 else "— 觀望")
        lines.append(f"| [{r['ticker']}](#{r['ticker']}) | {fi} | {it} | {bh} | {cs} | {sc}/4 | {verdict} |")

    lines += ["", "---", ""]

    for r in sorted(results, key=lambda x: -x["score"]):
        lines.append(f'<a id="{r["ticker"]}"></a>')
        lines.append("")
        if r.get("error"):
            lines += [f"## {r['ticker']}", f"", f"> 資料取得失敗: {r['error']}", f"",
                      "[↑ 回到總覽](#overview)", f"", "---", ""]
            continue

        sig = r["signals"]
        inst, mar, sh = r["inst"], r["margin"], r["shareholding"]

        chg_str   = f"{mar['margin_5d_chg']:+.1%}" if mar["margin_5d_chg"] is not None else "N/A"
        ratio_str = f"{sh['big_holder_ratio']:.2f}%" if sh["big_holder_ratio"] is not None else "N/A"
        bh_chg    = f"{sh['big_holder_chg']:+.2f} pp" if sh["big_holder_chg"] is not None else "（首次記錄，下週可比較趨勢）"
        tdcc_date = sh.get("report_date", "N/A")

        margin_note = ""
        if mar["margin_surge"]:
            margin_note = "\n> ⚠️ 融資爆增，留意短線浮額過多造成股價震盪。"
        elif sig["chip_settle"]:
            margin_note = "\n> ✅ 籌碼沉澱，融資減少代表長線投資人承接。"

        lines += [
            f"## {r['ticker']}",
            f"",
            f"[↑ 回到總覽](#overview)",
            f"",
            f"| 指標 | 數值 | 訊號 |",
            f"|------|------|:----:|",
            f"| 外資連續買超 | {inst['fi']} 天 | {_icon(sig['fi_buy'])} |",
            f"| 投信連續買超 | {inst['it']} 天 | {_icon(sig['it_buy'])} |",
            f"| 自營商連續買超 | {inst['dealer']} 天 | — |",
            f"| 大戶（400張+）持股比例 | {ratio_str}（{bh_chg}）（集保日期: {tdcc_date}） | {_icon(sig['big_holder_up'])} |",
            f"| 融資餘額 5 日變化 | {chg_str} | {_icon(sig['chip_settle'])} |",
            margin_note,
            "",
            "---",
            "",
        ]

    return "\n".join(lines)


# ── 主程式 ────────────────────────────────────────────────────────────────────

def main():
    tw_stocks = load_tw_tickers()
    if not tw_stocks:
        print("stocks.yaml 中沒有台股（.TW/.TWO 結尾），無法執行籌碼分析。")
        return

    print(f"台股籌碼分析：{tw_stocks}\n")
    dl = get_loader()
    tdcc_cache = load_tdcc_cache()
    results = []

    for sid in tw_stocks:
        print(f"[{sid}]")
        try:
            inst_df   = fetch_institutional(dl, sid)
            margin_df = fetch_margin(dl, sid)

            inst_r   = analyse_institutional(inst_df)
            margin_r = analyse_margin(margin_df)
            share_r  = analyse_shareholding(sid, tdcc_cache)
            sigs, sc = score(inst_r, margin_r, share_r)

            bh_chg_str = f"{share_r['big_holder_chg']:+.2f}pp" if share_r["big_holder_chg"] is not None else "首次"
            print(f"  外資 {inst_r['fi']}天 | 投信 {inst_r['it']}天 | "
                  f"大戶 {share_r.get('big_holder_ratio','?')}%({bh_chg_str}) | "
                  f"融資 {margin_r['margin_5d_chg']:+.1%}" if margin_r["margin_5d_chg"] is not None
                  else f"  外資 {inst_r['fi']}天 | 投信 {inst_r['it']}天 | 大戶 首次 | 融資 N/A")
            print(f"  → 得分 {sc}/4")

            results.append(dict(
                ticker=sid, inst=inst_r, margin=margin_r,
                shareholding=share_r, signals=sigs, score=sc,
            ))
        except Exception as e:
            import traceback; traceback.print_exc()
            results.append(dict(ticker=sid, error=str(e), score=-1,
                                signals={}, inst={}, margin={}, shareholding={}))

    save_tdcc_cache(tdcc_cache)

    report = build_report(results)
    os.makedirs(REPORT_DIR, exist_ok=True)
    dated_path  = os.path.join(REPORT_DIR, f"chip_report_{TODAY}.md")
    latest_path = os.path.join(REPORT_DIR, "chip_report.md")
    for path in (dated_path, latest_path):
        with open(path, "w") as f:
            f.write(report)

    # JSON for web builder
    chip_data = {
        "updated": TODAY,
        "stocks": [
            {k: v for k, v in r.items() if k != "error"}
            if not r.get("error") else {"ticker": r["ticker"], "error": r["error"]}
            for r in results
        ],
    }
    with open(os.path.join(REPORT_DIR, "chip_data.json"), "w") as f:
        json.dump(chip_data, f, ensure_ascii=False, indent=2)

    print(f"\n籌碼報告已生成: {dated_path}")
    print(f"集保快取已更新: {TDCC_CACHE}")


if __name__ == "__main__":
    main()
