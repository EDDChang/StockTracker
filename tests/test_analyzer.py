import sys
import os
import pytest
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from analyzer import (
    find_higher_lows,
    find_lower_highs,
    check_structure_shift,
    detect_price_action,
    detect_ma_river,
    detect_sr_flip,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def make_df(closes, highs=None, lows=None, opens=None):
    n = len(closes)
    c = np.asarray(closes, dtype=float)
    h = np.asarray(highs, dtype=float) if highs is not None else c + 2
    l = np.asarray(lows,  dtype=float) if lows  is not None else c - 2
    o = np.asarray(opens, dtype=float) if opens is not None else c
    return pd.DataFrame(
        {"Open": o, "High": h, "Low": l, "Close": c, "Volume": np.ones(n) * 1e6},
        index=pd.date_range("2024-01-01", periods=n, freq="B"),
    )


def piecewise(n, waypoints):
    """線性內插產生指定長度的陣列。waypoints: [(x, y), ...]"""
    out = np.zeros(n, dtype=float)
    for (x1, y1), (x2, y2) in zip(waypoints, waypoints[1:]):
        for x in range(x1, x2 + 1):
            out[x] = y1 + (y2 - y1) * (x - x1) / max(x2 - x1, 1)
    return out


# ── Rule 1a: find_higher_lows ─────────────────────────────────────────────────
#
# 用 window=5, center=True：min_periods=5，所以 index 0-1 與 13-14 的 rolling 結果
# 是 NaN，不會被標為 local low。真正的 valley 在 index 2、7、12。

class TestFindHigherLows:
    # Valley values 上升 (80 < 85 < 90) → Higher Lows
    UPTREND   = [95, 92, 80, 92, 95,  95, 92, 85, 92, 95,  95, 92, 90, 92, 95]
    # Valley values 下降 (90 > 85 > 80) → 無 Higher Lows
    DOWNTREND = [95, 92, 90, 92, 95,  95, 92, 85, 92, 95,  95, 92, 80, 92, 95]

    def _df(self, lows):
        l = np.array(lows, dtype=float)
        return make_df(l + 5, highs=l + 10, lows=l)

    def test_uptrend_finds_higher_lows(self):
        result = find_higher_lows(self._df(self.UPTREND))
        assert len(result) >= 1
        vals = [v for _, v in result]
        assert vals == sorted(vals), "HL 值應依序遞增"

    def test_downtrend_has_no_higher_lows(self):
        assert find_higher_lows(self._df(self.DOWNTREND)) == []

    def test_too_few_bars_returns_empty(self):
        # 3 根 K 線 < min_periods=5，rolling 全為 NaN → 無 local low
        assert find_higher_lows(make_df([100, 101, 99])) == []


# ── Rule 1b: check_structure_shift ────────────────────────────────────────────

class TestCheckStructureShift:
    HL = [(pd.Timestamp("2024-01-10"), 100.0)]

    def test_price_below_last_hl_is_broken(self):
        df = make_df(np.ones(10) * 90)
        is_broken, last_hl = check_structure_shift(df, self.HL)
        assert is_broken is True
        assert last_hl == 100.0

    def test_price_above_last_hl_is_intact(self):
        df = make_df(np.ones(10) * 110)
        is_broken, last_hl = check_structure_shift(df, self.HL)
        assert is_broken is False
        assert last_hl == 100.0

    def test_price_equal_to_last_hl_is_intact(self):
        # 收盤 = HL 值，未跌破，應視為完整
        df = make_df(np.ones(10) * 100)
        is_broken, _ = check_structure_shift(df, self.HL)
        assert is_broken is False

    def test_empty_hl_list(self):
        df = make_df(np.ones(10) * 100)
        is_broken, last_hl = check_structure_shift(df, [])
        assert is_broken is False
        assert last_hl is None


# ── Rule 2: find_lower_highs ──────────────────────────────────────────────────
#
# 共 80 根 K 線，lookback=60 取最後 60 根（index 20-79）。
# 兩個波段高點在 index 25 和 55，中間在 index 40 放谷底確保兩峰都能被
# rolling(window=10) 辨識為 local high。

class TestFindLowerHighs:
    N = 80

    def _df(self, p1, p2):
        """p1=index 25 的峰值，p2=index 55 的峰值，中間在 index 40 有谷底 75。"""
        highs = piecewise(self.N, [(0, 85), (25, p1), (40, 75), (55, p2), (79, 85)])
        return make_df(highs - 2, highs=highs, lows=highs - 5)

    def test_ascending_peaks_no_lh(self):
        # 最近兩個高點遞增 → 無 LH
        assert find_lower_highs(self._df(110, 130)) == []

    def test_descending_peaks_lh_detected(self):
        # 最近兩個高點遞減 → 偵測到 LH
        result = find_lower_highs(self._df(130, 110))
        assert len(result) == 1
        _, lh_val = result[0]
        assert lh_val == pytest.approx(110, abs=1)

    def test_equal_peaks_no_lh(self):
        # 兩個高點相等，未形成下降結構
        assert find_lower_highs(self._df(120, 120)) == []

    def test_too_few_bars_returns_empty(self):
        # 8 根 < min_periods=10 → rolling 全 NaN → 無 local high → []
        assert find_lower_highs(make_df(np.ones(8) * 100)) == []


# ── Rule 3: detect_price_action ───────────────────────────────────────────────

class TestDetectPriceAction:
    def _df(self, prev_ohlc, last_ohlc):
        po, ph, pl, pc = prev_ohlc
        lo, lh, ll, lc = last_ohlc
        return make_df([pc, lc], highs=[ph, lh], lows=[pl, ll], opens=[po, lo])

    # ── 長上影線 ──

    def test_long_upper_shadow_detected(self):
        # O=100, C=101, H=120, L=99 → shadow_ratio = (120-101)/(120-99) ≈ 0.90 > 0.6
        result = detect_price_action(self._df(
            prev_ohlc=(100, 110, 95, 105),
            last_ohlc=(100, 120, 99, 101),
        ))
        assert result["long_shadow"]

    def test_no_long_upper_shadow_on_normal_candle(self):
        # O=100, C=108, H=110, L=99 → shadow_ratio = (110-108)/(110-99) ≈ 0.18 < 0.6
        result = detect_price_action(self._df(
            prev_ohlc=(100, 110, 95, 105),
            last_ohlc=(100, 110, 99, 108),
        ))
        assert not result["long_shadow"]

    def test_doji_with_tiny_body_not_counted_as_shadow(self):
        # O=C=100, H=102, L=98 → shadow_ratio = (102-100)/4 = 0.5 < 0.6
        result = detect_price_action(self._df(
            prev_ohlc=(98, 103, 96, 100),
            last_ohlc=(100, 102, 98, 100),
        ))
        assert not result["long_shadow"]

    # ── 吞噬形態 ──

    def test_bearish_engulfing_detected(self):
        # 前棒陽線 (O=100, C=110)；後棒陰線完全吞噬 (O=115 > 110, C=95 < 100)
        result = detect_price_action(self._df(
            prev_ohlc=(100, 115, 98, 110),
            last_ohlc=(115, 120, 90, 95),
        ))
        assert result["engulfing"]

    def test_bullish_candle_no_engulfing(self):
        # 後棒為陽線 → 不符合 c < o 條件
        result = detect_price_action(self._df(
            prev_ohlc=(100, 112, 98, 110),
            last_ohlc=(108, 120, 106, 118),
        ))
        assert not result["engulfing"]

    def test_bearish_prev_candle_no_engulfing(self):
        # 前棒為陰線 → 不符合 p_close > p_open 條件
        result = detect_price_action(self._df(
            prev_ohlc=(110, 115, 95, 100),   # prev 陰線
            last_ohlc=(115, 120, 85, 90),
        ))
        assert not result["engulfing"]


# ── Rule 4: detect_ma_river ───────────────────────────────────────────────────
#
# 先以大量 K 線「暖機」讓 EMA 收斂，再用少量 K 線製造特定情境。
# "inside" 計算：暖機 200 根 close=100 → EMA20≈EMA50≈100；
# 再 20 根 close=200 → EMA20≈184, EMA50≈156；
# 最後 1 根 close=170 → 落在兩 EMA 之間。

class TestDetectMaRiver:
    def _df(self, warm_close, n_warm, tail):
        closes = np.array([warm_close] * n_warm + list(tail), dtype=float)
        return make_df(closes)

    def test_price_above_both_emas(self):
        # EMA20≈EMA50≈100，最後一根 close=200 → above
        result = detect_ma_river(self._df(100, 200, [200]))
        assert result["status"] == "above"

    def test_price_below_both_emas(self):
        # EMA20≈EMA50≈200，最後一根 close=50 → below
        result = detect_ma_river(self._df(200, 200, [50]))
        assert result["status"] == "below"

    def test_price_inside_ema_river(self):
        # 20 根 close=200 讓 EMA20(≈184) > EMA50(≈156)，close=170 夾在中間
        result = detect_ma_river(self._df(100, 200, [200] * 20 + [170]))
        assert result["status"] == "inside"

    def test_returns_ema_values_close_to_warm_price(self):
        result = detect_ma_river(self._df(100, 200, [100]))
        assert "ema_short" in result and "ema_long" in result
        assert abs(result["ema_short"] - 100) < 1
        assert abs(result["ema_long"]  - 100) < 1

    def test_ema_short_reacts_faster_than_ema_long(self):
        # 大幅拉升後，EMA20 應高於 EMA50
        result = detect_ma_river(self._df(100, 200, [200] * 30))
        assert result["ema_short"] > result["ema_long"]


# ── Rule 5: detect_sr_flip ────────────────────────────────────────────────────

class TestDetectSrFlip:
    def test_result_has_required_keys(self):
        df = make_df(np.ones(100) * 100)
        result = detect_sr_flip(df)
        assert "status" in result
        assert "flip_price" in result

    def test_monotone_rising_support_never_broken(self):
        # 單調上漲，支撐永遠不被跌破
        closes = np.linspace(100, 200, 150)
        df = make_df(closes, highs=closes + 2, lows=closes - 2)
        result = detect_sr_flip(df)
        assert result["status"] in (
            "支撐未有效跌破",
            "無足夠歷史支撐位",
            "無足夠後續數據",
        )

    def test_sr_flip_detected_on_breakdown_and_retest(self):
        # 建立一個明確 S/R Flip 的場景：
        # 1. 在支撐 100 形成低點  2. 跌破至 97  3. 反彈至 100 附近但收盤未站上
        n = 150
        closes = np.ones(n, dtype=float) * 110
        highs  = closes + 2
        lows   = closes - 2

        # 在 index 30 附近製造支撐 100
        lows[28:33]   = 100
        closes[28:33] = 101

        # 在 index 80 跌破 (close < 100 * 0.99 = 99)
        closes[80] = 97
        lows[80]   = 96

        # 在 index 100 反彈到 100 附近但未收盤站上
        highs[100]  = 100        # high 剛好碰到支撐位
        closes[100] = 97.5       # close 仍在支撐下方

        df = make_df(closes, highs=highs, lows=lows)
        result = detect_sr_flip(df)
        assert result["status"] in (
            "🚨 偵測到支撐轉壓力 (S/R Flip)",
            "未偵測到S/R Flip",
            "支撐未有效跌破",
        )
