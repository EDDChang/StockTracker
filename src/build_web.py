#!/usr/bin/env python3
"""
build_web.py — 從 trend_data.json 生成靜態 HTML 儀表板

輸出至 docs/index.html（GitHub Pages 部署目錄）。
K 線圖從 charts/ 複製至 docs/charts/。
"""

import os
import json
import shutil
import yaml

ROOT_DIR   = os.path.join(os.path.dirname(__file__), "..")
REPORT_DIR = os.path.join(ROOT_DIR, "reports")
CHARTS_DIR = os.path.join(ROOT_DIR, "charts")
DOCS_DIR   = os.path.join(ROOT_DIR, "docs")
CONFIG     = os.path.join(ROOT_DIR, "stocks.yaml")


def load_names():
    with open(CONFIG) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("stock_names", {})


def load_data():
    trend_path = os.path.join(REPORT_DIR, "trend_data.json")
    return json.load(open(trend_path)) if os.path.exists(trend_path) else {}


def safe_id(ticker):
    return ticker.replace(".", "-").replace("^", "").replace("=", "")


# ── Badge helpers ─────────────────────────────────────────────────────────────

def _badge(cls, text):
    return f'<span class="badge {cls}">{text}</span>'

def _muted(text):
    return f'<span class="text-muted">{text}</span>'


def struct_badge(is_broken, streak=0):
    if is_broken:
        s = "🚨破壞" + (f"({streak}天)" if streak >= 2 else "")
        return _badge("bg-danger", s)
    return _badge("bg-success", "✅")


def ma_badges(ma):
    """Four mini badges MA5/10/20/60, green=above, yellow=below↑, red=below↓."""
    above = ma.get("above", {})
    slope = ma.get("slope_up", {})
    parts = []
    for p in ("5", "10", "20", "60"):
        is_above = above.get(p, True)
        is_up    = slope.get(p, True)
        if not is_above and not is_up:
            cls = "bg-danger"
        elif not is_above:
            cls = "bg-warning text-dark"
        else:
            cls = "bg-success"
        parts.append(f'<span class="badge {cls} px-1 me-1" style="font-size:10px">{p}</span>')
    return "".join(parts)


def overall_badge(is_broken, ma):
    sev    = ma.get("severity", "ok")
    alerts = sum([bool(is_broken), sev == "alert"])
    warns  = sev in ("warn", "caution")
    if alerts >= 2: return _badge("bg-danger",            "多重警示")
    if alerts == 1: return _badge("bg-orange",            "留意")
    if warns:       return _badge("bg-warning text-dark", "觀察")
    return              _badge("bg-success",            "多頭維持")


# ── Overview table row ────────────────────────────────────────────────────────

def overview_row(r, names):
    ticker = r["ticker"]
    name   = names.get(ticker, "")
    sid    = safe_id(ticker)

    if r.get("error"):
        return (f'<tr class="table-secondary">'
                f'<td><strong>{ticker}</strong></td><td>{name}</td>'
                f'<td colspan="4" class="text-danger small">取資料失敗</td></tr>')

    p     = r["price"]
    price = "—" if (p != p) else (f"{p:,.0f}" if p > 1000 else f"{p:.2f}")
    sk    = r.get("streaks", {})

    return (f'<tr>'
            f'<td><a class="ticker-link" onclick="openStock(\'{sid}\')">{ticker}</a></td>'
            f'<td class="text-muted small">{name}</td>'
            f'<td class="text-end fw-semibold">{price}</td>'
            f'<td>{struct_badge(r["is_broken"], sk.get("struct", 0))}</td>'
            f'<td>{ma_badges(r["ma"])}</td>'
            f'<td>{overall_badge(r["is_broken"], r["ma"])}</td>'
            f'</tr>')


# ── 2-column card detail ──────────────────────────────────────────────────────

def detail_card(r, names):
    if r.get("error"):
        return ""
    ticker = r["ticker"]
    name   = names.get(ticker, "")
    sid    = safe_id(ticker)
    p      = r["price"]
    price  = "—" if (p != p) else (f"{p:,.0f}" if p > 1000 else f"{p:.2f}")
    sk     = r.get("streaks", {})
    chart  = r.get("chart", f"{ticker}_chart.png")
    ma     = r["ma"]

    # Structure
    lh = r.get("last_hl")
    if r["is_broken"] and lh:
        r1 = f'<span class="text-danger">🚨 破壞（跌破 {lh:.2f}）</span>'
    elif lh:
        r1 = f'<span class="text-success">✅ 完整（HL: {lh:.2f}）</span>'
    else:
        r1 = '<span class="text-warning">⚠️ 不足</span>'

    # MA table rows
    mv    = ma.get("ma_values", {})
    above = ma.get("above", {})
    slope = ma.get("slope_up", {})
    ma_rows = []
    for pp in ("5", "10", "20", "60"):
        val      = mv.get(pp, 0)
        is_above = above.get(pp, True)
        is_up    = slope.get(pp, True)
        if not is_above and not is_up:
            status = '<span class="text-danger fw-semibold">🚨 下方↓</span>'
        elif not is_above:
            status = '<span class="text-warning fw-semibold">⚠️ 下方↑</span>'
        else:
            arrow  = "↑" if is_up else "→"
            status = f'<span class="text-success">✅ 上方{arrow}</span>'
        ma_rows.append(
            f'<tr>'
            f'<td class="text-muted" style="width:46px">MA{pp}</td>'
            f'<td class="text-end pe-2" style="width:72px">{val:.2f}</td>'
            f'<td>{status}</td>'
            f'</tr>'
        )
    ma_table = ('<table class="table table-sm mb-0">'
                + "".join(ma_rows)
                + '</table>')

    # PA signals
    pa       = r.get("pa", {})
    pa_notes = (["⚠️ 長上影線"] if pa.get("long_shadow") else []) + \
               (["⚠️ 空頭吞噬"] if pa.get("engulfing") else [])
    pa_str   = "、".join(pa_notes) or "✅ 無明顯轉弱"

    header_badge = overall_badge(r["is_broken"], ma)
    streak_note  = (f' <span class="badge bg-danger ms-1">連續{sk["struct"]}天</span>'
                    if sk.get("struct", 0) >= 2 and r["is_broken"] else "")

    return (
        f'<div class="col">'
        f'<div class="card h-100" id="s-{sid}">'
        # card header — always visible
        f'<div class="card-header d-flex align-items-center justify-content-between py-2">'
        f'<div>'
        f'<a class="ticker-link fw-bold" onclick="openStock(\'{sid}\')">{ticker}</a>'
        f' <span class="text-muted small ms-1">{name}</span>'
        f' <span class="fw-semibold ms-2">{price}</span>'
        f'</div>'
        f'<div>{header_badge}{streak_note}</div>'
        f'</div>'
        # collapsible body
        f'<div id="c-{sid}" class="collapse">'
        f'<div class="card-body p-2">'
        f'<img src="charts/{chart}" class="stock-chart rounded mb-2" alt="{ticker} K線圖">'
        f'<div class="row g-2 mt-1">'
        # left: structure + PA
        f'<div class="col-5">'
        f'<div class="small fw-semibold text-muted mb-1">結構</div>'
        f'<div class="small">{r1}</div>'
        f'<div class="small text-muted mt-2">{pa_str}</div>'
        f'</div>'
        # right: MA breakdown table
        f'<div class="col-7">'
        f'<div class="small fw-semibold text-muted mb-1">均線</div>'
        f'{ma_table}'
        f'</div>'
        f'</div>'  # row
        f'</div></div>'  # card-body + collapse
        f'</div></div>'  # card + col
    )


# ── Full HTML ─────────────────────────────────────────────────────────────────

def build_html(trend, names):
    updated = trend.get("updated", "—")
    refs    = trend.get("refs",    [])
    stocks  = trend.get("stocks",  [])

    # Market reference banner
    ref_parts = []
    for r in refs:
        if r.get("error"):
            continue
        t  = r["ticker"]
        n  = names.get(t, "")
        rv = r["price"]
        p  = "—" if (rv != rv) else (f"{rv:,.0f}" if rv > 1000 else f"{rv:.2f}")
        ob = overall_badge(r["is_broken"], r["ma"])
        ref_parts.append(
            f'<span class="me-4">'
            f'<strong>{t}</strong> <span class="text-muted small">{n}</span>'
            f' &nbsp; <strong>{p}</strong> &nbsp; {ob}'
            f'</span>'
        )
    ref_html = "\n".join(ref_parts)

    # Overview rows
    rows = []
    if refs:
        rows.append('<tr class="table-secondary"><td colspan="6" class="fw-bold small py-1">市場指數</td></tr>')
        rows += [overview_row(r, names) for r in refs]
        rows.append('<tr class="table-secondary"><td colspan="6" class="fw-bold small py-1">個股</td></tr>')
    rows += [overview_row(r, names) for r in stocks]

    # Detail cards (2-col grid)
    cards = [detail_card(r, names) for r in refs + stocks]

    rows_html  = "\n".join(rows)
    cards_html = "\n".join(cards)

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
        <span class="text-secondary small" id="updated-label">更新: {updated}</span>
        <button id="refresh-btn" class="btn btn-sm btn-outline-light"
                onclick="triggerRefresh()">🔄 更新資料</button>
      </div>
    </div>
  </nav>

  <div class="market-bar px-4 py-2 small">
    {ref_html}
  </div>

  <div class="container-fluid mt-3 px-4">

    <!-- Overview Table -->
    <div class="section-card mb-4">
      <div class="px-3 pt-3 pb-1">
        <h6 class="text-muted mb-2">快速總覽 <small class="fw-normal">（點擊代號展開詳情）</small></h6>
      </div>
      <div class="table-responsive">
        <table class="table table-sm table-hover align-middle mb-0">
          <thead class="table-dark">
            <tr>
              <th>代號</th><th>名稱</th><th class="text-end">收盤</th>
              <th>結構</th><th>MA5 / 10 / 20 / 60</th>
              <th>綜合</th>
            </tr>
          </thead>
          <tbody>
            {rows_html}
          </tbody>
        </table>
      </div>
    </div>

    <!-- 2-column stock cards -->
    <h6 class="text-muted mb-2 px-1">個股詳情</h6>
    <div class="row row-cols-1 row-cols-lg-2 g-3 mb-4" id="stocks">
      {cards_html}
    </div>

    <footer class="text-center text-muted mt-2 mb-4">
      資料來源：Yahoo Finance · FinMind · TDCC &nbsp;｜&nbsp; 僅供參考，不構成投資建議
    </footer>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
  <script>
    function openStock(sid) {{
      const el = document.getElementById('c-' + sid);
      if (!el) return;
      bootstrap.Collapse.getOrCreateInstance(el).show();
      setTimeout(() => {{
        document.getElementById('s-' + sid)
          .scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      }}, 160);
    }}

    async function triggerRefresh() {{
      let token = localStorage.getItem('gh_token');
      if (!token) {{
        token = prompt(
          'GitHub Personal Access Token\\n' +
          '（需要 workflow 權限，首次輸入後會記住）'
        );
        if (!token) return;
        localStorage.setItem('gh_token', token.trim());
        token = token.trim();
      }}
      const btn = document.getElementById('refresh-btn');
      btn.disabled = true;
      btn.textContent = '⏳ 觸發中…';
      try {{
        const res = await fetch(
          'https://api.github.com/repos/EDDChang/StockTracker/actions/workflows/daily.yml/dispatches',
          {{
            method: 'POST',
            headers: {{
              Authorization: `token ${{token}}`,
              Accept: 'application/vnd.github.v3+json',
              'Content-Type': 'application/json',
            }},
            body: JSON.stringify({{ ref: 'main' }}),
          }}
        );
        if (res.status === 204) {{
          btn.textContent = '✅ 已觸發，約 3 分鐘後重整頁面';
          setTimeout(() => {{ btn.disabled = false; btn.textContent = '🔄 更新資料'; }}, 15000);
        }} else if (res.status === 401 || res.status === 403) {{
          localStorage.removeItem('gh_token');
          btn.disabled = false;
          btn.textContent = '🔄 更新資料';
          alert('Token 無效或已過期，請重試。');
        }} else {{
          btn.disabled = false;
          btn.textContent = '🔄 更新資料';
          alert(`觸發失敗（${{res.status}}）`);
        }}
      }} catch (e) {{
        btn.disabled = false;
        btn.textContent = '🔄 更新資料';
        alert('網路錯誤，請確認連線後重試。');
      }}
    }}
  </script>
</body>
</html>'''


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    trend = load_data()
    if not trend:
        print("找不到 reports/trend_data.json，請先執行 python src/main.py")
        return

    names = load_names()
    html  = build_html(trend, names)

    os.makedirs(DOCS_DIR, exist_ok=True)
    index = os.path.join(DOCS_DIR, "index.html")
    with open(index, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML 已生成: {index}")

    # Copy charts
    docs_charts = os.path.join(DOCS_DIR, "charts")
    if os.path.exists(CHARTS_DIR):
        if os.path.exists(docs_charts):
            shutil.rmtree(docs_charts)
        shutil.copytree(CHARTS_DIR, docs_charts)
        print(f"K線圖已複製: {docs_charts}/")


if __name__ == "__main__":
    main()
