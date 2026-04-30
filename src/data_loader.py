import yfinance as yf
import pandas as pd
import requests
from datetime import date, timedelta

# ── TAIFEX 近月期貨 ───────────────────────────────────────────────────────────

TAIFEX_URL = "https://opendata.taifex.com.tw/v1/DailyFuturesOHLC"

def _taifex_near_month(lookback_days=400):
    """
    從 TAIFEX OpenData 取得台指期（TX）近月連續 OHLCV 資料。
    每個交易日自動選擇最近到期（尚未到期）的合約月份。
    """
    start = (date.today() - timedelta(days=lookback_days)).strftime("%Y%m%d")
    end   = date.today().strftime("%Y%m%d")

    r = requests.get(
        TAIFEX_URL,
        params={"commodity_id": "TX", "date_gte": start, "date_lte": end},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError("TAIFEX API 回傳空資料")

    df = pd.DataFrame(data)

    # 欄位正規化（相容不同版本的 API）
    rename = {
        "Date": "trade_date", "date": "trade_date", "tradingDate": "trade_date",
        "ContractMonth": "contract_month", "contractMonth": "contract_month",
        "Open": "Open", "open": "Open", "openPrice": "Open",
        "High": "High", "high": "High", "highPrice": "High",
        "Low": "Low",  "low": "Low",  "lowPrice": "Low",
        "Close": "Close", "close": "Close", "closePrice": "Close",
        "Volume": "Volume", "volume": "Volume", "tradingVolume": "Volume",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    df["trade_date"]     = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d")
    df["contract_month"] = pd.to_numeric(df["contract_month"], errors="coerce")

    for col in ("Open", "High", "Low", "Close", "Volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 每個交易日選出近月合約：最小的 contract_month >= 當日所屬月份
    def _pick_near(grp):
        ym = int(grp.name.strftime("%Y%m"))
        valid = grp[grp["contract_month"] >= ym]
        pool = valid if not valid.empty else grp
        return pool.nsmallest(1, "contract_month").iloc[0]

    near = df.groupby("trade_date", group_keys=False).apply(_pick_near)
    out  = near[["Open", "High", "Low", "Close", "Volume"]].copy()
    out.index = near["trade_date"]
    out.index.name = "Date"
    return out.sort_index().dropna(subset=["Close"])


def get_stock_data(ticker, period="1y"):
    # 台指近月期貨使用 TAIFEX OpenData；其餘走 yfinance
    if ticker == "TX":
        try:
            df = _taifex_near_month()
            print(f"  [TAIFEX] 台指近月資料 {len(df)} 筆")
            return df
        except Exception as e:
            print(f"  [TAIFEX] 無法取得近月資料（{e}），改用 ^TWII")
            ticker = "^TWII"

    df = yf.download(ticker, period=period, auto_adjust=True)
    if df.empty:
        raise ValueError(f"無法獲取 {ticker} 的數據")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df
