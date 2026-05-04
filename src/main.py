import os
import json
import shutil
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

TODAY     = pd.Timestamp.now().strftime("%Y-%m-%d")
ROOT_DIR  = os.path.join(os.path.dirname(__file__), "..")
DATA_DIR  = os.path.join(ROOT_DIR, "reports")
CHARTS_DIR= os.path.join(ROOT_DIR, "charts")
DOCS_DIR  = os.path.join(ROOT_DIR, "docs")
CONFIG    = os.path.join(ROOT_DIR, "stocks.yaml")
HISTORY   = os.path.join(DATA_DIR, "history.json")


# ── config & history ──────────────────────────────────────────────────────────

def load_config():
    with open(CONFIG) as f:
        cfg = yaml.safe_load(f)
    return (cfg.get("market_references", []),
            cfg.get("stocks", []),
            cfg.get("stock_names", {}))

def load_history():
    if os.path.exists(HISTORY):
        with open(HISTORY) as f:
            return json.load(f)
    return {}

def save_history(history):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def extract_signals(r):
    if r.get("error"):
        return None
    sev = r["ma"].get("severity", "ok")
    return {
        "struct": "alert" if r["is_broken"] else "ok",
        "ma":     "alert" if sev == "alert" else ("warn" if sev in ("warn", "caution") else "ok"),
    }

def record_streaks(history, ticker, signals):
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
        for e in reversed(entries):
            if e.get(key, "ok") != "ok":
                count += 1
            else:
                break
        streaks[key] = count
    return streaks


# ── chart ─────────────────────────────────────────────────────────────────────

def generate_chart(ticker, df):
    cutoff = pd.Timestamp.now() - pd.DateOffset(days=200)
    df_c   = df[df.index >= cutoff].copy()
    df_c.index = pd.DatetimeIndex(df_c.index)
    add_plots = [
        mpf.make_addplot(df_c["Close"].rolling(5).mean(),  color="#e74c3c", width=0.9, label="MA5",  linestyle="--"),
        mpf.make_addplot(df_c["Close"].rolling(10).mean(), color="#2ecc71", width=1.0, label="MA10"),
        mpf.make_addplot(df_c["Close"].rolling(20).mean(), color="#f5a623", width=1.2, label="MA20"),
        mpf.make_addplot(df_c["Close"].rolling(60).mean(), color="#4a90d9", width=1.4, label="MA60"),
    ]
    os.makedirs(CHARTS_DIR, exist_ok=True)
    path = os.path.join(CHARTS_DIR, f"{ticker}_chart.png")
    mpf.plot(df_c, type="candle", style="yahoo",
             title=f"{ticker}  Daily Candlestick Chart (Last 200 Days)",
             addplot=add_plots, volume=True, figsize=(14, 7),
             savefig=dict(fname=path, dpi=150, bbox_inches="tight"))
    return f"{ticker}_chart.png"


# ── analysis ──────────────────────────────────────────────────────────────────

def analyse(ticker):
    df = get_stock_data(ticker)
    hl_list           = find_higher_lows(df)
    is_broken, last_hl = check_structure_shift(df, hl_list)
    return dict(
        ticker    = ticker,
        price     = float(df["Close"].dropna().iloc[-1]),
        is_broken = is_broken,
        last_hl   = last_hl,
        ma        = detect_ma_structure(df),
        pa        = detect_price_action(df),
        new_high  = days_since_new_high(df),
        chart     = generate_chart(ticker, df),
    )


# ── badge helpers ─────────────────────────────────────────────────────────────

def _badge(cls, text):
    return f'<span class="badge {cls}">{text}</span>'

def _muted(text):
    return f'<span class="text-muted">{text}</span>'

def _safe_id(ticker):
    return ticker.replace(".", "-").replace("^", "").replace("=", "")

def struct_badge(is_broken, streak=0):
    if is_broken:
        return _badge("bg-danger", "🚨破壞" + (f"({streak}天)" if streak >= 2 else ""))
    return _badge("bg-success", "✅")

def ma_badges(ma):
    above, slope, parts = ma.get("above", {}), ma.get("slope_up", {}), []
    for p in ("5", "10", "20", "60"):
        is_above, is_up = above.get(p, True), slope.get(p, True)
        cls = "bg-danger" if (not is_above and not is_up) else ("bg-warning text-dark" if not is_above else "bg-success")
        parts.append(f'<span class="badge {cls} px-1 me-1" style="font-size:10px">{p}</span>')
    return "".join(parts)

def new_high_badge(nh):
    if not nh:
        return _muted("—")
    days = nh.get("days", 0)
    if days >= 60: return _badge("bg-danger",            f"🚨 {days}天")
    if days >= 20: return _badge("bg-warning text-dark", f"⚠️ {days}天")
    return              _badge("bg-success",            f"✅ {days}天")

def overall_badge(is_broken, ma):
    sev = ma.get("severity", "ok")
    alerts = sum([bool(is_broken), sev == "alert"])
    if alerts >= 2: return _badge("bg-danger",            "多重警示")
    if alerts == 1: return _badge("bg-orange",            "留意")
    if sev in ("warn", "caution"): return _badge("bg-warning text-dark", "觀察")
    return                         _badge("bg-success",  "多頭維持")


# ── HTML rows & cards ─────────────────────────────────────────────────────────

def overview_row(r, names):
    ticker, sid = r["ticker"], _safe_id(r["ticker"])
    name = names.get(ticker, "")
    if r.get("error"):
        return (f'<tr class="table-secondary"><td><strong>{ticker}</strong></td>'
                f'<td>{name}</td><td colspan="5" class="text-danger small">取資料失敗</td></tr>')
    p     = r["price"]
    price = f"{p:,.0f}" if p > 1000 else f"{p:.2f}"
    sk    = r.get("streaks", {})
    return (f'<tr>'
            f'<td><a class="ticker-link" onclick="openStock(\'{sid}\')">{ticker}</a></td>'
            f'<td class="text-muted small">{name}</td>'
            f'<td class="text-end fw-semibold">{price}</td>'
            f'<td>{struct_badge(r["is_broken"], sk.get("struct", 0))}</td>'
            f'<td>{ma_badges(r["ma"])}</td>'
            f'<td>{new_high_badge(r.get("new_high"))}</td>'
            f'<td>{overall_badge(r["is_broken"], r["ma"])}</td>'
            f'</tr>')

def detail_card(r, names):
    if r.get("error"):
        return ""
    ticker, sid = r["ticker"], _safe_id(r["ticker"])
    name  = names.get(ticker, "")
    p     = r["price"]
    price = f"{p:,.0f}" if p > 1000 else f"{p:.2f}"
    sk, ma = r.get("streaks", {}), r["ma"]

    lh = r.get("last_hl")
    if r["is_broken"] and lh:
        r1 = f'<span class="text-danger">🚨 破壞（跌破 {lh:.2f}）</span>'
    elif lh:
        r1 = f'<span class="text-success">✅ 完整（HL: {lh:.2f}）</span>'
    else:
        r1 = '<span class="text-warning">⚠️ 不足</span>'

    mv, above, slope = ma.get("ma_values", {}), ma.get("above", {}), ma.get("slope_up", {})
    ma_rows = []
    for pp in ("5", "10", "20", "60"):
        val, is_above, is_up = mv.get(pp, 0), above.get(pp, True), slope.get(pp, True)
        if not is_above and not is_up:
            st = '<span class="text-danger fw-semibold">🚨 下方↓</span>'
        elif not is_above:
            st = '<span class="text-warning fw-semibold">⚠️ 下方↑</span>'
        else:
            st = f'<span class="text-success">✅ 上方{"↑" if is_up else "→"}</span>'
        ma_rows.append(f'<tr><td class="text-muted" style="width:46px">MA{pp}</td>'
                       f'<td class="text-end pe-2" style="width:72px">{val:.2f}</td>'
                       f'<td>{st}</td></tr>')
    ma_table = '<table class="table table-sm mb-0">' + "".join(ma_rows) + '</table>'

    pa    = r.get("pa", {})
    pa_notes = (["⚠️ 長上影線"] if pa.get("long_shadow") else []) + \
               (["⚠️ 空頭吞噬"] if pa.get("engulfing") else [])
    pa_str = "、".join(pa_notes) or "✅ 無明顯轉弱"

    nh = r.get("new_high")
    nh_detail = (f' <span class="text-muted" style="font-size:10px">'
                 f'高點 {nh["peak_price"]:,.2f}（{nh["peak_date"]}）</span>' if nh else "")

    streak_note = (f' <span class="badge bg-danger ms-1">連續{sk["struct"]}天</span>'
                   if sk.get("struct", 0) >= 2 and r["is_broken"] else "")

    return (
        f'<div class="col"><div class="card h-100" id="s-{sid}">'
        f'<div class="card-header d-flex align-items-center justify-content-between py-2">'
        f'<div><a class="ticker-link fw-bold" onclick="openStock(\'{sid}\')">{ticker}</a>'
        f' <span class="text-muted small ms-1">{name}</span>'
        f' <span class="fw-semibold ms-2">{price}</span></div>'
        f'<div>{overall_badge(r["is_broken"], ma)}{streak_note}</div></div>'
        f'<div id="c-{sid}" class="collapse"><div class="card-body p-2">'
        f'<img src="charts/{r["chart"]}" class="stock-chart rounded mb-2" alt="{ticker} K線圖">'
        f'<div class="row g-2 mt-1">'
        f'<div class="col-5">'
        f'<div class="small fw-semibold text-muted mb-1">結構</div>'
        f'<div class="small">{r1}</div>'
        f'<div class="small text-muted mt-2">{pa_str}</div>'
        f'<div class="small text-muted mt-2">距新高 {new_high_badge(nh)}{nh_detail}</div>'
        f'</div>'
        f'<div class="col-7">'
        f'<div class="small fw-semibold text-muted mb-1">均線</div>'
        f'{ma_table}</div>'
        f'</div></div></div></div></div>'
    )


# ── HTML template ─────────────────────────────────────────────────────────────

def build_html(ref_results, stock_results, names):
    ref_parts = []
    for r in ref_results:
        if r.get("error"):
            continue
        p  = r["price"]
        px = f"{p:,.0f}" if p > 1000 else f"{p:.2f}"
        ref_parts.append(
            f'<span class="me-4"><strong>{r["ticker"]}</strong>'
            f' <span class="text-muted small">{names.get(r["ticker"], "")}</span>'
            f' &nbsp; <strong>{px}</strong> &nbsp; {overall_badge(r["is_broken"], r["ma"])}</span>'
        )

    rows = []
    if ref_results:
        rows.append('<tr class="table-secondary"><td colspan="7" class="fw-bold small py-1">市場指數</td></tr>')
        rows += [overview_row(r, names) for r in ref_results]
        rows.append('<tr class="table-secondary"><td colspan="7" class="fw-bold small py-1">個股</td></tr>')
    rows += [overview_row(r, names) for r in stock_results]

    cards = [detail_card(r, names) for r in ref_results + stock_results]

    return f'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>股票追蹤儀表板</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body {{ font-size: 13px; background: #f5f7fa; }}
    .top-nav {{ background: #1a1a2e; }}
    .top-nav .navbar-brand {{ font-size: 1rem; letter-spacing: .03em; }}
    .market-bar {{ background: #2d2d44; color: #e0e0e0; }}
    .stock-chart {{ max-width: 100%; height: auto; border: 1px solid #dee2e6; }}
    .card-header {{ font-size: 13px; background: #fff; }}
    .ticker-link {{ color: #0d6efd; font-weight: 600; cursor: pointer; text-decoration: none; }}
    .ticker-link:hover {{ text-decoration: underline; }}
    th {{ font-size: 12px; white-space: nowrap; }}
    .badge {{ font-size: 11px; }}
    .bg-orange {{ background-color: #fd7e14 !important; color: #fff; }}
    .table-sm td, .table-sm th {{ padding: .2rem .35rem; }}
    .section-card {{ background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
    footer {{ font-size: 11px; }}
  </style>
</head>
<body>
  <nav class="navbar top-nav sticky-top py-2">
    <div class="container-fluid">
      <span class="navbar-brand text-white">📈 股票追蹤儀表板</span>
      <div class="d-flex align-items-center gap-2">
        <span class="text-secondary small">更新: {TODAY}</span>
        <button id="refresh-btn" class="btn btn-sm btn-outline-light"
                onclick="triggerRefresh()">🔄 更新資料</button>
      </div>
    </div>
  </nav>
  <div class="market-bar px-4 py-2 small">{"".join(ref_parts)}</div>
  <div class="container-fluid mt-3 px-4">
    <div class="section-card mb-4">
      <div class="px-3 pt-3 pb-1">
        <h6 class="text-muted mb-2">快速總覽 <small class="fw-normal">（點擊代號展開詳情）</small></h6>
      </div>
      <div class="table-responsive">
        <table class="table table-sm table-hover align-middle mb-0">
          <thead class="table-dark">
            <tr>
              <th>代號</th><th>名稱</th><th class="text-end">收盤</th>
              <th>結構</th><th>MA5 / 10 / 20 / 60</th><th>距新高</th><th>綜合</th>
            </tr>
          </thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>
    </div>
    <h6 class="text-muted mb-2 px-1">個股詳情</h6>
    <div class="row row-cols-1 row-cols-lg-2 g-3 mb-4" id="stocks">{"".join(cards)}</div>
    <footer class="text-center text-muted mt-2 mb-4">
      資料來源：Yahoo Finance &nbsp;｜&nbsp; 僅供參考，不構成投資建議
    </footer>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
  <script>
    function openStock(sid) {{
      const el = document.getElementById('c-' + sid);
      if (!el) return;
      bootstrap.Collapse.getOrCreateInstance(el).show();
      setTimeout(() => {{
        document.getElementById('s-' + sid).scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      }}, 160);
    }}
    async function triggerRefresh() {{
      let token = localStorage.getItem('gh_token');
      if (!token) {{
        token = prompt('GitHub Personal Access Token\n（需要 workflow 權限，首次輸入後會記住）');
        if (!token) return;
        localStorage.setItem('gh_token', token.trim());
        token = token.trim();
      }}
      const btn = document.getElementById('refresh-btn');
      btn.disabled = true; btn.textContent = '⏳ 觸發中…';
      try {{
        const res = await fetch(
          'https://api.github.com/repos/EDDChang/StockTracker/actions/workflows/daily.yml/dispatches',
          {{ method: 'POST',
             headers: {{ Authorization: `token ${{token}}`, Accept: 'application/vnd.github.v3+json', 'Content-Type': 'application/json' }},
             body: JSON.stringify({{ ref: 'main' }}) }}
        );
        if (res.status === 204) {{
          btn.textContent = '✅ 已觸發，約 3 分鐘後重整頁面';
          setTimeout(() => {{ btn.disabled = false; btn.textContent = '🔄 更新資料'; }}, 15000);
        }} else if (res.status === 401 || res.status === 403) {{
          localStorage.removeItem('gh_token'); btn.disabled = false; btn.textContent = '🔄 更新資料';
          alert('Token 無效或已過期，請重試。');
        }} else {{
          btn.disabled = false; btn.textContent = '🔄 更新資料';
          alert(`觸發失敗（${{res.status}}）`);
        }}
      }} catch (e) {{
        btn.disabled = false; btn.textContent = '🔄 更新資料';
        alert('網路錯誤，請確認連線後重試。');
      }}
    }}
  </script>
</body>
</html>'''


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    refs, stocks, names = load_config()
    history = load_history()

    ref_results, stock_results = [], []

    for ticker, bucket in [(t, "ref") for t in refs] + [(t, "stock") for t in stocks]:
        try:
            r = analyse(ticker)
            r["streaks"] = record_streaks(history, ticker, extract_signals(r))
            (ref_results if bucket == "ref" else stock_results).append(r)
            print(f"已分析: {ticker}")
        except Exception as e:
            err = dict(ticker=ticker, error=str(e), streaks={"struct": 0, "ma": 0})
            (ref_results if bucket == "ref" else stock_results).append(err)
            print(f"錯誤 {ticker}: {e}")
            import traceback; traceback.print_exc()

    save_history(history)

    html = build_html(ref_results, stock_results, names)
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    docs_charts = os.path.join(DOCS_DIR, "charts")
    if os.path.exists(docs_charts):
        shutil.rmtree(docs_charts)
    shutil.copytree(CHARTS_DIR, docs_charts)

    print("完成")
