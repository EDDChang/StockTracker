import pandas as pd

def find_higher_lows(df, window=5):
    df['is_low'] = df['Low'] == df['Low'].rolling(window=window, center=True).min()
    lows = df[df['is_low']]['Low']
    hl_list = []
    prev_low = None
    for date, val in lows.items():
        if prev_low is not None and val > prev_low:
            hl_list.append((date, val))
        prev_low = val
    return hl_list

def find_lower_highs(df, window=10, lookback=60):
    # 用較大的 window 抓出有意義的波段高點，只看近期
    df_recent = df.iloc[-lookback:].copy()
    df_recent['is_high'] = df_recent['High'] == df_recent['High'].rolling(window=window, center=True).max()
    highs = df_recent[df_recent['is_high']]['High']

    if len(highs) < 2:
        return []

    # 只比較最後兩個波段高點：最新高點低於前一個才算 LH
    last_two = list(highs.items())[-2:]
    if last_two[1][1] < last_two[0][1]:
        return [last_two[1]]
    return []

def detect_price_action(df):
    """
    偵測長上影線、吞噬形態
    """
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # 修正：確保取出的值是純量 (scalar)
    h = last['High'].item() if isinstance(last['High'], pd.Series) else last['High']
    o = last['Open'].item() if isinstance(last['Open'], pd.Series) else last['Open']
    c = last['Close'].item() if isinstance(last['Close'], pd.Series) else last['Close']
    l = last['Low'].item() if isinstance(last['Low'], pd.Series) else last['Low']
    
    # 長上影線：(High - max(o, c)) / (h - l + 1e-9)
    shadow_ratio = (h - max(o, c)) / (h - l + 1e-9)
    has_long_shadow = shadow_ratio > 0.6
    
    # 吞噬形態
    p_open = prev['Open'].item() if isinstance(prev['Open'], pd.Series) else prev['Open']
    p_close = prev['Close'].item() if isinstance(prev['Close'], pd.Series) else prev['Close']
    
    is_engulfing = (p_close > p_open) and (c < o) and (c < p_open) and (o > p_close)
    
    return {
        "long_shadow": has_long_shadow,
        "engulfing": is_engulfing
    }

def detect_ma_river(df, short_period=20, long_period=50):
    """
    偵測均線河流 (EMA 20 & EMA 50)
    """
    df['ema_short'] = df['Close'].ewm(span=short_period, adjust=False).mean()
    df['ema_long'] = df['Close'].ewm(span=long_period, adjust=False).mean()
    
    last_close = df['Close'].iloc[-1].item() if isinstance(df['Close'].iloc[-1], pd.Series) else df['Close'].iloc[-1]
    ema_short = df['ema_short'].iloc[-1].item() if isinstance(df['ema_short'].iloc[-1], pd.Series) else df['ema_short'].iloc[-1]
    ema_long = df['ema_long'].iloc[-1].item() if isinstance(df['ema_long'].iloc[-1], pd.Series) else df['ema_long'].iloc[-1]
    
    river_top = max(ema_short, ema_long)
    river_bottom = min(ema_short, ema_long)
    
    status = "above" # 在河流上方
    if last_close < river_bottom:
        status = "below" # 跌破河流
    elif river_bottom <= last_close <= river_top:
        status = "inside" # 進入河流
        
    return {
        "status": status,
        "ema_short": ema_short,
        "ema_long": ema_long
    }

def find_significant_lows(df, window=10, lookback_period=60):
    """
    尋找近期重要的低點作為潛在支撐位
    """
    df_recent = df.iloc[-lookback_period:].copy() # 使用 .copy() 避免 SettingWithCopyWarning
    df_recent['is_min'] = (df_recent['Low'] == df_recent['Low'].rolling(window=window, center=True).min())
    significant_lows = df_recent.loc[df_recent['is_min'] & (df_recent['Low'] > 0), ['Low']]
    return significant_lows.sort_index(ascending=False) # 由近到遠排序

def detect_sr_flip(df, price_tolerance=0.01, lookback_period=90):
    """
    偵測支撐轉壓力 (Support/Resistance Flip)
    """
    # 1. 尋找潛在的歷史支撐位 (significant lows)
    significant_lows = find_significant_lows(df, lookback_period=lookback_period)

    if significant_lows.empty or len(significant_lows) < 2:
        return {"status": "無足夠歷史支撐位", "flip_price": None}

    # 找到最近的幾個重要低點
    recent_lows = significant_lows.iloc[:2]
    
    # 假設最近期的低點是潛在的支撐位
    potential_support_price = recent_lows.iloc[0]['Low']
    potential_support_date = recent_lows.index[0]

    current_price = df['Close'].iloc[-1].item()
    
    # 判斷支撐是否被跌破
    # 我們需要判斷在 potential_support_date 之後，價格是否有明確跌破這個支撐
    # 並且近期有嘗試反彈但受阻於此
    
    # 這個部分需要更複雜的邏輯來判斷「有效跌破」和「反彈受阻」
    # 為了簡化，目前先返回一個預設狀態
    # return {"status": "待觀察 (邏輯待完善)", "flip_price": potential_support_price}

    # 2. 判斷支撐是否被有效跌破
    # 在潛在支撐位形成之後，是否有K線收盤價明顯低於該支撐位
    df_after_support = df[df.index > potential_support_date]
    if df_after_support.empty:
        return {"status": "無足夠後續數據", "flip_price": potential_support_price}

    # 找出第一次有效跌破的點
    break_down_points = df_after_support[df_after_support['Close'] < potential_support_price * (1 - price_tolerance)]
    if break_down_points.empty:
        return {"status": "支撐未有效跌破", "flip_price": potential_support_price}
    
    first_break_date = break_down_points.index[0]

    # 3. 判斷跌破後價格反彈是否被該價位阻擋 (S/R Flip)
    # 在支撐被跌破之後，價格是否有反彈到原支撐位附近，並被阻擋
    df_after_break = df[df.index > first_break_date]
    if df_after_break.empty:
        return {"status": "跌破後無反彈數據", "flip_price": potential_support_price}

    # 尋找反彈到原支撐位附近的K線，且高點未明顯突破原支撐位
    # 反彈的高點在 (potential_support_price * (1 - price_tolerance)) 到 (potential_support_price * (1 + price_tolerance)) 之間
    # 並且收盤價未能站穩在 potential_support_price 之上
    
    sr_flip_found = False
    for idx, row in df_after_break.iterrows():
        current_high = row['High'].item() if isinstance(row['High'], pd.Series) else row['High']
        current_close = row['Close'].item() if isinstance(row['Close'], pd.Series) else row['Close']

        # 價格反彈到原支撐位附近
        if (potential_support_price * (1 - price_tolerance) <= current_high <= potential_support_price * (1 + price_tolerance)) and \
           (current_close < potential_support_price * (1 - price_tolerance)):
            sr_flip_found = True
            break

    if sr_flip_found:
        return {"status": "🚨 偵測到支撐轉壓力 (S/R Flip)", "flip_price": potential_support_price}
    else:
        return {"status": "未偵測到S/R Flip", "flip_price": potential_support_price}


def detect_ma_structure(df, periods=(5, 10, 20, 60), slope_window=5):
    """MA5/MA10/MA20/MA60 positions, slopes, and bullish alignment."""
    d = df.copy()
    last_close = float(d['Close'].dropna().iloc[-1])

    ma_vals = {}
    above = {}
    slope_up = {}

    for p in periods:
        col = f"_ma{p}"
        d[col] = d['Close'].rolling(p).mean()
        val      = float(d[col].iloc[-1])
        prev_val = float(d[col].iloc[-(slope_window + 1)])
        ma_vals[p]  = round(val, 2)
        above[p]    = last_close >= val
        slope_up[p] = val > prev_val

    below_60 = not above[60]
    below_20 = not above[20]
    below_10 = not above[10]
    below_5  = not above[5]
    ma60_down = not slope_up[60]
    ma20_down = not slope_up[20]
    ma10_down = not slope_up[10]

    if below_60 or (below_20 and ma20_down):
        severity = "alert"
    elif below_20 or (below_10 and ma10_down):
        severity = "warn"
    elif below_5:
        severity = "caution"
    else:
        severity = "ok"

    parts = []
    if below_60 and ma60_down:
        parts.append(f"🚨 跌破 MA60（{ma_vals[60]:.2f}）且下彎")
    elif below_60:
        parts.append(f"🚨 跌破 MA60（{ma_vals[60]:.2f}）")
    if below_20 and ma20_down:
        parts.append(f"🚨 跌破 MA20（{ma_vals[20]:.2f}）且下彎")
    elif below_20:
        parts.append(f"⚠️ 跌破 MA20（{ma_vals[20]:.2f}）")
    if below_10 and ma10_down and not below_20:
        parts.append(f"⚠️ 跌破 MA10（{ma_vals[10]:.2f}）且下彎")
    elif below_10 and not below_20:
        parts.append(f"⚠️ 跌破 MA10（{ma_vals[10]:.2f}）")
    if below_5 and not below_10:
        parts.append(f"⚠️ 跌破 MA5（{ma_vals[5]:.2f}）")

    aligned_bullish = (ma_vals[5] > ma_vals[10] > ma_vals[20] > ma_vals[60])

    if parts:
        status = " / ".join(parts)
    elif aligned_bullish:
        status = "✅ 多頭排列（MA5 > MA10 > MA20 > MA60）"
    else:
        status = (f"✅ 收盤高於各均線 "
                  f"MA5 {ma_vals[5]:.2f} | MA10 {ma_vals[10]:.2f} | "
                  f"MA20 {ma_vals[20]:.2f} | MA60 {ma_vals[60]:.2f}")

    return {
        "status": status,
        "severity": severity,
        "ma_values": ma_vals,
        "above": above,
        "slope_up": slope_up,
        "aligned_bullish": aligned_bullish,
        "close": last_close,
    }


def detect_ma_breakdown(df, short_ma=5, long_ma=20, slope_window=5):
    """Rule 2: 均線跌破 — 收盤跌破均線且斜率走平/下彎時發出警示。"""
    d = df.copy()
    d['_ma_s'] = d['Close'].rolling(short_ma).mean()
    d['_ma_l'] = d['Close'].rolling(long_ma).mean()

    last_close = float(d['Close'].iloc[-1])
    ma_s = float(d['_ma_s'].iloc[-1])
    ma_l = float(d['_ma_l'].iloc[-1])

    # 斜率：與 slope_window 根前比較
    ma_s_prev = float(d['_ma_s'].iloc[-(slope_window + 1)])
    ma_l_prev = float(d['_ma_l'].iloc[-(slope_window + 1)])
    s_slope_down = ma_s <= ma_s_prev
    l_slope_down = ma_l <= ma_l_prev

    below_s = last_close < ma_s
    below_l = last_close < ma_l

    warnings = []
    if below_l and l_slope_down:
        warnings.append(f"🚨 跌破 MA{long_ma}（{ma_l:.2f}）且均線下彎")
    elif below_l:
        warnings.append(f"⚠️ 跌破 MA{long_ma}（{ma_l:.2f}）")
    if below_s and s_slope_down:
        warnings.append(f"⚠️ 跌破 MA{short_ma}（{ma_s:.2f}）且均線走平/下彎")
    elif below_s and not below_l:
        warnings.append(f"⚠️ 跌破 MA{short_ma}（{ma_s:.2f}）")

    status = " / ".join(warnings) if warnings else f"✅ 收盤維持在 MA{short_ma}（{ma_s:.2f}）與 MA{long_ma}（{ma_l:.2f}）上方"
    return {
        "status": status,
        "below_ma_short": below_s,
        "below_ma_long": below_l,
        "ma_short_slope_down": s_slope_down,
        "ma_long_slope_down": l_slope_down,
        "ma_short": ma_s,
        "ma_long": ma_l,
    }


def detect_trendline_break(df, hl_list, volume_ratio=1.5):
    """Rule 3: 趨勢線跌破 — 連接最近兩個 HL 構成上升趨勢線，偵測長黑K或爆量跌破。"""
    if len(hl_list) < 2:
        return {"status": "無足夠波段低點（需至少 2 個 HL）", "trendline_value": None, "broken": False}

    (date0, val0), (date1, val1) = hl_list[-2], hl_list[-1]
    current_date = df.index[-1]
    total_days = (date1 - date0).days
    if total_days <= 0:
        return {"status": "無法計算趨勢線（日期重疊）", "trendline_value": None, "broken": False}

    slope = (val1 - val0) / total_days
    projected = val0 + slope * (current_date - date0).days

    last = df.iloc[-1]
    last_close = float(last['Close'])
    last_open  = float(last['Open'])
    last_high  = float(last['High'])
    last_vol   = float(last['Volume'])
    avg_vol    = float(df['Volume'].rolling(20).mean().iloc[-1])

    broken = last_close < projected
    if broken:
        candle_range = last_high - float(last['Low'])
        is_long_bearish = (
            last_open > last_close and candle_range > 0 and
            (last_open - last_close) / candle_range > 0.6
        )
        is_high_vol = not pd.isna(avg_vol) and last_vol > avg_vol * volume_ratio
        if is_long_bearish or is_high_vol:
            status = "🚨 有效跌破上升趨勢線（長黑K/爆量確認）"
        else:
            status = "⚠️ 跌破上升趨勢線（量能或K線未充分確認）"
    else:
        status = f"✅ 趨勢線完整（現價高於趨勢線 {last_close - projected:.2f}）"

    return {"status": status, "trendline_value": round(projected, 2), "broken": broken}


def check_structure_shift(df, hl_list):
    if not hl_list:
        return False, None
    last_hl_date, last_hl_val = hl_list[-1]
    current_price = df['Close'].iloc[-1].item() if isinstance(df['Close'].iloc[-1], pd.Series) else df['Close'].iloc[-1]
    if current_price < last_hl_val:
        return True, last_hl_val
    return False, last_hl_val
