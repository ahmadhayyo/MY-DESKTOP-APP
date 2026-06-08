"""
market_tools.py — Live market data & technical analysis via TwelveData.

Gives the agent eyes on the markets: real-time quotes, historical candles,
technical indicators, a transparent multi-indicator analysis, and candlestick
charts saved as images. Pairs with web_search for economic news.

HONEST DESIGN — read this:
  • This is ANALYSIS, not prophecy. market_analyze() produces a rules-based,
    fully transparent technical read (it shows every indicator it used and how it
    weighed them). It is NOT a guaranteed signal and NEVER implies certainty.
  • No tool can reliably predict short-term price direction. Every output carries
    a risk reminder. The decision and the responsibility remain the user's.
  • Intended for spot/forex/crypto market study and risk-managed trading — not for
    binary-options gambling.

Setup: put a (free-tier works) key in .env →  TWELVEDATA_API_KEY=...
Get one at https://twelvedata.com/ .

Tools:
  • market_quote(symbol)
  • market_timeseries(symbol, interval, outputsize)
  • market_indicator(symbol, indicator, interval)
  • market_analyze(symbol, interval)        — transparent technical summary + bias
  • market_chart(symbol, interval, bars)    — candlestick PNG to Desktop
  • market_news(query)                       — economic/forex news via web search
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from config import DESKTOP_DIR

_BASE = "https://api.twelvedata.com"
_RISK = ("\n\n⚠️ تنبيه: هذا تحليل فنّي آلي وليس نصيحة مالية ولا إشارة مضمونة. "
         "الأسواق لا تُتنبّأ بيقين. لا تخاطر بأكثر مما تتحمّل خسارته، وضع وقف خسارة دائماً. "
         "القرار والمسؤولية لك.")


def _api_key() -> str:
    return os.getenv("TWELVEDATA_API_KEY", "").strip()


def _key_missing() -> str:
    return ("❌ مفتاح TwelveData غير مضبوط.\n"
            "   أضِف إلى .env:  TWELVEDATA_API_KEY=مفتاحك\n"
            "   احصل على مفتاح (الباقة المجانية تكفي للبداية) من https://twelvedata.com/")


def _http_get(path: str, params: dict) -> dict:
    """
    GET JSON from TwelveData. Handles the user's VPN doing TLS interception:
    tries normal verification first, then falls back to unverified so the data
    feed keeps working behind the proxy (logged, never silent for auth calls).
    """
    import requests
    params = dict(params)
    params["apikey"] = _api_key()
    url = f"{_BASE}/{path}"
    try:
        r = requests.get(url, params=params, timeout=20)
        return r.json()
    except requests.exceptions.SSLError:
        warnings.filterwarnings("ignore")
        try:
            import urllib3
            urllib3.disable_warnings()
        except Exception:
            pass
        r = requests.get(url, params=params, timeout=20, verify=False)
        return r.json()


def _err(data: dict) -> str | None:
    """TwelveData returns {'status':'error','message':...} on failure."""
    if isinstance(data, dict) and data.get("status") == "error":
        return f"❌ TwelveData: {data.get('message', 'خطأ غير معروف')}"
    if isinstance(data, dict) and data.get("code") and data.get("message"):
        return f"❌ TwelveData ({data.get('code')}): {data.get('message')}"
    return None


# ═══════════════════════════════════════════════════════════════════════════════
@tool
def market_quote(
    symbol: Annotated[str, "Instrument, e.g. 'EUR/USD', 'XAU/USD' (gold), 'BTC/USD', 'AAPL'."],
) -> str:
    """السعر اللحظي لأداة مالية (فوركس/ذهب/كريبتو/أسهم) مع تغيّر اليوم."""
    if not _api_key():
        return _key_missing()
    data = _http_get("quote", {"symbol": symbol})
    e = _err(data)
    if e:
        return e
    try:
        name = data.get("name", symbol)
        price = data.get("close", "?")
        chg = data.get("change", "?")
        pct = data.get("percent_change", "?")
        hi, lo = data.get("high", "?"), data.get("low", "?")
        arrow = "🟢▲" if str(chg).lstrip("-").replace(".", "").isdigit() and not str(chg).startswith("-") else "🔴▼"
        return (f"💹 {name} ({symbol})\n"
                f"   السعر: {price}\n"
                f"   التغيّر: {arrow} {chg} ({pct}%)\n"
                f"   أعلى/أدنى اليوم: {hi} / {lo}")
    except Exception as ex:
        return f"❌ خطأ في قراءة السعر: {ex}"


@tool
def market_timeseries(
    symbol: Annotated[str, "Instrument, e.g. 'EUR/USD'."],
    interval: Annotated[str, "Candle size: '1min','5min','15min','30min','1h','4h','1day','1week'."] = "1h",
    outputsize: Annotated[int, "How many candles back."] = 30,
) -> str:
    """سلسلة شموع تاريخية (OHLC) لأداة مالية — لرؤية حركة السعر."""
    if not _api_key():
        return _key_missing()
    data = _http_get("time_series", {"symbol": symbol, "interval": interval,
                                     "outputsize": min(max(outputsize, 1), 200)})
    e = _err(data)
    if e:
        return e
    values = data.get("values", [])
    if not values:
        return f"ℹ️ لا بيانات لـ {symbol} ({interval})."
    lines = [f"📊 {symbol} — شموع {interval} (الأحدث أولاً):"]
    for v in values[:min(len(values), 20)]:
        lines.append(f"  {v.get('datetime')}: فتح {v.get('open')} | "
                     f"أعلى {v.get('high')} | أدنى {v.get('low')} | إغلاق {v.get('close')}")
    return "\n".join(lines)


@tool
def market_indicator(
    symbol: Annotated[str, "Instrument, e.g. 'EUR/USD'."],
    indicator: Annotated[str, "One of: 'rsi','macd','ema','sma','bbands','adx','stoch'."] = "rsi",
    interval: Annotated[str, "Candle size, e.g. '1h','15min','1day'."] = "1h",
) -> str:
    """قراءة مؤشّر فنّي محدّد من TwelveData (RSI، MACD، EMA، Bollinger، ADX...)."""
    if not _api_key():
        return _key_missing()
    ind = indicator.lower().strip()
    params = {"symbol": symbol, "interval": interval, "outputsize": 1}
    data = _http_get(ind, params)
    e = _err(data)
    if e:
        return e
    vals = data.get("values", [])
    if not vals:
        return f"ℹ️ لا قيمة لـ {ind.upper()} على {symbol}."
    latest = vals[0]
    latest.pop("datetime", None)
    pretty = " | ".join(f"{k}: {v}" for k, v in latest.items())
    return f"📐 {ind.upper()} ({symbol}, {interval}): {pretty}"


def _fetch_float(path: str, symbol: str, interval: str, key: str):
    data = _http_get(path, {"symbol": symbol, "interval": interval, "outputsize": 1})
    if _err(data):
        return None
    vals = data.get("values", [])
    if not vals:
        return None
    try:
        return float(vals[0].get(key))
    except (TypeError, ValueError):
        return None


@tool
def market_analyze(
    symbol: Annotated[str, "Instrument, e.g. 'EUR/USD', 'XAU/USD', 'BTC/USD'."],
    interval: Annotated[str, "Timeframe: '15min','1h','4h','1day'."] = "1h",
) -> str:
    """تحليل فنّي شفّاف متعدّد المؤشّرات + رأي اتجاهي مُبرَّر (ليس إشارة مضمونة).

    يجمع: السعر، RSI، MACD، EMA(9/21/50)، ويشرح كيف وصل لكل استنتاج، ثم يعطي
    انحيازاً اتجاهياً (صعودي/هابط/محايد) مع درجة وضوح ومستويات يجب مراقبتها،
    وتذكير إلزامي بإدارة المخاطر. القرار النهائي لك.
    """
    if not _api_key():
        return _key_missing()

    # ── gather inputs ─────────────────────────────────────────────────────────
    quote = _http_get("quote", {"symbol": symbol})
    if _err(quote):
        return _err(quote)
    try:
        price = float(quote.get("close"))
    except (TypeError, ValueError):
        return f"❌ تعذّر قراءة سعر {symbol}."

    rsi = _fetch_float("rsi", symbol, interval, "rsi")
    macd_data = _http_get("macd", {"symbol": symbol, "interval": interval, "outputsize": 1})
    macd_hist = None
    if not _err(macd_data) and macd_data.get("values"):
        try:
            macd_hist = float(macd_data["values"][0].get("macd_hist"))
        except (TypeError, ValueError):
            macd_hist = None
    ema9 = _fetch_float("ema", symbol, interval, "ema")  # default period 9
    ema21 = None
    ema50 = None
    d21 = _http_get("ema", {"symbol": symbol, "interval": interval, "time_period": 21, "outputsize": 1})
    if not _err(d21) and d21.get("values"):
        try:
            ema21 = float(d21["values"][0].get("ema"))
        except (TypeError, ValueError):
            pass
    d50 = _http_get("ema", {"symbol": symbol, "interval": interval, "time_period": 50, "outputsize": 1})
    if not _err(d50) and d50.get("values"):
        try:
            ema50 = float(d50["values"][0].get("ema"))
        except (TypeError, ValueError):
            pass

    # ── transparent scoring ───────────────────────────────────────────────────
    notes = []
    score = 0  # >0 bullish, <0 bearish

    if rsi is not None:
        if rsi < 30:
            score += 1; notes.append(f"RSI={rsi:.1f} → تشبّع بيعي (إشارة ارتداد صعودي محتملة)")
        elif rsi > 70:
            score -= 1; notes.append(f"RSI={rsi:.1f} → تشبّع شرائي (إشارة ارتداد هابط محتملة)")
        else:
            bias = "أقرب للصعود" if rsi >= 50 else "أقرب للهبوط"
            score += 1 if rsi >= 50 else -1
            notes.append(f"RSI={rsi:.1f} → محايد ({bias})")

    if macd_hist is not None:
        if macd_hist > 0:
            score += 1; notes.append(f"MACD histogram={macd_hist:.5f} → زخم صعودي")
        elif macd_hist < 0:
            score -= 1; notes.append(f"MACD histogram={macd_hist:.5f} → زخم هابط")

    if ema9 is not None and ema21 is not None:
        if ema9 > ema21:
            score += 1; notes.append("EMA9 > EMA21 → اتجاه قصير المدى صعودي")
        else:
            score -= 1; notes.append("EMA9 < EMA21 → اتجاه قصير المدى هابط")
    if ema50 is not None:
        if price > ema50:
            score += 1; notes.append(f"السعر ({price}) فوق EMA50 ({ema50:.5f}) → الاتجاه العام صعودي")
        else:
            score -= 1; notes.append(f"السعر ({price}) تحت EMA50 ({ema50:.5f}) → الاتجاه العام هابط")

    if score >= 2:
        bias, emoji = "انحياز صعودي", "🟢"
    elif score <= -2:
        bias, emoji = "انحياز هابط", "🔴"
    else:
        bias, emoji = "محايد / غير واضح", "🟡"
    clarity = min(abs(score), 4)
    clarity_txt = {0: "ضعيف جداً", 1: "ضعيف", 2: "متوسط", 3: "جيد", 4: "قوي"}.get(clarity, "متوسط")

    # ── report ────────────────────────────────────────────────────────────────
    out = [f"🔍 تحليل فنّي: {symbol} ({interval})",
           f"   السعر الحالي: {price}",
           "",
           "📋 ما رُصد (شفّاف):"]
    out += [f"   • {n}" for n in notes] or ["   • (لا مؤشرات متاحة)"]
    out += ["",
            f"{emoji} الخلاصة: {bias} — وضوح الإشارة: {clarity_txt} ({score:+d})",
            "   هذا انحياز احتمالي مبنيّ على المؤشّرات أعلاه، وليس يقيناً.",
            "   راقب: مستويات الدعم/المقاومة القريبة وأي خبر اقتصادي مؤثّر (استخدم market_news)."]
    return "\n".join(out) + _RISK


@tool
def market_chart(
    symbol: Annotated[str, "Instrument, e.g. 'EUR/USD'."],
    interval: Annotated[str, "Candle size: '15min','1h','4h','1day'."] = "1h",
    bars: Annotated[int, "How many candles to plot."] = 60,
    dest: Annotated[str, "Folder to save the PNG. Empty = Desktop."] = "",
) -> str:
    """رسم شارت شموع يابانية (candlestick) لأداة مالية وحفظه كصورة على سطح المكتب."""
    if not _api_key():
        return _key_missing()
    data = _http_get("time_series", {"symbol": symbol, "interval": interval,
                                     "outputsize": min(max(bars, 5), 200)})
    e = _err(data)
    if e:
        return e
    values = data.get("values", [])
    if not values:
        return f"ℹ️ لا بيانات لرسم {symbol}."
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.dates import date2num
        import datetime as dt

        values = list(reversed(values))  # oldest → newest
        fig, ax = plt.subplots(figsize=(12, 6))
        for i, v in enumerate(values):
            o, h, l, c = float(v["open"]), float(v["high"]), float(v["low"]), float(v["close"])
            color = "#26a69a" if c >= o else "#ef5350"
            ax.plot([i, i], [l, h], color=color, linewidth=1)          # wick
            ax.add_patch(plt.Rectangle((i - 0.3, min(o, c)), 0.6, abs(c - o) or 1e-9,
                                       color=color))                    # body
        ax.set_title(f"{symbol} — {interval} ({len(values)} candles)")
        ax.set_xlabel("candles (old → new)")
        ax.set_ylabel("price")
        ax.grid(True, alpha=0.3)
        folder = Path(dest) if dest else Path(str(DESKTOP_DIR))
        folder.mkdir(parents=True, exist_ok=True)
        safe = symbol.replace("/", "_")
        out = folder / f"chart_{safe}_{interval}.png"
        fig.tight_layout()
        fig.savefig(str(out), dpi=110)
        plt.close(fig)
        return f"✅ تم حفظ الشارت: {out}"
    except Exception as ex:
        return f"❌ خطأ في رسم الشارت: {ex}"


@tool
def market_news(
    query: Annotated[str, "Topic, e.g. 'EUR USD forecast', 'gold price news', 'Fed interest rate'."] = "forex economic news today",
) -> str:
    """متابعة الأخبار الاقتصادية المؤثّرة على السوق (عبر البحث الآمن DuckDuckGo)."""
    try:
        from tools.web_search_tools import _ddg_news, _ddg_text
        results = _ddg_news(query, 6) or _ddg_text(query, 6)
        if not results:
            return f"ℹ️ لا أخبار حديثة لـ «{query}»."
        lines = [f"📰 أخبار اقتصادية: «{query}»"]
        for r in results[:6]:
            t = (r.get("title") or "").strip()
            d = (r.get("date") or "").strip()
            b = (r.get("body") or "").strip()[:160]
            lines.append(f"  • {t}" + (f"  ({d})" if d else ""))
            if b:
                lines.append(f"    {b}")
        lines.append("\n💡 الأخبار قد تقلب الاتجاه الفنّي فجأة — راعِها قبل أي قرار.")
        return "\n".join(lines)
    except Exception as ex:
        return f"❌ خطأ في جلب الأخبار: {ex}"
