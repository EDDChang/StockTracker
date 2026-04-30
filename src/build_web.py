#!/usr/bin/env python3
"""
build_web.py — 從 trend_data.json + chip_data.json 生成靜態 HTML 儀表板

輸出至 docs/index.html（GitHub Pages 部署目錄）。
K 線圖從 charts/ 複製至 docs/charts/。

使用方式：
  python src/main.py && python src/chip_screen.py && python src/build_web.py
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
    chip_path  = os.path.join(REPORT_DIR, "chip_data.json")
    trend = json.load(open(trend_path)) if os.path.exists(trend_path) else {}
    chip  = json.load(open(chip_path))  if os.path.exists(chip_path)  else {}
    return trend, chip


def chip_index(chip_data):
    return {r["ticker"]: r for r in chip_data.get("stocks", [])}


def safe_id(ticker):
    return ticker.replace(".", "-").replace("^", "").replace("=", "")


# ── Badge helpers ─────────────────────────────────────────────────────────────

def _badge(cls, text):
    return f'<span class="badge {cls}">{text}</span>'

def _muted(text):
    return f'<span class="text-muted">{text}</span>'


def struct_badge(is_broken, streak=0):
    if is_broken:
        s = f"🚨破壞" + (f"({streak}天)" if streak >= 2 else "")
        return _badge("bg-danger", s)
    return _badge("bg-success", "✅")


def ma_badge(ma, streak=0):
    if ma.get("below_ma_long") and ma.get("ma_long_slope_down"):
        s = "🚨" + (f"({streak}天)" if streak >= 2 else "")
        return _badge("bg-danger", s)
    if ma.get("below_ma_long") or (ma.get("below_ma_short") and ma.get("ma_short_slope_down")):
        s = "⚠️" + (f"({streak}天)" if streak >= 2 else "")
        return _badge("bg-warning text-dark", s)
    return _badge("bg-success", "✅")


def tl_badge(tl, streak=0):
    if tl.get("trendline_value") is None:
        return _badge("bg-secondary", "—")
    st = tl.get("status", "")
    if "🚨" in st:
        return _badge("bg-danger", "🚨" + (f"({streak}天)" if streak >= 2 else ""))
    if "⚠️" in st:
        return _badge("bg-warning text-dark", "⚠️" + (f"({streak}天)" if streak >= 2 else ""))
    return _badge("bg-success", "✅")


def overall_badge(is_broken, ma, tl):
    alerts = sum([
        bool(is_broken),
        bool(ma.get("below_ma_long") and ma.get("ma_long_slope_down")),
        bool("🚨" in tl.get("status", "") and tl.get("trendline_value") is not None),
    ])
    warns = sum([
        bool(ma.get("below_ma_long") or (ma.get("below_ma_short") and ma.get("ma_short_slope_down"))),
        bool("⚠️" in tl.get("status", "") and tl.get("trendline_value") is not None),
    ])
    if alerts >= 2: return _badge("bg-danger",              "多重警示")
    if alerts == 1: return _badge("bg-orange",              "留意")
    if warns:       return _badge("bg-warning text-dark",   "觀察")
    return              _badge("bg-success",              "多頭維持")


def inst_badge(days, thresh=3):
    if days >= thresh: return _badge("bg-success",     f"{days}天")
    if days > 0:       return _muted(f"{days}天")
    return _muted("—")


def bh_badge(rising):
    return _badge("bg-success", "↑") if rising else _muted("—")


def margin_badge(chip_r):
    if not chip_r or chip_r.get("error"):
        return _muted("—")
    mar = chip_r.get("margin", {})
    chg = mar.get("margin_5d_chg")
    if mar.get("margin_surge"):
        return _badge("bg-warning text-dark", f"爆增{chg:+.0%}" if chg is not None else "爆增")
    if mar.get("chip_settle"):
        return _badge("bg-success", f"沉澱{chg:+.0%}" if chg is not None else "沉澱")
    if chg is not None:
        return _muted(f"{chg:+.0%}")
    return _muted("—")


# ── Overview table row ────────────────────────────────────────────────────────

def overview_row(r, chip_r, names):
    ticker = r["ticker"]
    name   = names.get(ticker, "")
    sid    = safe_id(ticker)

    if r.get("error"):
        return (f'<tr class="table-secondary">'
                f'<td><strong>{ticker}</strong></td><td>{name}</td>'
                f'<td colspan="9" class="text-danger small">取資料失敗</td></tr>')

    p     = r["price"]
    price = "—" if (p != p) else (f"{p:,.0f}" if p > 1000 else f"{p:.2f}")
    sk    = r.get("streaks", {})
    chip  = chip_r or {}

    fi = inst_badge(chip.get("inst", {}).get("fi", 0))  if chip and not chip.get("error") else _muted("—")
    it = inst_badge(chip.get("inst", {}).get("it", 0))  if chip and not chip.get("error") else _muted("—")
    bh = bh_badge(chip.get("shareholding", {}).get("big_holder_rising", False)) if chip and not chip.get("error") else _muted("—")
    mg = margin_badge(chip_r)

    return (f'<tr>'
            f'<td><a class="ticker-link" onclick="openStock(\'{sid}\')">{ticker}</a></td>'
            f'<td class="text-muted small">{name}</td>'
            f'<td class="text-end fw-semibold">{price}</td>'
            f'<td>{struct_badge(r["is_broken"], sk.get("struct",0))}</td>'
            f'<td>{ma_badge(r["ma_bd"], sk.get("ma",0))}</td>'
            f'<td>{tl_badge(r["tl"], sk.get("tl",0))}</td>'
            f'<td>{fi}</td><td>{it}</td><td>{bh}</td><td>{mg}</td>'
            f'<td>{overall_badge(r["is_broken"], r["ma_bd"], r["tl"])}</td>'
            f'</tr>')


# ── Accordion detail card ─────────────────────────────────────────────────────

def detail_card(r, chip_r, names):
    if r.get("error"):
        return ""
    ticker = r["ticker"]
    name   = names.get(ticker, "")
    sid    = safe_id(ticker)
    p      = r["price"]
    price  = "—" if (p != p) else (f"{p:,.0f}" if p > 1000 else f"{p:.2f}")
    sk     = r.get("streaks", {})
    chart  = r.get("chart", f"{ticker}_chart.png")

    # Trend text
    lh = r.get("last_hl")
    if r["is_broken"] and lh:
        r1 = f'<span class="text-danger">🚨 多頭結構遭破壞（跌破前低 {lh:.2f}）</span>'
    elif lh:
        r1 = f'<span class="text-success">✅ 多頭結構完整（最後 HL: {lh:.2f}）</span>'
    else:
        r1 = '<span class="text-warning">⚠️ 尚無足夠波段低點</span>'

    ma   = r["ma_bd"]
    tl   = r["tl"]
    pa   = r.get("pa", {})
    pa_notes = (["⚠️ 長上影線"] if pa.get("long_shadow") else []) + \
               (["⚠️ 空頭吞噬"] if pa.get("engulfing") else [])
    pa_str = "、".join(pa_notes) or "✅ 無明顯轉弱"
    tl_val = tl.get("trendline_value")
    tl_extra = f" <small class='text-muted'>（趨勢線: {tl_val:.2f}）</small>" if tl_val else ""

    trend_table = (
        f'<table class="table table-sm table-bordered mb-0">'
        f'<tr><td class="w-25 text-muted">結構</td><td>{r1}</td></tr>'
        f'<tr><td class="text-muted">均線</td><td>{ma["status"]}<br>'
        f'<small class="text-muted">MA5: {ma["ma_short"]:.2f} | MA20: {ma["ma_long"]:.2f}</small></td></tr>'
        f'<tr><td class="text-muted">趨勢線</td><td>{tl["status"]}{tl_extra}</td></tr>'
        f'<tr><td class="text-muted">K線訊號</td><td>{pa_str}</td></tr>'
        f'</table>'
    )

    # Chip section (TW stocks only)
    chip_col = ""
    if chip_r and not chip_r.get("error"):
        inst = chip_r.get("inst", {})
        mar  = chip_r.get("margin", {})
        sh   = chip_r.get("shareholding", {})
        chg  = mar.get("margin_5d_chg")
        ratio = sh.get("big_holder_ratio")
        bh_c  = sh.get("big_holder_chg")
        tdcc_d = sh.get("report_date", "")
        chg_str   = f"{chg:+.1%}"   if chg   is not None else "N/A"
        ratio_str = f"{ratio:.2f}%" if ratio  is not None else "N/A"
        bh_chg_str = (f"{bh_c:+.2f} pp" if bh_c is not None else
                      "<small class='text-muted'>首次記錄，下週可比較</small>")
        chip_col = (
            f'<div class="col-lg-5">'
            f'<h6 class="text-primary mb-2">📊 籌碼分析</h6>'
            f'<table class="table table-sm table-bordered mb-0">'
            f'<tr><td class="w-40 text-muted">外資連買</td>'
            f'<td>{inst_badge(inst.get("fi",0))} {inst.get("fi",0)} 天</td></tr>'
            f'<tr><td class="text-muted">投信連買</td>'
            f'<td>{inst_badge(inst.get("it",0))} {inst.get("it",0)} 天</td></tr>'
            f'<tr><td class="text-muted">自營商連買</td>'
            f'<td>{_muted(str(inst.get("dealer", 0)) + " 天")}</td></tr>'
            f'<tr><td class="text-muted">大戶持股（400張+）</td>'
            f'<td>{ratio_str} {bh_badge(sh.get("big_holder_rising",False))} {bh_chg_str}'
            f'<br><small class="text-muted">集保 {tdcc_d}</small></td></tr>'
            f'<tr><td class="text-muted">融資5日變化</td>'
            f'<td>{chg_str} {margin_badge(chip_r)}</td></tr>'
            f'</table></div>'
        )

    header_badge = overall_badge(r["is_broken"], ma, tl)
    streak_note  = (f' <span class="badge bg-danger ms-1">連續{sk["struct"]}天</span>'
                    if sk.get("struct", 0) >= 2 and r["is_broken"] else "")

    return (
        f'<div class="accordion-item" id="s-{sid}">'
        f'<h2 class="accordion-header">'
        f'<button class="accordion-button collapsed py-2" type="button"'
        f' data-bs-toggle="collapse" data-bs-target="#c-{sid}">'
        f'<span class="fw-bold me-2">{ticker}</span>'
        f'<span class="text-muted me-2 small">{name}</span>'
        f'<span class="me-3">{price}</span>'
        f'{header_badge}{streak_note}'
        f'</button></h2>'
        f'<div id="c-{sid}" class="accordion-collapse collapse">'
        f'<div class="accordion-body pt-2">'
        f'<img src="charts/{chart}" class="stock-chart rounded mb-3" alt="{ticker} K線圖">'
        f'<div class="row g-3">'
        f'<div class="col-lg-7">'
        f'<h6 class="text-success mb-2">📈 趨勢分析</h6>'
        f'{trend_table}</div>'
        f'{chip_col}'
        f'</div></div></div></div>'
    )


# ── Full HTML ─────────────────────────────────────────────────────────────────

def build_html(trend, chip, names):
    updated  = trend.get("updated", "—")
    chip_idx = chip_index(chip)

    def get_chip(ticker):
        base = ticker.split(".")[0]
        return chip_idx.get(base)

    refs   = trend.get("refs",   [])
    stocks = trend.get("stocks", [])

    # Market reference banner
    ref_parts = []
    for r in refs:
        if r.get("error"): continue
        t = r["ticker"]
        n = names.get(t, "")
        rv = r["price"]
        p = "—" if (rv != rv) else (f"{rv:,.0f}" if rv > 1000 else f"{rv:.2f}")
        ob = overall_badge(r["is_broken"], r["ma_bd"], r["tl"])
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
        rows.append('<tr class="table-secondary"><td colspan="11" class="fw-bold small py-1">市場指數</td></tr>')
        rows += [overview_row(r, get_chip(r["ticker"]), names) for r in refs]
        rows.append('<tr class="table-secondary"><td colspan="11" class="fw-bold small py-1">個股</td></tr>')
    rows += [overview_row(r, get_chip(r["ticker"]), names) for r in stocks]

    # Detail accordion
    details = [detail_card(r, get_chip(r["ticker"]), names) for r in refs + stocks]

    rows_html    = "\n".join(rows)
    details_html = "\n".join(details)

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
    .accordion-button {{ font-size: 13px; background: #fff; }}
    .accordion-button:not(.collapsed) {{ background: #eef4ff; box-shadow: none; }}
    .ticker-link {{ color: #0d6efd; font-weight: 600; cursor: pointer; text-decoration: none; }}
    .ticker-link:hover {{ text-decoration: underline; }}
    th {{ font-size: 12px; white-space: nowrap; }}
    .badge {{ font-size: 11px; }}
    .bg-orange {{ background-color: #fd7e14 !important; color: #fff; }}
    .table-sm td, .table-sm th {{ padding: .25rem .4rem; }}
    .section-card {{ background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
    footer {{ font-size: 11px; }}
  </style>
</head>
<body>
  <nav class="navbar top-nav sticky-top py-2">
    <div class="container-fluid">
      <span class="navbar-brand text-white">📈 股票追蹤儀表板</span>
      <span class="text-secondary small">更新: {updated}</span>
    </div>
  </nav>

  <div class="market-bar px-4 py-2 small">
    {ref_html}
  </div>

  <div class="container-fluid mt-3 px-4">

    <!-- Overview Table -->
    <div class="section-card mb-4">
      <div class="px-3 pt-3 pb-1">
        <h6 class="text-muted mb-2">快速總覽 <small class="fw-normal">（點擊股票代號展開詳情）</small></h6>
      </div>
      <div class="table-responsive">
        <table class="table table-sm table-hover align-middle mb-0">
          <thead class="table-dark">
            <tr>
              <th>代號</th><th>名稱</th><th class="text-end">收盤</th>
              <th>結構</th><th>均線</th><th>趨勢線</th>
              <th>外資</th><th>投信</th><th>大戶↑</th><th>融資</th>
              <th>綜合</th>
            </tr>
          </thead>
          <tbody>
            {rows_html}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Stock Detail Accordion -->
    <h6 class="text-muted mb-2 px-1">個股詳情</h6>
    <div class="accordion accordion-flush section-card mb-4" id="stocks">
      {details_html}
    </div>

    <footer class="text-center text-muted mt-2 mb-4">
      資料來源：Yahoo Finance · TAIFEX · FinMind · TDCC &nbsp;｜&nbsp; 僅供參考，不構成投資建議
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
  </script>
</body>
</html>'''


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    trend, chip = load_data()
    if not trend:
        print("找不到 reports/trend_data.json，請先執行 python src/main.py")
        return

    names = load_names()
    html  = build_html(trend, chip, names)

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
