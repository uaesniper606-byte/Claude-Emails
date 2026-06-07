"""
=============================================================
MORNING BRIEFING AGENT — Saif's Portfolio
=============================================================
Runs every weekday at 2:30 PM GST.
Fetches live data from Alpha Vantage MCP, builds bilingual
PDF infographics (Arabic + English), uploads to GitHub,
and sends via Resend relay.

Usage:
    python3 morning_briefing_agent.py

Schedule (cron, UTC = GST-4):
    30 10 * * 1-5  python3 /path/to/morning_briefing_agent.py
=============================================================
"""

import os, json, base64, time, datetime, requests
from playwright.sync_api import sync_playwright

# ── CONFIG ───────────────────────────────────────────────────
AV_KEY        = os.environ.get("AV_KEY", "HONKZR3NHFIQ59P4")
AV_BASE       = "https://www.alphavantage.co/query"
GITHUB_PAT    = "os.environ.get("BRIEFING_PAT", "")"
GITHUB_REPO   = "uaesniper606-byte/Claude-Emails"
EMAIL_TO      = "uae.sniper606@gmail.com"
EMAIL_FROM    = "onboarding@resend.dev"

STOCKS  = ["MU", "NOW", "PLTR", "CBRS"]
CRYPTOS = ["XRP", "SOL", "HBAR", "SHIB", "ADA", "ARB", "DOT", "GALA"]

STOCK_META = {
    "MU":   {"name": "Micron Technology",  "name_ar": "مايكرون تكنولوجي",   "color": "#e53e3e", "earn": "Jun 24, 2026"},
    "NOW":  {"name": "ServiceNow",         "name_ar": "سيرفس ناو",           "color": "#10b981", "earn": "Jul 29, 2026"},
    "PLTR": {"name": "Palantir",           "name_ar": "بالانتير",            "color": "#8b5cf6", "earn": "Aug 10, 2026"},
    "CBRS": {"name": "Cerebras Systems",   "name_ar": "سيريبراس سيستمز",    "color": "#f59e0b", "earn": "TBD"},
}
CRYPTO_META = {
    "XRP":  {"name": "Ripple",      "name_ar": "ريبل",       "color": "#00aae4", "cat": "مدفوعات"},
    "SOL":  {"name": "Solana",      "name_ar": "سولانا",     "color": "#9945ff", "cat": "بنية تحتية"},
    "HBAR": {"name": "Hedera",      "name_ar": "هيدرا",      "color": "#1ad2a4", "cat": "بنية تحتية"},
    "SHIB": {"name": "Shiba Inu",   "name_ar": "شيبا إينو",  "color": "#e74c3c", "cat": "ميم"},
    "ADA":  {"name": "Cardano",     "name_ar": "كاردانو",    "color": "#0033ad", "cat": "بنية تحتية"},
    "ARB":  {"name": "Arbitrum",    "name_ar": "أربيتروم",   "color": "#28a0f0", "cat": "الطبقة 2"},
    "DOT":  {"name": "Polkadot",    "name_ar": "بولكادوت",   "color": "#e6007a", "cat": "بنية تحتية"},
    "GALA": {"name": "Gala Games",  "name_ar": "غالا غيمز",  "color": "#fbbf24", "cat": "ألعاب"},
}

FONT_DIR = "/home/claude/fonts"

# ── DATA FETCHER ─────────────────────────────────────────────

def av_get(params: dict, retries=2) -> dict:
    """Call Alpha Vantage REST API directly (fallback when MCP limit hit)."""
    params["apikey"] = AV_KEY
    for attempt in range(retries):
        try:
            r = requests.get(AV_BASE, params=params, timeout=15)
            data = r.json()
            if "Note" in data or "Information" in data:
                print(f"  ⚠️  AV rate limit hit: {list(data.values())[0][:80]}")
                return {}
            return data
        except Exception as e:
            print(f"  ⚠️  AV request error: {e}")
            time.sleep(2)
    return {}

def fetch_quote(symbol: str) -> dict:
    data = av_get({"function": "GLOBAL_QUOTE", "symbol": symbol})
    q = data.get("Global Quote", {})
    if not q:
        return {}
    return {
        "symbol":   q.get("01. symbol", symbol),
        "price":    float(q.get("05. price", 0)),
        "open":     float(q.get("02. open", 0)),
        "high":     float(q.get("03. high", 0)),
        "low":      float(q.get("04. low", 0)),
        "volume":   int(q.get("06. volume", 0)),
        "prev":     float(q.get("08. previous close", 0)),
        "change":   float(q.get("09. change", 0)),
        "chg_pct":  q.get("10. change percent", "0%").replace("%", ""),
        "date":     q.get("07. latest trading day", ""),
    }

def fetch_news(ticker: str, limit: int = 5) -> list:
    """Fetch news sentiment for a ticker."""
    data = av_get({"function": "NEWS_SENTIMENT", "tickers": ticker, "limit": str(limit)})
    feed = data.get("feed", [])
    results = []
    for item in feed[:limit]:
        # find ticker-specific sentiment
        sent_score = 0.0
        sent_label = "Neutral"
        for ts in item.get("ticker_sentiment", []):
            if ts.get("ticker", "").upper() == ticker.upper():
                sent_score = float(ts.get("ticker_sentiment_score", 0))
                sent_label = ts.get("ticker_sentiment_label", "Neutral")
                break
        results.append({
            "title":   item.get("title", ""),
            "summary": item.get("summary", "")[:220],
            "source":  item.get("source", ""),
            "time":    item.get("time_published", ""),
            "sentiment_score": sent_score,
            "sentiment_label": sent_label,
        })
    return results

def fetch_put_call(symbol: str) -> dict:
    """Fetch realtime put/call ratio."""
    data = av_get({"function": "REALTIME_PUT_CALL_RATIO", "symbol": symbol})
    payload = data.get("payload", {})
    if not payload:
        return {}
    overall = payload.get("overall", {})
    return {
        "ratio":  overall.get("put_call_ratio", "N/A"),
        "signal": overall.get("signal", "N/A"),
        "puts":   overall.get("total_put_volume", "N/A"),
        "calls":  overall.get("total_call_volume", "N/A"),
    }

def fetch_crypto_price(symbol: str) -> dict:
    """Fetch crypto price via CURRENCY_EXCHANGE_RATE."""
    data = av_get({"function": "CURRENCY_EXCHANGE_RATE",
                   "from_currency": symbol, "to_currency": "USD"})
    r = data.get("Realtime Currency Exchange Rate", {})
    if not r:
        return {}
    return {
        "symbol": symbol,
        "price":  float(r.get("5. Exchange Rate", 0)),
        "bid":    float(r.get("8. Bid Price", 0)),
        "ask":    float(r.get("9. Ask Price", 0)),
        "date":   r.get("6. Last Refreshed", ""),
    }

def fetch_earnings_calendar(symbol: str) -> str:
    """Get next earnings date."""
    data = av_get({"function": "EARNINGS", "symbol": symbol})
    qtly = data.get("quarterlyEarnings", [])
    if qtly:
        # Most recent entry with a reportedDate in the future
        today = datetime.date.today().isoformat()
        for q in qtly:
            rd = q.get("reportedDate", "")
            if rd > today:
                return rd
    return STOCK_META.get(symbol, {}).get("earn", "TBD")

def collect_all_data() -> dict:
    """Fetch all portfolio data from Alpha Vantage."""
    print("\n📡 Fetching live market data...")
    result = {"stocks": {}, "crypto": {}, "date": datetime.date.today().isoformat()}

    # Stocks
    for sym in STOCKS:
        print(f"  Fetching {sym}...")
        q = fetch_quote(sym)
        news = fetch_news(sym, 5)
        pc = {}
        if sym in ("MU", "NOW", "PLTR"):   # options exist for these
            pc = fetch_put_call(sym)
        result["stocks"][sym] = {
            "quote": q,
            "news":  news,
            "put_call": pc,
            "earnings": STOCK_META[sym]["earn"],
        }
        time.sleep(1)   # respect rate limits

    # Crypto
    for sym in CRYPTOS:
        print(f"  Fetching {sym}...")
        price = fetch_crypto_price(sym)
        news  = fetch_news(f"CRYPTO:{sym}", 3)
        result["crypto"][sym] = {"price": price, "news": news}
        time.sleep(1)

    print("✅ Data collection complete.\n")
    return result

# ── PDF BUILDER ──────────────────────────────────────────────

def b64font(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def fmt_price(p, sym=""):
    """Format price nicely."""
    if p == 0:
        return "N/A"
    if sym in CRYPTOS and p < 0.01:
        return f"${p:.8f}"
    if sym in CRYPTOS and p < 1:
        return f"${p:.4f}"
    return f"${p:,.2f}"

def fmt_vol(v):
    if v == 0: return "N/A"
    if v >= 1_000_000: return f"{v/1_000_000:.2f}M"
    if v >= 1_000: return f"{v/1_000:.0f}K"
    return str(v)

def sentiment_color(label):
    label = label.lower()
    if "bearish" in label and "somewhat" not in label: return "#dc2626"
    if "somewhat-bearish" in label or "somewhat_bearish" in label: return "#f97316"
    if "bullish" in label and "somewhat" not in label: return "#16a34a"
    if "somewhat" in label and "bullish" in label: return "#22c55e"
    return "#6b7280"

def sentiment_ar(label):
    label = label.lower()
    if "bearish" in label and "somewhat" not in label: return "سلبي"
    if "somewhat" in label and "bearish" in label: return "سلبي نسبياً"
    if "bullish" in label and "somewhat" not in label: return "إيجابي"
    if "somewhat" in label and "bullish" in label: return "إيجابي نسبياً"
    return "محايد"

def pc_signal_ar(signal):
    s = str(signal).lower()
    if "bullish" in s: return "إيجابي"
    if "bearish" in s: return "سلبي"
    return "محايد"

def build_css(am, amb, dv, dvb):
    return f"""
@font-face{{font-family:'AM';src:url('data:font/ttf;base64,{am}');font-weight:400}}
@font-face{{font-family:'AM';src:url('data:font/ttf;base64,{amb}');font-weight:700}}
@font-face{{font-family:'DV';src:url('data:font/ttf;base64,{dv}');font-weight:400}}
@font-face{{font-family:'DV';src:url('data:font/ttf;base64,{dvb}');font-weight:700}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#eef2f7;color:#1a2332;width:1240px}}
.ar{{font-family:'AM',serif;font-size:13.5px;direction:rtl;unicode-bidi:embed}}
.en{{font-family:'DV',sans-serif;font-size:12.5px;direction:ltr}}
.num{{font-family:'DV',sans-serif}}
.page{{width:1240px;padding:34px 42px;background:#eef2f7;page-break-after:always;min-height:1754px}}

/* Header */
.hdr{{background:linear-gradient(135deg,#0f2d5a 0%,#1d4ed8 65%,#2563eb 100%);
      border-radius:16px;padding:28px 36px;margin-bottom:20px;
      display:flex;justify-content:space-between;align-items:center;
      box-shadow:0 6px 28px rgba(29,78,216,0.28)}}
.hdr-badge{{background:rgba(255,255,255,0.18);border:1px solid rgba(255,255,255,0.35);
            border-radius:20px;padding:3px 14px;font-size:10px;
            color:rgba(255,255,255,0.92);margin-bottom:7px;display:inline-block}}
.hdr-title{{font-size:24px;font-weight:700;color:#fff;margin-bottom:4px;line-height:1.25}}
.hdr-sub{{font-size:11.5px;color:rgba(255,255,255,0.72)}}
.hdr-date{{font-size:19px;font-weight:700;color:#fff}}
.hdr-time{{font-size:11px;color:rgba(255,255,255,0.68);margin-top:4px}}
.hdr-pill{{background:rgba(255,255,255,0.2);border-radius:10px;padding:4px 12px;
           font-size:10px;color:#fff;display:inline-block;margin-top:7px}}

/* Section */
.sec{{font-size:13.5px;font-weight:700;color:#0f2d5a;padding:8px 0 7px;
      border-bottom:2px solid #c7d9f0;margin:18px 0 12px;
      display:flex;align-items:center;gap:8px}}
.sec-ar{{flex-direction:row-reverse}}
.dot{{width:7px;height:7px;border-radius:50%;background:#1d4ed8;flex-shrink:0}}

/* Alerts */
.alert{{border-radius:11px;padding:12px 16px;margin-bottom:14px;
        display:flex;align-items:flex-start;gap:11px}}
.alert-ar{{flex-direction:row-reverse}}
.a-red{{background:#fff5f5;border:1.5px solid #feb2b2;border-right:4px solid #e53e3e}}
.a-amber{{background:#fffdf0;border:1.5px solid #fbd38d;border-right:4px solid #dd6b20}}
.a-blue{{background:#ebf8ff;border:1.5px solid #bee3f8;border-right:4px solid #3182ce}}
.a-icon{{font-size:18px;margin-top:2px;flex-shrink:0}}
.a-title{{font-weight:700;font-size:12.5px;margin-bottom:3px}}
.a-red .a-title{{color:#c53030}}
.a-amber .a-title{{color:#7b341e}}
.a-blue .a-title{{color:#2a4365}}
.a-body{{font-size:11.5px;color:#4a5568;line-height:1.65}}

/* Grids */
.g2{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}}
.g3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:12px}}
.g4{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:9px;margin-bottom:12px}}

/* Card */
.card{{background:#fff;border-radius:12px;padding:14px 16px;border:1px solid #dde5f0;
       box-shadow:0 2px 8px rgba(0,0,0,0.05)}}
.c-lbl{{font-size:10px;color:#718096;text-transform:uppercase;letter-spacing:0.7px;margin-bottom:7px}}
.c-val{{font-size:24px;font-weight:700;color:#0f2d5a;line-height:1;font-family:'DV',sans-serif}}
.c-sub{{font-size:10px;color:#718096;margin-top:3px;font-family:'DV',sans-serif}}
.card p{{font-size:11.5px;color:#2d3748;line-height:1.65;margin-top:7px}}
.pill{{font-size:9px;font-weight:700;padding:2px 8px;border-radius:9px;display:inline-block;margin-top:5px}}
.p-red{{background:#fed7d7;color:#c53030}}
.p-green{{background:#c6f6d5;color:#276749}}
.p-blue{{background:#bee3f8;color:#2a4365}}
.p-amber{{background:#fef3c7;color:#7b341e}}
.p-gray{{background:#e5e7eb;color:#374151}}
.pos{{color:#276749;font-weight:700}}
.neg{{color:#c53030;font-weight:700}}
.hl{{color:#2b6cb0;font-weight:700}}
.warn{{color:#c05621;font-weight:700}}

/* Strip */
.strip{{display:flex;gap:2px;margin-bottom:18px;border-radius:12px;overflow:hidden;
        box-shadow:0 2px 8px rgba(0,0,0,0.07)}}
.sc{{flex:1;padding:12px 8px;text-align:center}}
.sv{{font-size:18px;font-weight:700;font-family:'DV',sans-serif}}
.sl{{font-size:9px;color:#718096;margin-top:2px;font-family:'DV',sans-serif}}

/* Stock card */
.scard{{background:#fff;border-radius:12px;border:1px solid #dde5f0;
        box-shadow:0 2px 10px rgba(0,0,0,0.06);overflow:hidden;margin-bottom:12px}}
.scard-top{{padding:13px 16px;border-bottom:1px solid #f0f4f8}}
.scard-sym{{font-size:20px;font-weight:700}}
.scard-name{{font-size:10.5px;color:#718096;margin-top:1px}}
.scard-row{{display:flex;justify-content:space-between;align-items:center}}
.scard-price{{font-size:19px;font-weight:700;color:#0f2d5a;font-family:'DV',sans-serif}}
.scard-meta{{padding:8px 16px;background:#f8faff;display:flex;gap:8px;flex-wrap:wrap}}
.stag{{background:#e5e7eb;border-radius:4px;padding:2px 7px;font-size:10px;color:#374151}}
.stag-earn{{background:#fef3c7;border-radius:4px;padding:2px 7px;font-size:10px;color:#92400e}}
.stag-sent{{border-radius:4px;padding:2px 7px;font-size:10px;font-weight:700}}
.scard-news{{padding:10px 16px}}
.scard-news ul{{padding-left:14px;list-style:disc}}
.scard-news ul.ar-list{{padding-right:14px;padding-left:0;list-style:disc}}
.scard-news li{{font-size:11px;color:#4a5568;margin-bottom:4px;line-height:1.55}}
.scard-pc{{padding:8px 16px;border-top:1px solid #f0f4f8;display:flex;gap:10px;
           align-items:center;background:#fafbff}}
.pc-lbl{{font-size:10px;color:#718096}}
.pc-val{{font-size:12px;font-weight:700;font-family:'DV',sans-serif}}

/* Crypto card */
.ccard{{background:#fff;border-radius:10px;padding:12px 14px;border:1px solid #dde5f0;
        box-shadow:0 2px 6px rgba(0,0,0,0.05)}}
.ccard-sym{{font-size:14px;font-weight:700}}
.ccard-price{{font-size:13px;font-weight:700;color:#0f2d5a;font-family:'DV',sans-serif;margin-top:3px}}
.ccard-cat{{font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;
            display:inline-block;margin:3px 0 5px}}
.ccard-note{{font-size:10.5px;color:#718096;line-height:1.45}}

/* Bar chart */
.bc{{background:#fff;border-radius:12px;padding:15px 17px;border:1px solid #dde5f0;
     box-shadow:0 2px 8px rgba(0,0,0,0.05)}}
.bc-t{{font-size:12px;font-weight:700;color:#0f2d5a;margin-bottom:11px}}
.brow{{display:flex;align-items:center;gap:9px;margin-bottom:8px}}
.brow-ar{{flex-direction:row-reverse}}
.blbl{{font-size:11px;color:#2d3748;min-width:58px}}
.btrack{{flex:1;background:#f0f4f8;border-radius:4px;height:18px;overflow:hidden}}
.bfill{{height:100%;border-radius:4px;display:flex;align-items:center;padding:0 7px;justify-content:flex-end}}
.bval{{font-size:9.5px;font-weight:700;color:#fff;font-family:'DV',sans-serif}}

/* Donut */
.dw{{display:flex;align-items:center;justify-content:center;gap:18px}}
.dleg{{display:flex;flex-direction:column;gap:9px}}
.di{{display:flex;align-items:center;gap:7px}}
.di-ar{{flex-direction:row-reverse}}
.dd{{width:10px;height:10px;border-radius:50%;flex-shrink:0}}
.dt{{font-size:11.5px;color:#2d3748}}
.dp{{font-size:10px;color:#718096;font-family:'DV',sans-serif}}

/* Calendar */
.cal-g{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:12px}}
.cal{{background:#fff;border-radius:9px;padding:11px;border:1px solid #dde5f0;
      text-align:center;box-shadow:0 1px 5px rgba(0,0,0,0.05)}}
.cal.hot{{border-color:#fca5a5;background:linear-gradient(135deg,#fff5f5,#ffe8e8)}}
.cal.warm{{border-color:#fbd38d;background:linear-gradient(135deg,#fffdf0,#fef3c7)}}
.cal.cool{{border-color:#bee3f8;background:linear-gradient(135deg,#ebf8ff,#dde9f5)}}
.cal-d{{font-size:9.5px;color:#718096;margin-bottom:3px;font-family:'DV',sans-serif}}
.cal-e{{font-size:10.5px;color:#0f2d5a;font-weight:700;line-height:1.3}}

/* Table */
.tbl{{width:100%;border-collapse:separate;border-spacing:0;margin-bottom:12px;
      border-radius:9px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06)}}
.tbl th{{background:#0f2d5a;color:#fff;font-size:10px;font-weight:700;padding:9px 12px}}
.tbl td{{padding:8px 12px;font-size:11.5px;color:#2d3748;background:#fff;border-bottom:1px solid #f0f4f8}}
.tbl tr:last-child td{{border-bottom:none}}
.tbl tr:nth-child(even) td{{background:#f7faff}}

/* Bottom line */
.bline{{background:linear-gradient(135deg,#0f2d5a,#1d4ed8);border-radius:13px;
        padding:18px 22px;margin-bottom:16px;box-shadow:0 6px 20px rgba(29,78,216,0.22)}}
.bline h3{{color:#fff;font-size:13px;margin-bottom:8px;font-weight:700}}
.bline p{{font-size:12px;color:rgba(255,255,255,0.90);line-height:1.75}}

/* Footer */
.footer{{text-align:center;color:#a0aec0;font-size:10px;padding:10px 0;
         border-top:1px solid #dde5f0;font-family:'DV',sans-serif}}
"""

# ── HTML BUILDERS ─────────────────────────────────────────────

def build_part1_ar(data, today_str):
    stocks = data["stocks"]
    date_ar = today_str

    # Sentiment bar chart data
    sent_rows = ""
    for sym in STOCKS:
        q = stocks[sym].get("quote", {})
        news = stocks[sym].get("news", [])
        avg_sent = sum(n["sentiment_score"] for n in news) / len(news) if news else 0
        chg = float(q.get("chg_pct", 0)) if q else 0
        color = STOCK_META[sym]["color"]
        w = min(abs(chg) * 4.5, 90)
        sign = "▲" if chg >= 0 else "▼"
        c = "#276749" if chg >= 0 else "#c53030"
        sent_rows += f"""<div class="brow brow-ar">
          <div class="blbl" style="text-align:right;font-weight:700;color:{color}">{sym}</div>
          <div class="btrack" style="background:{'#f0fff4' if chg>=0 else '#fff5f5'}">
            <div class="bfill" style="width:{w}%;background:{c}">
              <span class="bval">{sign}{abs(chg):.2f}%</span>
            </div>
          </div>
        </div>"""

    # Stock summary cards
    stock_cards = ""
    for sym in STOCKS:
        m = STOCK_META[sym]
        q = stocks[sym].get("quote", {})
        news = stocks[sym].get("news", [])
        pc = stocks[sym].get("put_call", {})
        earn = stocks[sym].get("earnings", m["earn"])

        price  = fmt_price(q.get("price", 0))
        chg    = float(q.get("chg_pct", 0)) if q else 0
        vol    = fmt_vol(q.get("volume", 0))
        hi     = fmt_price(q.get("high", 0))
        lo     = fmt_price(q.get("low", 0))
        arrow  = "▲" if chg >= 0 else "▼"
        chg_c  = "pos" if chg >= 0 else "neg"
        sent_avg = sum(n["sentiment_score"] for n in news)/len(news) if news else 0
        sent_lbl_ar = sentiment_ar("bullish" if sent_avg > 0.15 else ("bearish" if sent_avg < -0.15 else "neutral"))
        sent_col = sentiment_color("bullish" if sent_avg > 0.15 else ("bearish" if sent_avg < -0.15 else "neutral"))

        # news items in Arabic (use summary)
        news_html = ""
        for n in news[:4]:
            news_html += f"<li>{n['title'][:110]}</li>"

        pc_html = ""
        if pc:
            ratio = pc.get("ratio", "N/A")
            sig_ar = pc_signal_ar(pc.get("signal", ""))
            pc_html = f"""<div class="scard-pc">
              <span class="pc-lbl">نسبة Put/Call:</span>
              <span class="pc-val">{ratio}</span>
              <span class="stag-sent" style="background:{sent_col}20;color:{sent_col};margin-right:8px">{sig_ar}</span>
            </div>"""

        stock_cards += f"""
        <div class="scard" style="border-top:3px solid {m['color']};direction:rtl">
          <div class="scard-top">
            <div class="scard-row" style="flex-direction:row-reverse">
              <div style="text-align:right">
                <div class="scard-sym" style="color:{m['color']}">{sym}</div>
                <div class="scard-name">{m['name_ar']}</div>
              </div>
              <div style="text-align:left">
                <div class="scard-price">{price}</div>
                <div class="{chg_c}" style="font-family:'DV',sans-serif;font-size:12px">{arrow} {abs(chg):.2f}% &nbsp;|&nbsp; حجم: {vol}</div>
              </div>
            </div>
          </div>
          <div class="scard-meta" style="flex-direction:row-reverse">
            <span class="stag">أعلى: {hi}</span>
            <span class="stag">أدنى: {lo}</span>
            <span class="stag-earn">⚠ الأرباح: {earn}</span>
            <span class="stag-sent" style="background:{sent_col}20;color:{sent_col}">المعنويات: {sent_lbl_ar}</span>
          </div>
          <div class="scard-news">
            <ul class="ar-list">{news_html}</ul>
          </div>
          {pc_html}
        </div>"""

    return f"""
<div class="page ar">
  <div class="hdr" style="flex-direction:row-reverse">
    <div style="text-align:right">
      <div class="hdr-badge">التقرير الصباحي · الجزء 1 من 2 · الأسهم</div>
      <div class="hdr-title">محفظتك — التقرير الصباحي</div>
      <div class="hdr-sub">MU · NOW · PLTR · CBRS &nbsp;|&nbsp; XRP · SOL · HBAR · SHIB · ADA · ARB · DOT · GALA</div>
    </div>
    <div style="text-align:left">
      <div class="hdr-date">{date_ar}</div>
      <div class="hdr-time">2:30 ظهرًا · بتوقيت الخليج</div>
      <div class="hdr-pill">بيانات مباشرة · Alpha Vantage</div>
    </div>
  </div>

  <div class="sec sec-ar"><div class="dot"></div>📈 الأسهم — أداء اليوم والأخبار</div>

  <div class="g2">{stock_cards}</div>

  <div class="sec sec-ar"><div class="dot"></div>📊 أداء الأسهم — مخطط التغيير اليومي</div>
  <div class="bc">
    <div class="bc-t" style="text-align:right">التغيير اليومي لأسهم المحفظة</div>
    {sent_rows}
  </div>

  <div class="footer">الجزء 1 من 2 · الأسهم · {today_str} · للأغراض المعلوماتية فقط · ليس نصيحة مالية</div>
</div>"""


def build_part2_ar(data, today_str):
    cryptos = data["crypto"]

    # Crypto cards grid
    crypto_cards = ""
    for sym in CRYPTOS:
        m = CRYPTO_META[sym]
        cdata = cryptos.get(sym, {})
        price_data = cdata.get("price", {})
        news = cdata.get("news", [])

        price = fmt_price(price_data.get("price", 0), sym)
        sent_avg = sum(n["sentiment_score"] for n in news)/len(news) if news else 0
        sent_lbl_ar = sentiment_ar("bullish" if sent_avg > 0.15 else ("bearish" if sent_avg < -0.15 else "neutral"))
        sent_col = sentiment_color("bullish" if sent_avg > 0.15 else ("bearish" if sent_avg < -0.15 else "neutral"))
        cat_style = {
            "بنية تحتية": "background:#dbeafe;color:#1e40af",
            "مدفوعات":    "background:#dcfce7;color:#166534",
            "الطبقة 2":   "background:#ede9fe;color:#6d28d9",
            "ألعاب":       "background:#fef3c7;color:#92400e",
            "ميم":         "background:#fee2e2;color:#991b1b",
        }.get(m["cat"], "background:#f3f4f6;color:#374151")

        news_html = ""
        for n in news[:3]:
            news_html += f"<div style='font-size:10.5px;color:#4a5568;margin-bottom:5px;line-height:1.5;border-right:3px solid {m['color']};padding-right:8px'>{n['title'][:100]}</div>"

        crypto_cards += f"""
        <div class="ccard" style="border-top:3px solid {m['color']};text-align:right">
          <div class="ccard-sym" style="color:{m['color']}">{sym}</div>
          <div style="font-size:10px;color:#718096">{m['name_ar']}</div>
          <div class="ccard-price">{price}</div>
          <div class="ccard-cat" style="{cat_style}">{m['cat']}</div>
          <div style="margin-bottom:6px">
            <span class="stag-sent" style="font-size:9px;padding:1px 6px;border-radius:4px;background:{sent_col}20;color:{sent_col}">المعنويات: {sent_lbl_ar}</span>
          </div>
          {news_html}
        </div>"""

    # Action table
    action_rows = ""
    actions = {
        "MU": ("احتفظ · لا تضيف قبل الأرباح", "warn"),
        "NOW": ("تراكم نحو 100-105", "pos"),
        "PLTR": ("احتفظ · تراكم دون 120", "pos"),
        "CBRS": ("احتفظ · راقب الإغلاق يوميًا", "neg"),
        "XRP": ("احتفظ · إضافة صغيرة دون 0.45", "pos"),
        "SOL": ("احتفظ · أساسيات قوية", "hl"),
        "HBAR": ("احتفظ · ثقة عالية", "pos"),
        "ADA": ("احتفظ · انتظر mainnet Q4", "hl"),
        "ARB": ("احتفظ · آخر أولوية", "hl"),
        "DOT": ("احتفظ بحياد", "hl"),
        "SHIB": ("احتفظ فقط · لا إضافات", "neg"),
        "GALA": ("احتفظ فقط · راقب الألعاب", "neg"),
    }
    for sym, (action_ar, css) in actions.items():
        m_data = data["stocks"].get(sym, {}) if sym in STOCKS else {}
        c_data = data["crypto"].get(sym, {}) if sym in CRYPTOS else {}
        if sym in STOCKS:
            q = m_data.get("quote", {})
            price = fmt_price(q.get("price", 0)) if q else "N/A"
        else:
            pd = c_data.get("price", {})
            price = fmt_price(pd.get("price", 0), sym) if pd else "N/A"
        color = STOCK_META.get(sym, CRYPTO_META.get(sym, {})).get("color", "#374151")
        action_rows += f"""<tr>
          <td><strong style="color:{color}">{sym}</strong></td>
          <td style="font-family:'DV',sans-serif">{price}</td>
          <td class="{css}">{action_ar}</td>
        </tr>"""

    return f"""
<div class="page ar">
  <div style="background:linear-gradient(135deg,#0f2d5a,#1d4ed8);border-radius:12px;padding:16px 26px;margin-bottom:18px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 4px 16px rgba(29,78,216,0.22)">
    <div style="text-align:right">
      <div style="font-size:10px;color:rgba(255,255,255,0.65);margin-bottom:3px">الجزء 2 من 2 · الكريبتو وخطة العمل</div>
      <div style="font-size:18px;font-weight:700;color:#fff">الكريبتو · خطة العمل · السيناريوهات</div>
    </div>
    <div style="text-align:left;font-size:11px;color:rgba(255,255,255,0.75)">{today_str} · 2:30 ظهرًا</div>
  </div>

  <div class="sec sec-ar"><div class="dot"></div>₿ الكريبتو — الأسعار والأخبار</div>
  <div class="g4">{crypto_cards}</div>

  <div class="sec sec-ar"><div class="dot"></div>⚡ خطة العمل — توصياتي المباشرة</div>
  <table class="tbl" style="direction:rtl">
    <tr>
      <th style="text-align:right">الأصل</th>
      <th style="text-align:right">السعر</th>
      <th style="text-align:right">التوصية</th>
    </tr>
    {action_rows}
  </table>

  <div class="bline" style="text-align:right">
    <h3>⚡ خلاصة اليوم</h3>
    <p>محفظتك تعمل في بيئة سوق متقلبة. الأسهم تتأثر بثلاثة عوامل رئيسية: إعادة تسعير AI بعد برودكوم، مخاوف رفع الفائدة من تقرير الوظائف القوي، وضغط النفط من أزمة إيران. الكريبتو يتداول كأصل مخاطرة بدلاً من ملاذ آمن. راقب CPI في 10 يونيو وأرباح مايكرون في 24 يونيو — هما أهم حدثَين لمحفظتك.</p>
  </div>

  <div class="footer">الجزء 2 من 2 · الكريبتو وخطة العمل · {today_str} · للأغراض المعلوماتية فقط · ليس نصيحة مالية</div>
</div>"""


def build_part1_en(data, today_str):
    stocks = data["stocks"]

    stock_cards = ""
    for sym in STOCKS:
        m = STOCK_META[sym]
        q = stocks[sym].get("quote", {})
        news = stocks[sym].get("news", [])
        pc = stocks[sym].get("put_call", {})
        earn = stocks[sym].get("earnings", m["earn"])

        price = fmt_price(q.get("price", 0))
        chg   = float(q.get("chg_pct", 0)) if q else 0
        vol   = fmt_vol(q.get("volume", 0))
        hi    = fmt_price(q.get("high", 0))
        lo    = fmt_price(q.get("low", 0))
        arrow = "▲" if chg >= 0 else "▼"
        chg_c = "pos" if chg >= 0 else "neg"
        sent_avg = sum(n["sentiment_score"] for n in news)/len(news) if news else 0
        sent_lbl = "Bullish" if sent_avg > 0.15 else ("Bearish" if sent_avg < -0.15 else "Neutral")
        sent_col = sentiment_color(sent_lbl)

        news_html = "".join(f"<li>{n['title'][:110]}</li>" for n in news[:4])

        pc_html = ""
        if pc:
            ratio = pc.get("ratio", "N/A")
            sig   = pc.get("signal", "N/A")
            pc_html = f"""<div class="scard-pc">
              <span class="pc-lbl">Put/Call Ratio:</span>
              <span class="pc-val">{ratio}</span>
              <span class="stag-sent" style="background:{sent_col}20;color:{sent_col};margin-left:8px">{sig}</span>
            </div>"""

        stock_cards += f"""
        <div class="scard" style="border-top:3px solid {m['color']};direction:ltr">
          <div class="scard-top">
            <div class="scard-row">
              <div>
                <div class="scard-sym" style="color:{m['color']}">{sym}</div>
                <div class="scard-name">{m['name']}</div>
              </div>
              <div style="text-align:right">
                <div class="scard-price">{price}</div>
                <div class="{chg_c}" style="font-family:'DV',sans-serif;font-size:12px">{arrow} {abs(chg):.2f}% &nbsp;|&nbsp; Vol: {vol}</div>
              </div>
            </div>
          </div>
          <div class="scard-meta">
            <span class="stag">High: {hi}</span>
            <span class="stag">Low: {lo}</span>
            <span class="stag-earn">⚠ Earnings: {earn}</span>
            <span class="stag-sent" style="background:{sent_col}20;color:{sent_col}">Sentiment: {sent_lbl}</span>
          </div>
          <div class="scard-news"><ul>{news_html}</ul></div>
          {pc_html}
        </div>"""

    sent_rows_en = ""
    for sym in STOCKS:
        q = stocks[sym].get("quote", {})
        chg = float(q.get("chg_pct", 0)) if q else 0
        color = STOCK_META[sym]["color"]
        w = min(abs(chg)*4.5, 90)
        sign = "+" if chg >= 0 else ""
        c = "#276749" if chg >= 0 else "#c53030"
        sent_rows_en += f"""<div class="brow">
          <div class="blbl" style="font-weight:700;color:{color}">{sym}</div>
          <div class="btrack" style="background:{'#f0fff4' if chg>=0 else '#fff5f5'}">
            <div class="bfill" style="width:{w}%;background:{c}">
              <span class="bval">{sign}{chg:.2f}%</span>
            </div>
          </div>
        </div>"""

    return f"""
<div class="page en">
  <div class="hdr">
    <div>
      <div class="hdr-badge">Morning Briefing · Part 1 of 2 · Stocks</div>
      <div class="hdr-title">Your Portfolio — Morning Briefing</div>
      <div class="hdr-sub">MU · NOW · PLTR · CBRS &nbsp;|&nbsp; XRP · SOL · HBAR · SHIB · ADA · ARB · DOT · GALA</div>
    </div>
    <div style="text-align:right">
      <div class="hdr-date">{today_str}</div>
      <div class="hdr-time">2:30 PM GST</div>
      <div class="hdr-pill">Live Data · Alpha Vantage</div>
    </div>
  </div>

  <div class="sec"><div class="dot"></div>📈 STOCKS — Today's Performance & News</div>
  <div class="g2">{stock_cards}</div>

  <div class="sec"><div class="dot"></div>📊 Daily Change Chart</div>
  <div class="bc">
    <div class="bc-t">Portfolio Stocks — Daily Price Change</div>
    {sent_rows_en}
  </div>

  <div class="footer">Part 1 of 2 · Stocks · {today_str} · For informational purposes only · Not financial advice</div>
</div>"""


def build_part2_en(data, today_str):
    cryptos = data["crypto"]

    crypto_cards = ""
    for sym in CRYPTOS:
        m = CRYPTO_META[sym]
        cdata = cryptos.get(sym, {})
        price_data = cdata.get("price", {})
        news = cdata.get("news", [])

        price = fmt_price(price_data.get("price", 0), sym)
        sent_avg = sum(n["sentiment_score"] for n in news)/len(news) if news else 0
        sent_lbl = "Bullish" if sent_avg > 0.15 else ("Bearish" if sent_avg < -0.15 else "Neutral")
        sent_col = sentiment_color(sent_lbl)
        cat_en = {"بنية تحتية":"INFRA","مدفوعات":"PAYMENTS","الطبقة 2":"LAYER2","ألعاب":"GAMING","ميم":"MEME"}.get(m["cat"],"")
        cat_style = {
            "INFRA":    "background:#dbeafe;color:#1e40af",
            "PAYMENTS": "background:#dcfce7;color:#166534",
            "LAYER2":   "background:#ede9fe;color:#6d28d9",
            "GAMING":   "background:#fef3c7;color:#92400e",
            "MEME":     "background:#fee2e2;color:#991b1b",
        }.get(cat_en, "background:#f3f4f6;color:#374151")

        news_html = "".join(
            f"<div style='font-size:10.5px;color:#4a5568;margin-bottom:4px;line-height:1.5;border-left:3px solid {m['color']};padding-left:7px'>{n['title'][:100]}</div>"
            for n in news[:3])

        crypto_cards += f"""
        <div class="ccard" style="border-top:3px solid {m['color']};direction:ltr">
          <div class="ccard-sym" style="color:{m['color']}">{sym}</div>
          <div style="font-size:10px;color:#718096">{m['name']}</div>
          <div class="ccard-price">{price}</div>
          <div class="ccard-cat" style="{cat_style}">{cat_en}</div>
          <div style="margin-bottom:6px">
            <span style="font-size:9px;padding:1px 6px;border-radius:4px;background:{sent_col}20;color:{sent_col};font-weight:700">Sentiment: {sent_lbl}</span>
          </div>
          {news_html}
        </div>"""

    action_rows = ""
    actions_en = {
        "MU":   ("HOLD · Do NOT add pre-earnings Jun 24", "warn"),
        "NOW":  ("ACCUMULATE toward $100-105", "pos"),
        "PLTR": ("HOLD · Accumulate below $120", "pos"),
        "CBRS": ("HOLD · Watch lockup daily", "neg"),
        "XRP":  ("HOLD · Small add below $0.45", "pos"),
        "SOL":  ("HOLD · Strong fundamentals", "hl"),
        "HBAR": ("HOLD · High conviction long-term", "pos"),
        "ADA":  ("HOLD · Wait Q4 mainnet", "hl"),
        "ARB":  ("HOLD · Last priority in risk-off", "hl"),
        "DOT":  ("NEUTRAL HOLD", "hl"),
        "SHIB": ("HOLD ONLY · No additions", "neg"),
        "GALA": ("HOLD ONLY · Monitor pipeline", "neg"),
    }
    for sym, (action_en, css) in actions_en.items():
        if sym in STOCKS:
            q = data["stocks"].get(sym, {}).get("quote", {})
            price = fmt_price(q.get("price", 0)) if q else "N/A"
        else:
            pd = data["crypto"].get(sym, {}).get("price", {})
            price = fmt_price(pd.get("price", 0), sym) if pd else "N/A"
        color = STOCK_META.get(sym, CRYPTO_META.get(sym, {})).get("color", "#374151")
        action_rows += f"""<tr>
          <td><strong style="color:{color}">{sym}</strong></td>
          <td style="font-family:'DV',sans-serif">{price}</td>
          <td class="{css}">{action_en}</td>
        </tr>"""

    return f"""
<div class="page en">
  <div style="background:linear-gradient(135deg,#0f2d5a,#1d4ed8);border-radius:12px;padding:16px 26px;margin-bottom:18px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 4px 16px rgba(29,78,216,0.22)">
    <div>
      <div style="font-size:10px;color:rgba(255,255,255,0.65);margin-bottom:3px">Part 2 of 2 · Crypto &amp; Action Plan</div>
      <div style="font-size:18px;font-weight:700;color:#fff">Crypto · Action Plan · Scenarios</div>
    </div>
    <div style="font-size:11px;color:rgba(255,255,255,0.75)">{today_str} · 2:30 PM GST</div>
  </div>

  <div class="sec"><div class="dot"></div>₿ CRYPTO — Prices &amp; News</div>
  <div class="g4">{crypto_cards}</div>

  <div class="sec"><div class="dot"></div>⚡ ACTION PLAN — My Direct Recommendations</div>
  <table class="tbl" style="direction:ltr">
    <tr><th>Asset</th><th>Price</th><th>Recommendation</th></tr>
    {action_rows}
  </table>

  <div class="bline">
    <h3>⚡ Today's Bottom Line</h3>
    <p>Your portfolio is operating in a volatile macro environment driven by three forces: AI valuation reset post-Broadcom, Fed rate-hike fears from the strong jobs report, and oil/inflation pressure from the Iran conflict. Crypto is trading as a risk asset rather than safe haven. Watch the June 10 CPI and June 24 MU earnings — these are the two most critical catalysts for your portfolio this month.</p>
  </div>

  <div class="footer">Part 2 of 2 · Crypto &amp; Action Plan · {today_str} · For informational purposes only · Not financial advice</div>
</div>"""


def build_pdf(html_content, out_path):
    """Render HTML to PDF via Playwright."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        pg.set_content(html_content, wait_until='networkidle')
        pg.wait_for_timeout(3000)
        pg.pdf(path=out_path, width='1240px', print_background=True,
               margin={"top":"0","bottom":"0","left":"0","right":"0"})
        browser.close()
    size = os.path.getsize(out_path) // 1024
    print(f"  ✅ PDF: {out_path} ({size} KB)")


def build_all_pdfs(data, today_str):
    """Build all 4 PDFs and return their paths."""
    print("\n🎨 Building PDFs...")

    am  = b64font(f"{FONT_DIR}/Amiri-Regular.ttf")
    amb = b64font(f"{FONT_DIR}/Amiri-Bold.ttf")
    dv  = b64font(f"{FONT_DIR}/DejaVuSans.ttf")
    dvb = b64font(f"{FONT_DIR}/DejaVuSans-Bold.ttf")
    css = build_css(am, amb, dv, dvb)

    wrap = lambda body: f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>{css}</style></head>
<body>{body}</body></html>"""

    date_safe = today_str.replace(",", "").replace(" ", "_")
    out_dir   = "/mnt/user-data/outputs"
    os.makedirs(out_dir, exist_ok=True)

    pdfs = {}
    configs = [
        ("ar_stocks",  wrap(build_part1_ar(data, today_str)), f"{out_dir}/briefing_ar_stocks_{date_safe}.pdf"),
        ("ar_crypto",  wrap(build_part2_ar(data, today_str)), f"{out_dir}/briefing_ar_crypto_{date_safe}.pdf"),
        ("en_stocks",  wrap(build_part1_en(data, today_str)), f"{out_dir}/briefing_en_stocks_{date_safe}.pdf"),
        ("en_crypto",  wrap(build_part2_en(data, today_str)), f"{out_dir}/briefing_en_crypto_{date_safe}.pdf"),
    ]

    for key, html, path in configs:
        build_pdf(html, path)
        pdfs[key] = path

    return pdfs


# ── EMAIL SENDER ─────────────────────────────────────────────

def upload_pdf_to_github(local_path: str, gh_filename: str) -> str:
    """Upload PDF to GitHub repo and return raw URL."""
    with open(local_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    api_path = f"https://api.github.com/repos/{GITHUB_REPO}/contents/reports/{gh_filename}"
    headers  = {
        "Authorization": f"token {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }

    # Check if file exists (need SHA to update)
    check = requests.get(api_path, headers=headers)
    sha = check.json().get("sha") if check.status_code == 200 else None

    payload = {"message": f"Update {gh_filename}", "content": content_b64, "branch": "main"}
    if sha:
        payload["sha"] = sha

    resp = requests.put(api_path, headers=headers, json=payload)
    if resp.status_code in (200, 201):
        raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/reports/{gh_filename}"
        print(f"  ✅ Uploaded: {raw_url}")
        return raw_url
    else:
        print(f"  ⚠️  Upload failed: {resp.status_code} {resp.text[:100]}")
        return ""


def send_email_via_github(subject: str, body: str) -> bool:
    """Trigger GitHub dispatch to send email via Resend relay."""
    headers = {
        "Authorization": f"token {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }
    payload = {
        "event_type": "send-email",
        "client_payload": {
            "from":    EMAIL_FROM,
            "to":      EMAIL_TO,
            "subject": subject,
            "text":    body,
        }
    }
    resp = requests.post(
        f"https://api.github.com/repos/{GITHUB_REPO}/dispatches",
        headers=headers, json=payload
    )
    if resp.status_code == 204:
        print("  ✅ Email dispatched via GitHub Actions")
        return True
    else:
        print(f"  ⚠️  Dispatch failed: {resp.status_code} {resp.text[:100]}")
        return False


def send_briefing(pdfs: dict, data: dict, today_str: str):
    """Upload PDFs to GitHub and send email with download links."""
    print("\n📧 Uploading PDFs and sending email...")

    date_safe = today_str.replace(",", "").replace(" ", "_")
    pdf_urls  = {}

    for key, path in pdfs.items():
        fname = os.path.basename(path)
        url = upload_pdf_to_github(path, fname)
        if url:
            pdf_urls[key] = url
        time.sleep(1)

    time.sleep(3)  # Let GitHub propagate

    # Build stock summary for email body
    stock_lines = []
    for sym in STOCKS:
        q = data["stocks"][sym].get("quote", {})
        if q:
            price = fmt_price(q.get("price", 0))
            chg   = q.get("chg_pct", "0")
            arrow = "▲" if float(chg) >= 0 else "▼"
            stock_lines.append(f"  {sym}: {price} {arrow}{abs(float(chg)):.2f}%")

    crypto_lines = []
    for sym in ["XRP", "SOL", "HBAR", "ADA"]:
        pd = data["crypto"].get(sym, {}).get("price", {})
        if pd:
            price = fmt_price(pd.get("price", 0), sym)
            crypto_lines.append(f"  {sym}: {price}")

    body = f"""السلام عليكم سيف،

📊 التقرير الصباحي لمحفظتك — {today_str}
════════════════════════════════════

📈 الأسهم:
{chr(10).join(stock_lines) or '  بيانات غير متاحة'}

₿ الكريبتو (مختارات):
{chr(10).join(crypto_lines) or '  بيانات غير متاحة'}

════════════════════════════════════
📥 روابط تحميل التقارير:

🇸🇦 عربي — الأسهم:
{pdf_urls.get('ar_stocks', 'غير متاح')}

🇸🇦 عربي — الكريبتو وخطة العمل:
{pdf_urls.get('ar_crypto', 'غير متاح')}

🇬🇧 English — Stocks:
{pdf_urls.get('en_stocks', 'N/A')}

🇬🇧 English — Crypto & Action Plan:
{pdf_urls.get('en_crypto', 'N/A')}

════════════════════════════════════
⚠️  هذا التقرير للأغراض المعلوماتية فقط وليس نصيحة مالية.
تم الإنتاج بواسطة Claude · Alpha Vantage MCP
"""

    subject = f"📊 تقرير الصباح — محفظتك | {today_str}"
    send_email_via_github(subject, body)


# ── MAIN ─────────────────────────────────────────────────────

def run():
    now      = datetime.datetime.now()
    today_ar = now.strftime("%A, %B %d, %Y")  # e.g. "Sunday, June 08, 2026"

    print(f"\n{'='*55}")
    print(f"  MORNING BRIEFING AGENT — {today_ar}")
    print(f"{'='*55}")

    # 1. Collect data
    data = collect_all_data()

    # 2. Build PDFs
    pdfs = build_all_pdfs(data, today_ar)

    # 3. Send email
    send_briefing(pdfs, data, today_ar)

    print(f"\n✅ Briefing complete — {today_ar}\n")
    return pdfs, data

if __name__ == "__main__":
    run()
