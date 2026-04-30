# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

```bash
# 執行分析並產生報告與 K 線圖
python src/main.py

# 執行所有 unit tests
python -m pytest tests/test_analyzer.py -v

# 執行單一測試
python -m pytest tests/test_analyzer.py::TestFindLowerHighs::test_descending_peaks_lh_detected -v
```

## Architecture

### Entry point & orchestration — `src/main.py`
讀取 `stocks.yaml` 的股票清單，對每支股票：
1. 呼叫 `data_loader.get_stock_data()` 下載資料
2. 呼叫 `analyzer.py` 的各偵測函式
3. 呼叫 `generate_chart()` 產生 K 線圖 PNG 存入 `charts/`
4. 呼叫 `build_report()` 組裝 Markdown 區塊
5. 將所有股票的報告合併寫入 `reports/report.md`

### Stock list — `stocks.yaml`
新增或移除追蹤股票只需編輯此檔，格式：
```yaml
stocks:
  - AAPL
  - 2330.TW
```

### Analysis rules — `src/analyzer.py`
五個獨立規則，各回傳 dict 或 list：

| 函式 | Rule | 說明 |
|------|------|------|
| `find_higher_lows(df, window=5)` | 1a | 找全段 Higher Low 序列 |
| `check_structure_shift(df, hl_list)` | 1b | 當前價跌破最後一個 HL → 結構轉變 |
| `find_lower_highs(df, window=10, lookback=60)` | 2 | 只看近 60 根的最後兩個波段高點是否下降 |
| `detect_price_action(df)` | 3 | 偵測長上影線（ratio > 0.6）與空頭吞噬 |
| `detect_ma_river(df, short=20, long=50)` | 4 | EMA 河流：above / inside / below |
| `detect_sr_flip(df)` | 5 | 支撐被跌破後反彈受阻 → S/R Flip |

### Data loading — `src/data_loader.py`
使用 `yfinance` 下載資料，並將新版 yfinance 回傳的 MultiIndex columns 攤平為單層。

### Outputs
- `reports/report.md` — 所有股票合併的分析報告（Markdown，含圖片連結）
- `charts/{TICKER}_chart.png` — 近 200 天日線 K 線圖（含 EMA 20/50 與成交量）

### Tests — `tests/test_analyzer.py`
使用 `make_df()` 與 `piecewise()` 輔助函式建立合成 OHLCV DataFrame 進行單元測試。
`detect_price_action` 回傳值為 `np.bool_`，斷言需用 `assert value` / `assert not value`，不可用 `is True`。
