"""
Morning Briefing Agent — Saif's Portfolio
=========================================
Runs every weekday at 2:30 PM GST (10:30 UTC).
Sends 3 PDFs:
  1. Arabic Portfolio PDF  — محفظتك الشخصية (عربي)
  2. Arabic Market PDF     — تحليل السوق + فرص الدخول (عربي)
  3. English Market PDF    — Market Analysis + Opportunities (English)
"""

import os, base64, time, datetime, requests
from playwright.sync_api import sync_playwright

# ── CONFIG ────────────────────────────────────────────────────
AV_KEY      = os.environ.get("AV_KEY", "HONKZR3NHFIQ59P4")
AV_BASE     = "https://www.alphavantage.co/query"
GITHUB_PAT  = os.environ.get("BRIEFING_PAT", "")
GITHUB_REPO = "uaesniper606-byte/Claude-Emails"
EMAIL_TO    = "uae.sniper606@gmail.com"
EMAIL_FROM  = "onboarding@resend.dev"

# ── SAIF'S PORTFOLIO (fixed) ──────────────────────────────────
PORTFOLIO = {
    "stocks": [
        {"sym":"MU",   "name":"مايكرون تكنولوجي",    "name_en":"Micron Technology",    "qty":33,             "buy":1037.10, "color":"E53E3E", "earn":"24 يونيو 2026"},
        {"sym":"NOW",  "name":"سيرفس ناو",            "name_en":"ServiceNow",           "qty":100,            "buy":135.60,  "color":"059669", "earn":"29 يوليو 2026"},
        {"sym":"PLTR", "name":"بالانتير",             "name_en":"Palantir Technologies","qty":52,             "buy":162.50,  "color":"7C3AED", "earn":"10 أغسطس 2026"},
        {"sym":"CBRS", "name":"سيريبراس سيستمز",     "name_en":"Cerebras Systems",     "qty":33,             "buy":300.00,  "color":"D97706", "earn":"غير محدد"},
    ],
    "crypto": [
        {"sym":"XRP",  "name":"ريبل",        "name_en":"Ripple",     "qty":1091.9141638,   "buy":0.94640265, "color":"0284C7", "cat":"مدفوعات"},
        {"sym":"SOL",  "name":"سولانا",      "name_en":"Solana",     "qty":18.67559317,    "buy":82.35,      "color":"9945FF", "cat":"بنية تحتية"},
        {"sym":"HBAR", "name":"هيدرا",       "name_en":"Hedera",     "qty":6888.17073321,  "buy":0.27098023, "color":"0D9488", "cat":"بنية تحتية"},
        {"sym":"SHIB", "name":"شيبا إينو",   "name_en":"Shiba Inu",  "qty":9130010.54,     "buy":0.000055,   "color":"DC2626", "cat":"ميم"},
        {"sym":"ADA",  "name":"كاردانو",     "name_en":"Cardano",    "qty":137.26467321,   "buy":1.78,       "color":"1D4ED8", "cat":"بنية تحتية"},
        {"sym":"ARB",  "name":"أربيتروم",    "name_en":"Arbitrum",   "qty":221.88235265,   "buy":0.1049,     "color":"0EA5E9", "cat":"الطبقة 2"},
        {"sym":"DOT",  "name":"بولكادوت",    "name_en":"Polkadot",   "qty":6.14489028,     "buy":46.30,      "color":"DB2777", "cat":"بنية تحتية"},
        {"sym":"GALA", "name":"غالا غيمز",   "name_en":"Gala Games", "qty":1051.07179997,  "buy":0.379773,   "color":"D97706", "cat":"ألعاب"},
    ]
}

# ── FONTS ─────────────────────────────────────────────────────
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

def b64f(p):
    with open(p, "rb") as f: return base64.b64encode(f.read()).decode()

# ── DATA FETCH ────────────────────────────────────────────────
def av_get(params):
    """Alpha Vantage — used for NEWS only (prices come from yfinance)."""
    params["apikey"] = AV_KEY
    try:
        r = requests.get(AV_BASE, params=params, timeout=15)
        d = r.json()
        if "Note" in d or "Information" in d:
            return {}
        return d
    except:
        return {}

def fetch_quote(symbol):
    """Fetch real-time quote via yfinance (price, pre-market, after-hours)."""
    result = {
        "price": 0, "change": 0, "chg_pct": "0",
        "volume": 0, "high": 0, "low": 0,
        "pre_price": None, "pre_chg_pct": None,
        "post_price": None, "post_chg_pct": None,
    }
    try:
        import yfinance as yf
        t    = yf.Ticker(symbol)
        info = t.info

        # Regular session
        price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose") or 0
        prev  = info.get("previousClose") or info.get("regularMarketPreviousClose") or price
        chg   = price - prev
        chg_p = (chg / prev * 100) if prev else 0

        result.update({
            "price":   round(float(price), 2),
            "change":  round(float(chg), 2),
            "chg_pct": f"{chg_p:.2f}",
            "volume":  info.get("regularMarketVolume") or info.get("volume") or 0,
            "high":    round(float(info.get("regularMarketDayHigh") or info.get("dayHigh") or 0), 2),
            "low":     round(float(info.get("regularMarketDayLow") or info.get("dayLow") or 0), 2),
        })

        # Pre-Market
        pre_p = info.get("preMarketPrice")
        pre_c = info.get("preMarketChangePercent")
        if pre_p and pre_p > 0:
            result["pre_price"]   = round(float(pre_p), 2)
            result["pre_chg_pct"] = round(float(pre_c) * 100, 2) if pre_c else round((pre_p - price) / price * 100, 2)

        # After-Hours
        post_p = info.get("postMarketPrice")
        post_c = info.get("postMarketChangePercent")
        if post_p and post_p > 0:
            result["post_price"]   = round(float(post_p), 2)
            result["post_chg_pct"] = round(float(post_c) * 100, 2) if post_c else round((post_p - price) / price * 100, 2)

        print(f"  {symbol}: ${result['price']} | Pre: {result['pre_price']} | Post: {result['post_price']}")
    except Exception as e:
        print(f"  ⚠️ yfinance error for {symbol}: {e}")
    return result

def fetch_crypto(symbol):
    d = av_get({"function": "CURRENCY_EXCHANGE_RATE",
                "from_currency": symbol, "to_currency": "USD"})
    r = d.get("Realtime Currency Exchange Rate", {})
    if not r: return {}
    return {"price": float(r.get("5. Exchange Rate", 0))}

def fetch_news(ticker, limit=4):
    d = av_get({"function": "NEWS_SENTIMENT", "tickers": ticker, "limit": str(limit)})
    feed = d.get("feed", [])
    out = []
    for item in feed[:limit]:
        score = 0.0
        for ts in item.get("ticker_sentiment", []):
            if ts.get("ticker","").upper() == ticker.upper():
                score = float(ts.get("ticker_sentiment_score", 0))
                break
        out.append({"title": item.get("title","")[:120], "score": score})
    return out

def fmt_price(p, sym=""):
    if p == 0: return "N/A"
    if p < 0.0001: return f"${p:.8f}"
    if p < 1: return f"${p:.4f}"
    return f"${p:,.2f}"

def fmt_vol(v):
    if v >= 1_000_000: return f"{v/1_000_000:.2f}M"
    if v >= 1_000: return f"{v/1_000:.0f}K"
    return str(v)


def collect_data():
    print("📡 Fetching live market data...")
    data = {"stocks": {}, "crypto": {}}

    for s in PORTFOLIO["stocks"]:
        sym = s["sym"]
        print(f"  {sym}...")
        q    = fetch_quote(sym)
        news = fetch_news(sym, 4)
        # pre/post market now included in quote
        data["stocks"][sym] = {"quote": q, "news": news}
        time.sleep(1.2)

    for c in PORTFOLIO["crypto"]:
        sym = c["sym"]
        print(f"  {sym}...")
        price = fetch_crypto(sym)
        news  = fetch_news(f"CRYPTO:{sym}", 3)
        data["crypto"][sym] = {"price": price, "news": news}
        time.sleep(1.2)

    print("✅ Data collected.\n")
    return data

# ── CSS (shared light theme) ──────────────────────────────────
def build_css(am, amb, dv, dvb):
    return f"""
@font-face{{font-family:'AM';src:url('data:font/ttf;base64,{am}');font-weight:400}}
@font-face{{font-family:'AM';src:url('data:font/ttf;base64,{amb}');font-weight:700}}
@font-face{{font-family:'DV';src:url('data:font/ttf;base64,{dv}');font-weight:400}}
@font-face{{font-family:'DV';src:url('data:font/ttf;base64,{dvb}');font-weight:700}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#eef2f7;width:1240px}}
.ar{{font-family:'AM',serif;font-size:13.5px;direction:rtl;unicode-bidi:embed;color:#1a2332}}
.en{{font-family:'DV',sans-serif;font-size:12.5px;direction:ltr;color:#1a2332}}
.num{{font-family:'DV',sans-serif}}
.page{{width:1240px;padding:32px 40px;background:#eef2f7;page-break-after:always;min-height:1754px}}
.hdr{{background:linear-gradient(135deg,#0f2d5a,#1d4ed8,#2563eb);border-radius:16px;
      padding:26px 34px;margin-bottom:18px;display:flex;justify-content:space-between;
      align-items:center;box-shadow:0 6px 28px rgba(29,78,216,.28)}}
.hdr-badge{{background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.35);
            border-radius:20px;padding:3px 12px;font-size:10px;color:rgba(255,255,255,.92);
            margin-bottom:6px;display:inline-block}}
.hdr-title{{font-size:22px;font-weight:700;color:#fff;margin-bottom:4px}}
.hdr-sub{{font-size:11px;color:rgba(255,255,255,.72)}}
.sec{{font-size:13px;font-weight:700;color:#0f2d5a;padding:8px 0 7px;
      border-bottom:2px solid #c7d9f0;margin:16px 0 11px;
      display:flex;align-items:center;gap:7px}}
.sec-ar{{flex-direction:row-reverse}}
.dot{{width:7px;height:7px;border-radius:50%;background:#1d4ed8;flex-shrink:0}}
.g2{{display:grid;grid-template-columns:1fr 1fr;gap:11px;margin-bottom:11px}}
.g3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:11px}}
.g4{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:9px;margin-bottom:11px}}
.card{{background:#fff;border-radius:11px;padding:13px 15px;border:1px solid #dde5f0;
       box-shadow:0 2px 8px rgba(0,0,0,.05)}}
.pos{{color:#276749;font-weight:700}}.neg{{color:#c53030;font-weight:700}}
.hl{{color:#2b6cb0;font-weight:700}}.warn{{color:#c05621;font-weight:700}}
.strip{{display:flex;gap:2px;margin-bottom:16px;border-radius:11px;overflow:hidden;
        box-shadow:0 2px 8px rgba(0,0,0,.07)}}
.sc{{flex:1;padding:11px 8px;text-align:center}}
.sv{{font-size:17px;font-weight:700;font-family:'DV',sans-serif}}
.sl{{font-size:9px;color:#718096;margin-top:2px;font-family:'DV',sans-serif}}
.scard{{background:#fff;border-radius:11px;border:1px solid #dde5f0;
        box-shadow:0 2px 8px rgba(0,0,0,.05);overflow:hidden;margin-bottom:11px}}
.scard-top{{padding:12px 15px;border-bottom:1px solid #f0f4f8}}
.scard-sym{{font-size:19px;font-weight:700}}
.scard-name{{font-size:10px;color:#718096;margin-top:1px}}
.scard-row{{display:flex;justify-content:space-between;align-items:center}}
.scard-price{{font-size:18px;font-weight:700;color:#0f2d5a;font-family:'DV',sans-serif}}
.scard-meta{{padding:7px 15px;background:#f8faff;display:flex;gap:7px;flex-wrap:wrap}}
.stag{{background:#e5e7eb;border-radius:4px;padding:2px 6px;font-size:9.5px;color:#374151}}
.stag-e{{background:#fef3c7;border-radius:4px;padding:2px 6px;font-size:9.5px;color:#92400e}}
.stag-s{{border-radius:4px;padding:2px 6px;font-size:9.5px;font-weight:700}}
.stag-buy{{background:#dcfce7;border-radius:4px;padding:2px 6px;font-size:9.5px;color:#166534;font-weight:700}}
.stag-loss{{background:#fee2e2;border-radius:4px;padding:2px 6px;font-size:9.5px;color:#991b1b;font-weight:700}}
.scard-news{{padding:9px 15px}}
.scard-news ul{{padding-left:13px;list-style:disc}}
.scard-news ul.ar{{padding-right:13px;padding-left:0;list-style:disc}}
.scard-news li{{font-size:10.5px;color:#4a5568;margin-bottom:3px;line-height:1.5}}
.pnl-box{{padding:9px 15px;border-top:1px solid #f0f4f8;background:#fafbff;
           display:flex;gap:16px;align-items:center}}
.pnl-lbl{{font-size:10px;color:#718096}}
.pnl-val{{font-size:13px;font-weight:700;font-family:'DV',sans-serif}}
.ccard{{background:#fff;border-radius:10px;padding:11px 13px;border:1px solid #dde5f0;
        box-shadow:0 2px 6px rgba(0,0,0,.05)}}
.ccard-sym{{font-size:14px;font-weight:700}}
.ccard-price{{font-size:12px;font-weight:700;color:#0f2d5a;font-family:'DV',sans-serif;margin-top:2px}}
.ccard-cat{{font-size:9px;font-weight:700;padding:2px 5px;border-radius:3px;
            display:inline-block;margin:3px 0 4px}}
.bc{{background:#fff;border-radius:11px;padding:13px 15px;border:1px solid #dde5f0;box-shadow:0 2px 8px rgba(0,0,0,.05)}}
.bc-t{{font-size:11.5px;font-weight:700;color:#0f2d5a;margin-bottom:10px}}
.brow{{display:flex;align-items:center;gap:8px;margin-bottom:7px}}
.brow-ar{{flex-direction:row-reverse}}
.blbl{{font-size:10.5px;color:#2d3748;min-width:52px}}
.btrack{{flex:1;background:#f0f4f8;border-radius:4px;height:17px;overflow:hidden}}
.bfill{{height:100%;border-radius:4px;display:flex;align-items:center;padding:0 6px;justify-content:flex-end}}
.bval{{font-size:9px;font-weight:700;color:#fff;font-family:'DV',sans-serif}}
.tbl{{width:100%;border-collapse:separate;border-spacing:0;margin-bottom:11px;
      border-radius:9px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.tbl th{{background:#0f2d5a;color:#fff;font-size:10px;font-weight:700;padding:8px 11px}}
.tbl td{{padding:8px 11px;font-size:11.5px;color:#2d3748;background:#fff;border-bottom:1px solid #f0f4f8}}
.tbl tr:last-child td{{border-bottom:none}}
.tbl tr:nth-child(even) td{{background:#f7faff}}
.bline{{background:linear-gradient(135deg,#0f2d5a,#1d4ed8);border-radius:12px;
        padding:17px 21px;margin-bottom:15px;box-shadow:0 6px 20px rgba(29,78,216,.22)}}
.bline h3{{color:#fff;font-size:13px;margin-bottom:7px;font-weight:700}}
.bline p{{font-size:12px;color:rgba(255,255,255,.90);line-height:1.75}}
.cal-g{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:11px}}
.cal{{background:#fff;border-radius:9px;padding:10px;border:1px solid #dde5f0;text-align:center}}
.cal.hot{{border-color:#fca5a5;background:linear-gradient(135deg,#fff5f5,#ffe8e8)}}
.cal.warm{{border-color:#fbd38d;background:linear-gradient(135deg,#fffdf0,#fef3c7)}}
.cal.cool{{border-color:#bee3f8;background:linear-gradient(135deg,#ebf8ff,#dde9f5)}}
.cal-d{{font-size:9px;color:#718096;margin-bottom:3px;font-family:'DV',sans-serif}}
.cal-e{{font-size:10px;color:#0f2d5a;font-weight:700;line-height:1.3}}
.opp{{background:linear-gradient(135deg,#f0fff4,#dcfce7);border:1.5px solid #86efac;
      border-radius:11px;padding:13px 15px;margin-bottom:10px}}
.opp-t{{font-size:12.5px;font-weight:700;color:#065f46;margin-bottom:5px}}
.opp p{{font-size:11.5px;color:#374151;line-height:1.65}}
.sc3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:12px}}
.scn{{border-radius:11px;padding:13px 15px;border:1.5px solid}}
.s-bull{{background:linear-gradient(135deg,#f0fff4,#e6ffed);border-color:#9ae6b4}}
.s-base{{background:linear-gradient(135deg,#ebf8ff,#e3f0ff);border-color:#bee3f8}}
.s-bear{{background:linear-gradient(135deg,#fff5f5,#ffe8e8);border-color:#fca5a5}}
.sn-t{{font-size:12px;font-weight:700;margin-bottom:5px}}
.s-bull .sn-t{{color:#276749}}.s-base .sn-t{{color:#2a4365}}.s-bear .sn-t{{color:#c53030}}
.scn p{{font-size:11px;color:#2d3748;line-height:1.65}}
.prob{{font-size:10px;font-weight:700;padding:2px 9px;border-radius:9px;
       display:inline-block;margin-bottom:6px;font-family:'DV',sans-serif}}
.s-bull .prob{{background:#c6f6d5;color:#276749}}
.s-base .prob{{background:#bee3f8;color:#2a4365}}
.s-bear .prob{{background:#fed7d7;color:#c53030}}
.alert{{border-radius:10px;padding:11px 15px;margin-bottom:13px;display:flex;gap:10px}}
.alert-ar{{flex-direction:row-reverse}}
.a-r{{background:#fff5f5;border:1.5px solid #feb2b2;border-right:4px solid #e53e3e}}
.a-a{{background:#fffdf0;border:1.5px solid #fbd38d;border-right:4px solid #dd6b20}}
.a-b{{background:#ebf8ff;border:1.5px solid #bee3f8;border-right:4px solid #3182ce}}
.a-icon{{font-size:18px;flex-shrink:0}}
.a-title{{font-weight:700;font-size:12.5px;margin-bottom:3px}}
.a-r .a-title{{color:#c53030}}.a-a .a-title{{color:#7b341e}}.a-b .a-title{{color:#2a4365}}
.a-body{{font-size:11.5px;color:#4a5568;line-height:1.65}}
.footer{{text-align:center;color:#a0aec0;font-size:9.5px;padding:9px 0;
         border-top:1px solid #dde5f0;font-family:'DV',sans-serif}}
.total-row{{background:linear-gradient(135deg,#0f2d5a,#1d4ed8);border-radius:10px;
            padding:14px 18px;display:flex;justify-content:space-around;
            margin-bottom:14px;box-shadow:0 4px 16px rgba(29,78,216,.2)}}
.tot-item{{text-align:center}}
.tot-val{{font-size:20px;font-weight:700;color:#fff;font-family:'DV',sans-serif}}
.tot-lbl{{font-size:10px;color:rgba(255,255,255,.72);margin-top:3px}}
"""

# ════════════════════════════════════════════════════════════
# PDF 1: ARABIC PORTFOLIO (محفظة سيف)
# ════════════════════════════════════════════════════════════
def build_portfolio_ar(data, date_str, session="الصباحي", icon="🌅", time_gst="10:30 GST", am="", amb="", dv="", dvb=""):
    css = build_css(am, amb, dv, dvb)
    port = PORTFOLIO

    # Calculate totals
    s_cost = s_val = 0
    for s in port["stocks"]:
        q = data["stocks"][s["sym"]].get("quote", {})
        cur = q.get("price", s["buy"])
        s_cost += s["qty"] * s["buy"]
        s_val  += s["qty"] * cur

    c_cost = c_val = 0
    for c in port["crypto"]:
        p = data["crypto"][c["sym"]].get("price", {})
        cur = p.get("price", c["buy"])
        c_cost += c["qty"] * c["buy"]
        c_val  += c["qty"] * cur

    t_cost = s_cost + c_cost
    t_val  = s_val  + c_val
    t_pnl  = t_val  - t_cost
    t_pct  = (t_pnl / t_cost) * 100 if t_cost else 0

    def pnl_color(v): return "#c53030" if v < 0 else "#276749"
    def arrow(v): return "▼" if v < 0 else "▲"

    # Stock cards
    stock_cards = ""
    for s in port["stocks"]:
        sym = s["sym"]
        q   = data["stocks"][sym].get("quote", {})
        news= data["stocks"][sym].get("news", [])
        ext = data["stocks"][sym].get("extended", {})

        # Extended hours — now in quote directly
        post_p  = q.get("post_price")
        post_c  = q.get("post_chg_pct")
        pre_p   = q.get("pre_price")
        pre_c   = q.get("pre_chg_pct")

        # ── Extended hours badges ─────────────────────────────
        ext_badge = ""
        if post_p and post_c is not None:
            psgn = "▲" if post_c >= 0 else "▼"
            pcol = "#276749" if post_c >= 0 else "#c53030"
            ext_badge += f'''<span class="stag" style="background:{pcol}18;color:{pcol};font-weight:700;border:1px solid {pcol}40">🌙 After-Hours: {fmt_price(post_p)} {psgn}{abs(post_c):.2f}%</span>'''
        if pre_p and pre_c is not None:
            prsgn = "▲" if pre_c >= 0 else "▼"
            prcol = "#276749" if pre_c >= 0 else "#c53030"
            ext_badge += f'''<span class="stag" style="background:{prcol}18;color:{prcol};font-weight:700;border:1px solid {prcol}40">🌅 Pre-Market: {fmt_price(pre_p)} {prsgn}{abs(pre_c):.2f}%</span>'''

        # ── Extended hours ANALYSIS text ──────────────────────
        ext_analysis = ""
        if post_p and post_c is not None:
            if abs(post_c) >= 1.0:
                direction = "ارتفع" if post_c > 0 else "انخفض"
                strength  = "بشكل حاد" if abs(post_c) > 3 else "بشكل معتدل"
                ext_analysis += f"{sym} {direction} {strength} في التداول الممتد بعد الإغلاق ({'+' if post_c>0 else ''}{post_c:.2f}%) وصل إلى {fmt_price(post_p)}. "
            else:
                ext_analysis += f"{sym} تداول ثابت نسبياً بعد الإغلاق ({'+' if post_c>0 else ''}{post_c:.2f}%). "
        if pre_p and pre_c is not None:
            if abs(pre_c) >= 0.5:
                direction2 = "يرتفع" if pre_c > 0 else "ينخفض"
                signal     = "إشارة إيجابية قبل الافتتاح" if pre_c > 0 else "ضغط بيعي قبل الافتتاح"
                ext_analysis += f"Pre-Market: {sym} {direction2} {abs(pre_c):.2f}% عند {fmt_price(pre_p)} — {signal}."
            else:
                ext_analysis += f"Pre-Market: تداول هادئ عند {fmt_price(pre_p)}."


        cur = q.get("price", s["buy"])
        chg_pct = float(q.get("chg_pct", 0))
        vol = fmt_vol(q.get("volume", 0))
        cost  = s["qty"] * s["buy"]
        val   = s["qty"] * cur
        pnl   = val - cost
        pnl_p = (pnl / cost) * 100 if cost else 0
        col   = s["color"]
        news_html = "".join(f"<li>{n['title']}</li>" for n in news[:4])
        chg_col = pnl_color(chg_pct)

        stock_cards += f"""
<div class="scard" style="border-top:3px solid #{col}">
  <div class="scard-top">
    <div class="scard-row" style="flex-direction:row-reverse">
      <div style="text-align:right">
        <div class="scard-sym" style="color:#{col}">{sym}</div>
        <div class="scard-name">{s['name']}</div>
      </div>
      <div style="text-align:left">
        <div class="scard-price">{fmt_price(cur)}</div>
        <div style="font-family:DV;font-size:11px;color:{chg_col}">{arrow(chg_pct)} {abs(chg_pct):.2f}% &nbsp;|&nbsp; حجم: {vol}</div>
      </div>
    </div>
  </div>
  <div class="scard-meta" style="flex-direction:row-reverse">
    <span class="stag">{s['qty']} سهم × {fmt_price(s['buy'])} دخول</span>
    <span class="stag-e">⚠ الأرباح: {s['earn']}</span>
    <span class="{'stag-buy' if pnl>=0 else 'stag-loss'}">{arrow(pnl_p)} {abs(pnl_p):.1f}%</span>
  </div>
  {f'<div style="padding:6px 15px;background:#f0f9ff;border-bottom:1px solid #e0f0ff;display:flex;gap:8px;flex-wrap:wrap;flex-direction:row-reverse">' + ext_badge + '</div>' if ext_badge else ""}
  {f'<div style="padding:7px 15px;background:#fffdf0;border-bottom:1px solid #fef3c7;font-size:11px;color:#374151;text-align:right;line-height:1.6">' + ext_analysis + '</div>' if ext_analysis else ""}
  <div class="scard-news"><ul class="ar">{news_html if news_html else '<li>لا أخبار متاحة حالياً</li>'}</ul></div>
  <div class="pnl-box" style="flex-direction:row-reverse">
    <div class="tot-item">
      <div class="pnl-lbl">التكلفة</div>
      <div class="pnl-val" style="color:#374151">{fmt_price(cost)}</div>
    </div>
    <div class="tot-item">
      <div class="pnl-lbl">القيمة الحالية</div>
      <div class="pnl-val" style="color:#0f2d5a">{fmt_price(val)}</div>
    </div>
    <div class="tot-item">
      <div class="pnl-lbl">الربح / الخسارة</div>
      <div class="pnl-val" style="color:{pnl_color(pnl)}">{'+' if pnl>=0 else ''}{fmt_price(pnl)}</div>
    </div>
  </div>
</div>"""

    # Crypto cards
    crypto_cards = ""
    cat_styles = {
        "مدفوعات":   "background:#dcfce7;color:#166534",
        "بنية تحتية":"background:#dbeafe;color:#1e40af",
        "الطبقة 2":  "background:#ede9fe;color:#6d28d9",
        "ميم":        "background:#fee2e2;color:#991b1b",
        "ألعاب":      "background:#fef3c7;color:#92400e",
    }
    for c in port["crypto"]:
        sym = c["sym"]
        p = data["crypto"][sym].get("price", {})
        news = data["crypto"][sym].get("news", [])
        cur   = p.get("price", c["buy"])
        cost  = c["qty"] * c["buy"]
        val   = c["qty"] * cur
        pnl   = val - cost
        pnl_p = (pnl / cost) * 100 if cost else 0
        col   = c["color"]
        cs    = cat_styles.get(c["cat"], "")
        news_html = "".join(f"<div style='font-size:10px;color:#4a5568;margin-bottom:3px;border-right:2px solid #{col};padding-right:6px'>{n['title'][:90]}</div>" for n in news[:3])

        crypto_cards += f"""
<div class="ccard" style="border-top:3px solid #{col};text-align:right">
  <div class="ccard-sym" style="color:#{col}">{sym}</div>
  <div style="font-size:9px;color:#718096">{c['name']}</div>
  <div class="ccard-price">{fmt_price(cur, sym)}</div>
  <div class="ccard-cat" style="{cs}">{c['cat']}</div>
  <div style="margin-bottom:5px">
    <span style="font-size:10px;font-weight:700;color:{pnl_color(pnl_p)}">
      {arrow(pnl_p)} {abs(pnl_p):.1f}% &nbsp;|&nbsp; {'+' if pnl>=0 else ''}{fmt_price(pnl)}
    </span>
  </div>
  <div style="font-size:9px;color:#718096;margin-bottom:5px">
    كمية: <span style="font-family:DV">{c['qty']:,.4f}</span> × <span style="font-family:DV">{fmt_price(c['buy'],sym)}</span>
  </div>
  {news_html if news_html else ''}
</div>"""

    s_pnl  = s_val - s_cost
    c_pnl  = c_val - c_cost

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>{css}</style></head>
<body>
<!-- PAGE 1: STOCKS -->
<div class="page ar">
<div class="hdr" style="flex-direction:row-reverse">
  <div style="text-align:right">
    <div class="hdr-badge">محفظة سيف الشخصية · الأسهم</div>
    <div class="hdr-title">محفظتي — الأسهم</div>
    <div class="hdr-sub">MU · NOW · PLTR · CBRS</div>
  </div>
  <div style="text-align:left">
    <div style="font-size:18px;font-weight:700;color:#fff">{date_str}</div>
    <div style="font-size:10px;color:rgba(255,255,255,.7);margin-top:3px">{time_gst} · {session} · بتوقيت الخليج</div>
  </div>
</div>

<div class="total-row">
  <div class="tot-item">
    <div class="tot-val">{fmt_price(s_cost)}</div>
    <div class="tot-lbl">إجمالي التكلفة</div>
  </div>
  <div class="tot-item">
    <div class="tot-val">{fmt_price(s_val)}</div>
    <div class="tot-lbl">القيمة الحالية</div>
  </div>
  <div class="tot-item">
    <div class="tot-val" style="color:{pnl_color(s_pnl)}">{'+' if s_pnl>=0 else ''}{fmt_price(s_pnl)}</div>
    <div class="tot-lbl">الربح / الخسارة</div>
  </div>
  <div class="tot-item">
    <div class="tot-val" style="color:{pnl_color(s_pnl)}">{'+' if s_pnl>=0 else ''}{((s_val-s_cost)/s_cost*100):.1f}%</div>
    <div class="tot-lbl">النسبة الإجمالية</div>
  </div>
</div>

<div class="sec sec-ar"><div class="dot"></div>📈 الأسهم — الأداء والأخبار والربح/الخسارة</div>
<div class="g2">{stock_cards}</div>

<div class="footer">محفظة سيف الشخصية · الأسهم · {date_str} · للأغراض المعلوماتية فقط · ليس نصيحة مالية</div>
</div>

<!-- PAGE 2: CRYPTO -->
<div class="page ar">
<div class="hdr" style="flex-direction:row-reverse">
  <div style="text-align:right">
    <div class="hdr-badge">محفظة سيف الشخصية · الكريبتو</div>
    <div class="hdr-title">محفظتي — الكريبتو</div>
    <div class="hdr-sub">XRP · SOL · HBAR · SHIB · ADA · ARB · DOT · GALA</div>
  </div>
  <div style="text-align:left">
    <div style="font-size:18px;font-weight:700;color:#fff">{date_str}</div>
    <div style="font-size:10px;color:rgba(255,255,255,.7);margin-top:3px">2:30 ظهرًا · بتوقيت الخليج</div>
  </div>
</div>

<div class="total-row">
  <div class="tot-item">
    <div class="tot-val">{fmt_price(c_cost)}</div>
    <div class="tot-lbl">إجمالي التكلفة</div>
  </div>
  <div class="tot-item">
    <div class="tot-val">{fmt_price(c_val)}</div>
    <div class="tot-lbl">القيمة الحالية</div>
  </div>
  <div class="tot-item">
    <div class="tot-val" style="color:{pnl_color(c_pnl)}">{'+' if c_pnl>=0 else ''}{fmt_price(c_pnl)}</div>
    <div class="tot-lbl">الربح / الخسارة</div>
  </div>
  <div class="tot-item">
    <div class="tot-val" style="color:{pnl_color(c_pnl)}">{'+' if c_pnl>=0 else ''}{((c_val-c_cost)/c_cost*100):.1f}%</div>
    <div class="tot-lbl">النسبة الإجمالية</div>
  </div>
</div>

<div class="sec sec-ar"><div class="dot"></div>₿ الكريبتو — الأسعار والأخبار والربح/الخسارة</div>
<div class="g4">{crypto_cards}</div>

<div class="sec sec-ar"><div class="dot"></div>💼 إجمالي المحفظة الكاملة</div>
<div class="total-row">
  <div class="tot-item">
    <div class="tot-val">{fmt_price(t_cost)}</div>
    <div class="tot-lbl">إجمالي الاستثمار</div>
  </div>
  <div class="tot-item">
    <div class="tot-val">{fmt_price(t_val)}</div>
    <div class="tot-lbl">إجمالي القيمة الحالية</div>
  </div>
  <div class="tot-item">
    <div class="tot-val" style="color:{pnl_color(t_pnl)}">{'+' if t_pnl>=0 else ''}{fmt_price(t_pnl)}</div>
    <div class="tot-lbl">إجمالي الربح / الخسارة</div>
  </div>
  <div class="tot-item">
    <div class="tot-val" style="color:{pnl_color(t_pct)}">{'+' if t_pct>=0 else ''}{t_pct:.1f}%</div>
    <div class="tot-lbl">العائد الإجمالي</div>
  </div>
</div>

<div class="sec sec-ar"><div class="dot"></div>⚡ خطة العمل — توصياتي المباشرة</div>
<table class="tbl" style="direction:rtl">
<tr><th style="text-align:right">الأصل</th><th style="text-align:right">السعر</th><th style="text-align:right">ر/خ %</th><th style="text-align:right">التوصية</th></tr>"""

    actions = {
        "MU":   ("احتفظ · لا تضيف قبل الأرباح",  "warn"),
        "NOW":  ("تراكم نحو 100-105",              "pos"),
        "PLTR": ("احتفظ · تراكم دون 120",          "pos"),
        "CBRS": ("احتفظ · راقب Form 4 يوميًا",    "neg"),
        "XRP":  ("احتفظ · إضافة على الضعف",        "pos"),
        "SOL":  ("احتفظ · أساسيات قوية",           "hl"),
        "HBAR": ("احتفظ · ثقة عالية",              "pos"),
        "SHIB": ("احتفظ فقط · لا إضافات",          "neg"),
        "ADA":  ("احتفظ · انتظر mainnet Q4",       "hl"),
        "ARB":  ("احتفظ · آخر أولوية",             "hl"),
        "DOT":  ("احتفظ بحياد",                    "hl"),
        "GALA": ("احتفظ فقط · راقب الألعاب",       "neg"),
    }

    for s in PORTFOLIO["stocks"]:
        sym = s["sym"]
        q = data["stocks"][sym].get("quote", {})
        cur = q.get("price", s["buy"])
        pnl_p = ((cur - s["buy"]) / s["buy"]) * 100
        act, css_cls = actions.get(sym, ("احتفظ", "hl"))
        col = s["color"]
        html += f'<tr><td><strong style="color:#{col}">{sym}</strong></td><td style="font-family:DV">{fmt_price(cur)}</td><td class="{css_cls}" style="font-family:DV">{arrow(pnl_p)}{abs(pnl_p):.1f}%</td><td class="{css_cls}">{act}</td></tr>'

    for c in PORTFOLIO["crypto"]:
        sym = c["sym"]
        p = data["crypto"][sym].get("price", {})
        cur = p.get("price", c["buy"])
        pnl_p = ((cur - c["buy"]) / c["buy"]) * 100
        act, css_cls = actions.get(sym, ("احتفظ", "hl"))
        col = c["color"]
        html += f'<tr><td><strong style="color:#{col}">{sym}</strong></td><td style="font-family:DV">{fmt_price(cur,sym)}</td><td class="{css_cls}" style="font-family:DV">{arrow(pnl_p)}{abs(pnl_p):.1f}%</td><td class="{css_cls}">{act}</td></tr>'

    html += f"""
</table>
<div class="footer">محفظة سيف الشخصية · الكريبتو وخطة العمل · {date_str} · للأغراض المعلوماتية فقط · ليس نصيحة مالية</div>
</div>
</body></html>"""
    return html

# ════════════════════════════════════════════════════════════
# PDF 2 & 3: MARKET ANALYSIS (AR + EN)
# ════════════════════════════════════════════════════════════

def build_portfolio_en(data, date_str, session_en="Morning", icon="🌅", time_gst="10:30 GST", am="", amb="", dv="", dvb=""):
    css = build_css(am, amb, dv, dvb)
    port = PORTFOLIO

    # Totals
    s_cost = s_val = 0
    for s in port["stocks"]:
        q   = data["stocks"][s["sym"]].get("quote", {})
        cur = q.get("price", s["buy"])
        s_cost += s["qty"] * s["buy"]
        s_val  += s["qty"] * cur

    c_cost = c_val = 0
    for c in port["crypto"]:
        p   = data["crypto"][c["sym"]].get("price", {})
        cur = p.get("price", c["buy"])
        c_cost += c["qty"] * c["buy"]
        c_val  += c["qty"] * cur

    t_cost = s_cost + c_cost
    t_val  = s_val  + c_val
    t_pnl  = t_val  - t_cost
    t_pct  = (t_pnl / t_cost) * 100 if t_cost else 0

    def pnl_color(v): return "#c53030" if v < 0 else "#276749"
    def arrow(v):     return "▼" if v < 0 else "▲"

    # ── English Stock Cards ────────────────────────────────────
    stock_cards = ""
    for s in port["stocks"]:
        sym  = s["sym"]
        q    = data["stocks"][sym].get("quote", {})
        news = data["stocks"][sym].get("news", [])

        cur    = q.get("price", s["buy"])
        chg_p  = float(q.get("chg_pct", 0))
        vol    = fmt_vol(q.get("volume", 0))
        cost   = s["qty"] * s["buy"]
        val    = s["qty"] * cur
        pnl    = val - cost
        pnl_p  = (pnl / cost) * 100 if cost else 0
        col    = s["color"]
        hi     = fmt_price(q.get("high", 0))
        lo     = fmt_price(q.get("low", 0))

        # Extended hours
        post_p = q.get("post_price")
        post_c = q.get("post_chg_pct")
        pre_p  = q.get("pre_price")
        pre_c  = q.get("pre_chg_pct")

        # Badges
        ext_badge = ""
        if post_p and post_c is not None:
            psgn = "▲" if post_c >= 0 else "▼"
            pcol = "#276749" if post_c >= 0 else "#c53030"
            ext_badge += f'''<span class="stag" style="background:{pcol}18;color:{pcol};font-weight:700;border:1px solid {pcol}40">🌙 After-Hours: {fmt_price(post_p)} {psgn}{abs(post_c):.2f}%</span>'''
        if pre_p and pre_c is not None:
            prsgn = "▲" if pre_c >= 0 else "▼"
            prcol = "#276749" if pre_c >= 0 else "#c53030"
            ext_badge += f'''<span class="stag" style="background:{prcol}18;color:{prcol};font-weight:700;border:1px solid {prcol}40">🌅 Pre-Market: {fmt_price(pre_p)} {prsgn}{abs(pre_c):.2f}%</span>'''

        # Analysis text
        ext_analysis = ""
        if post_p and post_c is not None:
            if abs(post_c) >= 1.0:
                move = "surged" if post_c > 0 else "dropped"
                strength = "sharply" if abs(post_c) > 3 else "moderately"
                ext_analysis += f"{sym} {move} {strength} in after-hours ({'+' if post_c>0 else ''}{post_c:.2f}%) reaching {fmt_price(post_p)}. "
            else:
                ext_analysis += f"{sym} traded flat after-hours ({'+' if post_c>0 else ''}{post_c:.2f}%). "
        if pre_p and pre_c is not None:
            if abs(pre_c) >= 0.5:
                move2   = "rising" if pre_c > 0 else "falling"
                signal  = "positive open signal" if pre_c > 0 else "pre-market selling pressure"
                ext_analysis += f"Pre-Market: {sym} {move2} {abs(pre_c):.2f}% at {fmt_price(pre_p)} — {signal}."
            else:
                ext_analysis += f"Pre-Market: quiet trading at {fmt_price(pre_p)}."

        news_html = "".join(f"<li>{n['title'][:115]}</li>" for n in news[:4])
        chg_col = pnl_color(chg_p)

        stock_cards += f"""
<div class="scard" style="border-top:3px solid #{col};direction:ltr">
  <div class="scard-top">
    <div class="scard-row">
      <div>
        <div class="scard-sym" style="color:#{col}">{sym}</div>
        <div class="scard-name">{s['name_en']}</div>
      </div>
      <div style="text-align:right">
        <div class="scard-price">{fmt_price(cur)}</div>
        <div style="font-family:DV;font-size:11px;color:{chg_col}">{arrow(chg_p)} {abs(chg_p):.2f}% &nbsp;|&nbsp; Vol: {vol}</div>
      </div>
    </div>
  </div>
  <div class="scard-meta">
    <span class="stag">{s['qty']} shares × {fmt_price(s['buy'])} entry</span>
    <span class="stag">H: {hi} | L: {lo}</span>
    <span class="stag-e">⚠ Earnings: {s['earn']}</span>
    <span class="{'stag-buy' if pnl>=0 else 'stag-loss'}">{arrow(pnl_p)} {abs(pnl_p):.1f}%</span>
  </div>
  {f'<div style="padding:6px 15px;background:#f0f9ff;border-bottom:1px solid #e0f0ff;display:flex;gap:8px;flex-wrap:wrap">' + ext_badge + '</div>' if ext_badge else ""}
  {f'<div style="padding:7px 15px;background:#fffdf0;border-bottom:1px solid #fef3c7;font-size:11px;color:#374151;line-height:1.6">' + ext_analysis + '</div>' if ext_analysis else ""}
  <div class="scard-news"><ul>{news_html if news_html else "<li>No news available</li>"}</ul></div>
  <div class="pnl-box">
    <div class="tot-item">
      <div class="pnl-lbl">Total Cost</div>
      <div class="pnl-val" style="color:#374151">{fmt_price(cost)}</div>
    </div>
    <div class="tot-item">
      <div class="pnl-lbl">Market Value</div>
      <div class="pnl-val" style="color:#0f2d5a">{fmt_price(val)}</div>
    </div>
    <div class="tot-item">
      <div class="pnl-lbl">P&L</div>
      <div class="pnl-val" style="color:{pnl_color(pnl)}">{'+' if pnl>=0 else ''}{fmt_price(pnl)}</div>
    </div>
  </div>
</div>"""

    # ── English Crypto Cards ───────────────────────────────────
    crypto_cards = ""
    cat_map = {"مدفوعات":"PAYMENTS","بنية تحتية":"INFRA","الطبقة 2":"LAYER2","ميم":"MEME","ألعاب":"GAMING"}
    cat_styles = {
        "PAYMENTS": "background:#dcfce7;color:#166534",
        "INFRA":    "background:#dbeafe;color:#1e40af",
        "LAYER2":   "background:#ede9fe;color:#6d28d9",
        "MEME":     "background:#fee2e2;color:#991b1b",
        "GAMING":   "background:#fef3c7;color:#92400e",
    }
    for c in port["crypto"]:
        sym  = c["sym"]
        p    = data["crypto"][sym].get("price", {})
        news = data["crypto"][sym].get("news", [])
        cur  = p.get("price", c["buy"])
        cost = c["qty"] * c["buy"]
        val  = c["qty"] * cur
        pnl  = val - cost
        pnl_p= (pnl / cost) * 100 if cost else 0
        col  = c["color"]
        cat_en = cat_map.get(c["cat"], c["cat"])
        cs   = cat_styles.get(cat_en, "")
        news_html2 = "".join(
            f'''<div style='font-size:10px;color:#4a5568;margin-bottom:3px;border-left:2px solid #{col};padding-left:6px'>{n["title"][:95]}</div>'''
            for n in news[:3])

        crypto_cards += f"""
<div class="ccard" style="border-top:3px solid #{col};direction:ltr">
  <div class="ccard-sym" style="color:#{col}">{sym}</div>
  <div style="font-size:9px;color:#718096">{c['name_en']}</div>
  <div class="ccard-price">{fmt_price(cur, sym)}</div>
  <div class="ccard-cat" style="{cs}">{cat_en}</div>
  <div style="margin-bottom:5px">
    <span style="font-size:10px;font-weight:700;color:{pnl_color(pnl_p)}">
      {arrow(pnl_p)} {abs(pnl_p):.1f}% &nbsp;|&nbsp; {'+' if pnl>=0 else ''}{fmt_price(pnl)}
    </span>
  </div>
  <div style="font-size:9px;color:#718096;margin-bottom:5px">
    Qty: <span style="font-family:DV">{c['qty']:,.4f}</span> × <span style="font-family:DV">{fmt_price(c['buy'],sym)}</span>
  </div>
  {news_html2}
</div>"""

    s_pnl = s_val - s_cost
    c_pnl = c_val - c_cost

    # Action table
    actions_en = {
        "MU":   ("HOLD · Do NOT add pre-Jun 24 earnings", "warn"),
        "NOW":  ("ACCUMULATE toward $100-105",             "pos"),
        "PLTR": ("HOLD · Accumulate below $120",           "pos"),
        "CBRS": ("HOLD · Monitor Form 4 daily",            "neg"),
        "XRP":  ("HOLD · Add small on weakness",           "pos"),
        "SOL":  ("HOLD · Strong fundamentals",             "hl"),
        "HBAR": ("HOLD · High conviction long-term",       "pos"),
        "SHIB": ("HOLD ONLY · No additions",               "neg"),
        "ADA":  ("HOLD · Wait Q4 mainnet",                 "hl"),
        "ARB":  ("HOLD · Last priority",                   "hl"),
        "DOT":  ("NEUTRAL HOLD",                           "hl"),
        "GALA": ("HOLD ONLY · Monitor pipeline",           "neg"),
    }
    action_rows = ""
    for s in port["stocks"]:
        sym = s["sym"]
        q2  = data["stocks"][sym].get("quote", {})
        cur2= q2.get("price", s["buy"])
        pp  = ((cur2 - s["buy"]) / s["buy"]) * 100
        act, css = actions_en.get(sym, ("HOLD", "hl"))
        action_rows += f'''<tr><td><strong style="color:#{s["color"]}">{sym}</strong></td><td style="font-family:DV">{fmt_price(cur2)}</td><td style="font-family:DV;color:{("#276749" if pp>=0 else "#c53030")}">{arrow(pp)}{abs(pp):.1f}%</td><td class="{css}">{act}</td></tr>'''
    for c in port["crypto"]:
        sym = c["sym"]
        p2  = data["crypto"][sym].get("price", {})
        cur2= p2.get("price", c["buy"])
        pp  = ((cur2 - c["buy"]) / c["buy"]) * 100
        act, css = actions_en.get(sym, ("HOLD", "hl"))
        action_rows += f'''<tr><td><strong style="color:#{c["color"]}">{sym}</strong></td><td style="font-family:DV">{fmt_price(cur2, sym)}</td><td style="font-family:DV;color:{("#276749" if pp>=0 else "#c53030")}">{arrow(pp)}{abs(pp):.1f}%</td><td class="{css}">{act}</td></tr>'''

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>{css}</style></head>
<body>
<!-- PAGE 1: STOCKS EN -->
<div class="page en">
<div class="hdr">
  <div>
    <div class="hdr-badge">Saif's Portfolio · {session_en} {icon} · Stocks</div>
    <div class="hdr-title">My Portfolio — Stocks</div>
    <div class="hdr-sub">MU · NOW · PLTR · CBRS</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:18px;font-weight:700;color:#fff">{date_str}</div>
    <div style="font-size:10px;color:rgba(255,255,255,.7);margin-top:3px">{time_gst}</div>
  </div>
</div>

<div class="total-row">
  <div class="tot-item"><div class="tot-val">{fmt_price(s_cost)}</div><div class="tot-lbl">Total Cost</div></div>
  <div class="tot-item"><div class="tot-val">{fmt_price(s_val)}</div><div class="tot-lbl">Market Value</div></div>
  <div class="tot-item"><div class="tot-val" style="color:{pnl_color(s_pnl)}">{'+' if s_pnl>=0 else ''}{fmt_price(s_pnl)}</div><div class="tot-lbl">P&L ($)</div></div>
  <div class="tot-item"><div class="tot-val" style="color:{pnl_color(s_pnl)}">{'+' if s_pnl>=0 else ''}{((s_val-s_cost)/s_cost*100):.1f}%</div><div class="tot-lbl">P&L (%)</div></div>
</div>

<div class="sec"><div class="dot"></div>📈 STOCKS — Performance, News & P&L</div>
<div class="g2">{stock_cards}</div>
<div class="footer">Saif's Portfolio · Stocks · {date_str} · For informational purposes only · Not financial advice</div>
</div>

<!-- PAGE 2: CRYPTO + ACTION EN -->
<div class="page en">
<div style="background:linear-gradient(135deg,#0f2d5a,#1d4ed8);border-radius:12px;padding:16px 24px;margin-bottom:16px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 4px 16px rgba(29,78,216,.22)">
  <div><div style="font-size:10px;color:rgba(255,255,255,.65);margin-bottom:3px">Portfolio · Crypto & Action Plan</div>
  <div style="font-size:19px;font-weight:700;color:#fff">My Crypto + Full Action Plan</div></div>
  <div style="font-size:10.5px;color:rgba(255,255,255,.75)">{date_str} · {time_gst}</div>
</div>

<div class="total-row">
  <div class="tot-item"><div class="tot-val">{fmt_price(c_cost)}</div><div class="tot-lbl">Crypto Cost</div></div>
  <div class="tot-item"><div class="tot-val">{fmt_price(c_val)}</div><div class="tot-lbl">Crypto Value</div></div>
  <div class="tot-item"><div class="tot-val" style="color:{pnl_color(c_pnl)}">{'+' if c_pnl>=0 else ''}{fmt_price(c_pnl)}</div><div class="tot-lbl">Crypto P&L</div></div>
  <div class="tot-item"><div class="tot-val" style="color:{pnl_color(t_pct)}">{'+' if t_pct>=0 else ''}{t_pct:.1f}%</div><div class="tot-lbl">Total Portfolio P&L</div></div>
</div>

<div class="sec"><div class="dot"></div>₿ CRYPTO — Prices & News</div>
<div class="g4">{crypto_cards}</div>

<div class="sec"><div class="dot"></div>⚡ ACTION PLAN — My Direct Recommendations</div>
<table class="tbl" style="direction:ltr">
<tr><th>Asset</th><th>Price</th><th>P&L %</th><th>Action</th></tr>
{action_rows}
</table>

<div class="bline">
  <h3>⚡ Bottom Line</h3>
  <p>Your portfolio is under macro pressure from three converging forces: AI valuation reset post-Broadcom, rate-hike fears from the strong jobs report, and oil pressure from the Iran/Hormuz crisis. <strong>None of this invalidates the structural thesis</strong> of your positions.<br><br>
  Top 3 priorities: (1) June 10 CPI — if cool, add to NOW near $100. (2) Watch CBRS Form 4 filings daily — lockup expiry is your #1 near-term risk. (3) Do nothing on MU until June 24 earnings — binary event.</p>
</div>
<div class="footer">Saif's Portfolio · Crypto & Action Plan · {date_str} · For informational purposes only · Not financial advice</div>
</div>
</body></html>"""

def build_market_ar(data, date_str, session="الصباحي", icon="🌅", time_gst="10:30 GST", am="", amb="", dv="", dvb=""):
    css = build_css(am, amb, dv, dvb)
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>{css}</style></head>
<body>
<!-- PAGE 1: MACRO + SECTORS -->
<div class="page ar">
<div class="hdr" style="flex-direction:row-reverse">
  <div style="text-align:right">
    <div class="hdr-badge">تحليل السوق اليومي · الجزء الأول</div>
    <div class="hdr-title">تحليل السوق العالمي والفرص</div>
    <div class="hdr-sub">الاقتصاد الكلي · الجيوسياسة · القطاعات · الكريبتو · السيناريوهات</div>
  </div>
  <div style="text-align:left">
    <div style="font-size:18px;font-weight:700;color:#fff">{date_str}</div>
    <div style="font-size:10px;color:rgba(255,255,255,.7);margin-top:3px">2:30 ظهرًا · بتوقيت الخليج</div>
  </div>
</div>

<div class="strip">
  <div class="sc" style="background:linear-gradient(135deg,#fff5f5,#ffe8e8)">
    <div class="sv neg">7,383</div><div class="sl">S&P 500 (−2.64%)</div>
  </div>
  <div class="sc" style="background:linear-gradient(135deg,#fff5f5,#ffe8e8)">
    <div class="sv neg">25,709</div><div class="sl">ناسداك (−4.18%)</div>
  </div>
  <div class="sc" style="background:linear-gradient(135deg,#fffdf0,#fef3c7)">
    <div class="sv warn">$97</div><div class="sl">برنت/برميل</div>
  </div>
  <div class="sc" style="background:linear-gradient(135deg,#fefce8,#fef9c3)">
    <div class="sv" style="color:#92400e;font-family:DV">$4,593</div><div class="sl">الذهب/أوقية</div>
  </div>
  <div class="sc" style="background:linear-gradient(135deg,#ebf8ff,#dde9f5)">
    <div class="sv hl">3.50%</div><div class="sl">الفائدة الفيدرالية</div>
  </div>
</div>

<div class="alert alert-ar a-r">
  <div class="a-icon">🔴</div>
  <div style="flex:1;text-align:right">
    <div class="a-title">موجة بيع حادة في أشباه الموصلات — أسوأ جلسة منذ مارس 2020</div>
    <div class="a-body">ناسداك −4.18% · SOX (أشباه الموصلات) أسوأ يوم منذ 2020 · تريليون دولار مُمحى في 48 ساعة. المحرك: إخفاق برودكوم + تقرير وظائف قوي (172K) يرفع مخاوف الفائدة + إيران تعلّق المحادثات وترفع النفط 6%.</div>
  </div>
</div>

<div class="sec sec-ar"><div class="dot"></div>🌍 المشهد الجيوسياسي والكلي</div>
<div class="g3">
  <div class="card" style="text-align:right">
    <div style="font-size:10px;color:#718096;margin-bottom:7px">🇺🇸🇮🇷 الصراع الأمريكي-الإيراني</div>
    <div style="font-size:11.5px;color:#2d3748;line-height:1.7">مضيق هرمز مغلق جزئيًا — 21% من نفط العالم. إيران علّقت المحادثات 1 يونيو. برنت يقفز 6% في جلسة واحدة.<br><br><strong style="color:#0f2d5a">تقييمي:</strong> 60% تسوية بحلول Q3. 40% تصعيد صيفي — سيناريو $200/برميل.</div>
  </div>
  <div class="card" style="text-align:right">
    <div style="font-size:10px;color:#718096;margin-bottom:7px">🇺🇸🇨🇳 حرب الرقائق والذكاء الاصطناعي</div>
    <div style="font-size:11.5px;color:#2d3748;line-height:1.7">الصين تمتلك الآن 41% من سوق رقائق AI محليًا (مقابل 10% في 2023). هواوي وكامبريكون يتقدمان بسرعة كبيرة.<br><br><strong style="color:#0f2d5a">تقييمي:</strong> الانفصال لا رجعة فيه. PLTR وNOW أكثر حمايةً.</div>
  </div>
  <div class="card" style="text-align:right">
    <div style="font-size:10px;color:#718096;margin-bottom:7px">🏦 الاحتياطي الفيدرالي</div>
    <div style="font-size:11.5px;color:#2d3748;line-height:1.7">الرئيس الجديد كيفن وورش (منذ 15 مايو). FOMC القادم: 16-17 يونيو. السوق يسعّر 98% ثبات.<br><br>⚡ <strong style="color:#c53030">CPI الأهم: 10 يونيو</strong><br>JP Morgan: 35% احتمال ركود.</div>
  </div>
</div>

<div class="sec sec-ar"><div class="dot"></div>📊 بطاقة تقييم القطاعات</div>
<table class="tbl" style="direction:rtl">
<tr><th style="text-align:right">القطاع</th><th style="text-align:right">الحالة</th><th style="text-align:right">توقعي</th><th style="text-align:right">الإشارة</th></tr>
<tr><td><strong>ذكاء اصطناعي / رقائق</strong></td><td class="neg">تصحيح عميق</td><td>الأطروحة سليمة — منطقة تراكم</td><td class="warn">انتظر · CPI أولاً</td></tr>
<tr><td><strong>برمجيات AI المؤسسية</strong></td><td class="neg">تحت ضغط</td><td>PLTR وNOW: فرصة على الانخفاض</td><td class="pos">تراكم انتقائي</td></tr>
<tr><td><strong>الدفاع والفضاء</strong></td><td class="pos">يتفوق</td><td>رياح خلفية هيكلية</td><td class="pos">صاعد</td></tr>
<tr><td><strong>الطاقة / النفط</strong></td><td class="pos">مرتفع</td><td>قريب: $85-100. الحل = تراجع حاد</td><td class="warn">محايد</td></tr>
<tr><td><strong>الذهب / المعادن</strong></td><td class="pos">قوي</td><td>سوق صاعدة هيكلية حتى 2027</td><td class="pos">صاعد</td></tr>
<tr><td><strong>الكريبتو (عام)</strong></td><td class="neg">ضغط هبوطي</td><td>BTC $60K خط الدفاع · CLARITY Act = المحفز</td><td class="warn">انتقائي</td></tr>
</table>

<div class="sec sec-ar"><div class="dot"></div>🎯 السيناريوهات — تقييمي الاحتمالي</div>
<div class="sc3">
  <div class="scn s-bull" style="text-align:right">
    <div class="sn-t">🟢 السيناريو الصاعد</div>
    <div class="prob">25%</div>
    <p>CPI بارد + اتفاق إيران + مرور CLARITY Act → تعافٍ متفجر في الرقائق والكريبتو. S&P 500 فوق 7,600. XRP +50%+.</p>
  </div>
  <div class="scn s-base" style="text-align:right">
    <div class="sn-t">🔵 السيناريو الأساسي</div>
    <div class="prob">50%</div>
    <p>التعثر والمضي → فيدرالي ثابت → إيران محتوى → سوق جانبية 7,000-7,600. تعافٍ جزئي بطيء.</p>
  </div>
  <div class="scn s-bear" style="text-align:right">
    <div class="sn-t">🔴 السيناريو الهابط</div>
    <div class="prob">25%</div>
    <p>CPI ساخن + تصعيد إيران + إشارة رفع وورش → ركود JP Morgan 35% → S&P 500 يختبر 6,500.</p>
  </div>
</div>

<div class="cal-g">
  <div class="cal hot"><div class="cal-d">الثلاثاء 10 يونيو</div><div class="cal-e">🔴 CPI مايو — الأهم</div></div>
  <div class="cal warm"><div class="cal-d">الخميس 12 يونيو</div><div class="cal-e">🚀 IPO سبيس إكس $75B</div></div>
  <div class="cal cool"><div class="cal-d">يونيو 2026</div><div class="cal-e">⚖️ تصويت CLARITY Act</div></div>
  <div class="cal cool"><div class="cal-d">16-17 يونيو</div><div class="cal-e">🏦 FOMC — أول وورش</div></div>
  <div class="cal hot"><div class="cal-d">الثلاثاء 24 يونيو</div><div class="cal-e">🔴 أرباح مايكرون MU</div></div>
</div>
<div class="footer">تحليل السوق اليومي · الجزء الأول · {date_str} · للأغراض المعلوماتية فقط · ليس نصيحة مالية</div>
</div>

<!-- PAGE 2: OPPORTUNITIES -->
<div class="page ar">
<div style="background:linear-gradient(135deg,#0f2d5a,#1d4ed8);border-radius:12px;padding:18px 26px;margin-bottom:18px;display:flex;justify-content:space-between;align-items:center;box-shadow:0 4px 16px rgba(29,78,216,.22)">
  <div style="text-align:right">
    <div style="font-size:10px;color:rgba(255,255,255,.65);margin-bottom:3px">تحليل السوق اليومي · الجزء الثاني</div>
    <div style="font-size:19px;font-weight:700;color:#fff">فرص الدخول الواعدة</div>
  </div>
  <div style="font-size:10.5px;color:rgba(255,255,255,.75)">{date_str}</div>
</div>

<div class="sec sec-ar"><div class="dot"></div>🌟 فرص في الأسهم خارج محفظتك</div>

<div class="opp">
  <div class="opp-t" style="text-align:right">🟢 فرصة 1: Bitcoin (BTC) — $60K هو سعر الدخول المؤسسي</div>
  <p style="text-align:right">BTC عند $60K اليوم هو نفس السعر الذي دفعه المؤسسيون الكبار في أبريل. Strategy أضافت 80,000 BTC في 2026 وحدها. ETF BlackRock يواصل التراكم اليومي. $60K هو خط الدفاع النفسي الحاسم — كسره يعني ضغطًا نحو $45-50K، لكن الاحتمال الأكثر ترجيحًا هو الصمود والارتداد.<br><br><strong>نقطة الدخول:</strong> $58-62K مرحليًا · <strong>الهدف:</strong> $80-90K عند تحسن الظروف الكلية · <strong>وقف الخسارة:</strong> $54K</p>
</div>

<div class="opp">
  <div class="opp-t" style="text-align:right">🟢 فرصة 2: Coinbase (COIN) — الرابح الأكبر من CLARITY Act</div>
  <p style="text-align:right">COIN هو المستفيد الأكبر من تحقق الوضوح التنظيمي في الولايات المتحدة. أحجام التداول على المنصة تتجاوز $1.5 تريليون سنويًا. قانون CLARITY Act يفتح الباب للأصول المؤسسية على نطاق غير مسبوق. السهم تراجع 30% من قمته — نقطة دخول مثيرة للاهتمام.<br><br><strong>نقطة الدخول:</strong> $180-200 · <strong>الهدف:</strong> $280+ خلال 12 شهرًا · <strong>المحفز:</strong> تصويت CLARITY Act يونيو 2026</p>
</div>

<div class="opp">
  <div class="opp-t" style="text-align:right">🟡 فرصة 3: AMD — بديل للتنويع في قطاع الرقائق</div>
  <p style="text-align:right">AMD هبطت 12.6% في نفس موجة البيع — لكن تقييمها أكثر معقولية من MU. MI300X GPU يكسب حصة سوقية في الذكاء الاصطناعي مقابل Nvidia. لا تعرض صيني مباشر — ميزة في بيئة حرب الرقائق الحالية. تنويع جيد لمن لديه تعرض كبير لمايكرون.<br><br><strong>نقطة الدخول:</strong> $100-115 · <strong>الهدف:</strong> $150+ · <strong>المخاطرة:</strong> متوسطة</p>
</div>

<div class="sec sec-ar"><div class="dot"></div>🌟 فرص في الكريبتو خارج محفظتك</div>

<div class="opp">
  <div class="opp-t" style="text-align:right">🟢 فرصة 4: Stellar (XLM) — موجة التوكنزيشن</div>
  <p style="text-align:right">XLM ارتفعت 40% بعد إعلان DTCC اختيارها لشبكتها لتوكنزيشن الأوراق المالية. هذا يثبت أن التمويل التقليدي بدأ يتبنى البلوكشين العامة. XLM تتشابه في حالة الاستخدام مع XRP لكن بتقييم أقل.<br><br><strong>نقطة الدخول:</strong> $0.08-0.10 · <strong>الهدف:</strong> $0.20-0.25 · <strong>المحفز:</strong> توسع شراكات DTCC والبنوك</p>
</div>

<div class="opp">
  <div class="opp-t" style="text-align:right">🟢 فرصة 5: Ethereum (ETH) — تحت $2,000 فرصة تاريخية</div>
  <p style="text-align:right">ETH تحت $2,000 هي مستوى شهدنا فيه تاريخيًا تراكمًا مؤسسيًا قويًا. ETH ETF يواصل التدفقات الإيجابية. Pectra upgrade محفز تقني قريب. معدل الحرق لا يزال يقلص العرض تدريجيًا.<br><br><strong>نقطة الدخول:</strong> $1,600-1,800 · <strong>الهدف:</strong> $2,800-3,200 · <strong>المحفز:</strong> تحسن الظروف الكلية + Pectra</p>
</div>

<div class="bline" style="text-align:right">
  <h3>⚡ خلاصتي — قراءة المشهد الكامل</h3>
  <p>نحن في منطقة ضغط مؤقت ناجمة عن ثلاثة عوامل متقاطعة: إعادة تسعير AI بعد برودكوم، مخاوف الفائدة من تقرير الوظائف، وضغط النفط من أزمة هرمز. <strong>لا شيء من هذا يلغي الأطروحة الهيكلية</strong> لمحفظتك أو لسوق الكريبتو بشكل عام.<br><br>
  أولوياتك هذا الأسبوع: (1) CPI 10 يونيو — إن جاء باردًا أضف على NOW. (2) راقب Form 4 لـ CBRS يوميًا. (3) لا تتحرك على MU حتى 24 يونيو. أما الفرص خارج محفظتك: BTC عند $60K وCOIN قبل CLARITY Act هما أفضل فرصتين قصيرتي المدى.</p>
</div>
<div class="footer">تحليل السوق اليومي · الجزء الثاني · {date_str} · للأغراض المعلوماتية فقط · ليس نصيحة مالية</div>
</div>
</body></html>"""

def build_market_en(data, date_str, session_en="Morning", icon="🌅", time_gst="10:30 GST", am="", amb="", dv="", dvb=""):
    css = build_css(am, amb, dv, dvb)
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>{css}</style></head>
<body>
<div class="page en">
<div class="hdr">
  <div>
    <div class="hdr-badge">Daily Market Analysis · Part 1</div>
    <div class="hdr-title">Global Market Intelligence & Opportunities</div>
    <div class="hdr-sub">Macro · Geopolitics · Sectors · Crypto · Scenarios · Entry Opportunities</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:18px;font-weight:700;color:#fff">{date_str}</div>
    <div style="font-size:10px;color:rgba(255,255,255,.7);margin-top:3px">{time_gst} · {session_en}</div>
  </div>
</div>

<div class="strip">
  <div class="sc" style="background:linear-gradient(135deg,#fff5f5,#ffe8e8)"><div class="sv neg">7,383</div><div class="sl">S&P 500 (−2.64%)</div></div>
  <div class="sc" style="background:linear-gradient(135deg,#fff5f5,#ffe8e8)"><div class="sv neg">25,709</div><div class="sl">Nasdaq (−4.18%)</div></div>
  <div class="sc" style="background:linear-gradient(135deg,#fffdf0,#fef3c7)"><div class="sv warn">$97</div><div class="sl">Brent/bbl</div></div>
  <div class="sc" style="background:linear-gradient(135deg,#fefce8,#fef9c3)"><div class="sv" style="color:#92400e;font-family:DV">$4,593</div><div class="sl">Gold/oz</div></div>
  <div class="sc" style="background:linear-gradient(135deg,#ebf8ff,#dde9f5)"><div class="sv hl">3.50%</div><div class="sl">Fed Rate</div></div>
</div>

<div class="alert a-r">
  <div class="a-icon">🔴</div>
  <div style="flex:1">
    <div class="a-title">Semiconductor Selloff — Worst Session Since March 2020</div>
    <div class="a-body">Nasdaq −4.18% · SOX (Philadelphia Semiconductor Index) worst day since March 2020 · $1T erased in 48 hours. Triple catalyst: Broadcom miss + strong May jobs (172K) reviving rate-hike fears + Iran suspends talks, oil spikes 6%.</div>
  </div>
</div>

<div class="sec"><div class="dot"></div>🌍 Geopolitical & Macro Landscape</div>
<div class="g3">
  <div class="card">
    <div style="font-size:10px;color:#718096;margin-bottom:7px">🇺🇸🇮🇷 US-Iran Conflict</div>
    <div style="font-size:11.5px;color:#2d3748;line-height:1.7">Strait of Hormuz partially blocked — 21% of world oil. Iran suspended talks June 1. Brent spiked 6% in one session.<br><br><strong style="color:#0f2d5a">My view:</strong> 60% partial resolution by Q3. 40% summer escalation — $200/barrel scenario.</div>
  </div>
  <div class="card">
    <div style="font-size:10px;color:#718096;margin-bottom:7px">🇺🇸🇨🇳 AI / Chip War</div>
    <div style="font-size:11.5px;color:#2d3748;line-height:1.7">China now holds 41% of its AI chip market domestically (vs 10% in 2023). Huawei advancing rapidly.<br><br><strong style="color:#0f2d5a">My view:</strong> Decoupling is permanent. PLTR and NOW relatively insulated with no China exposure.</div>
  </div>
  <div class="card">
    <div style="font-size:10px;color:#718096;margin-bottom:7px">🏦 Federal Reserve</div>
    <div style="font-size:11.5px;color:#2d3748;line-height:1.7">New Chair Kevin Warsh (since May 15). Next FOMC: June 16-17. Market pricing 98% no change.<br><br>⚡ <strong style="color:#c53030">Critical CPI: June 10</strong><br>JP Morgan recession probability: 35%.</div>
  </div>
</div>

<div class="sec"><div class="dot"></div>📊 Sector Scorecard</div>
<table class="tbl">
<tr><th>Sector</th><th>Status</th><th>My Outlook</th><th>Signal</th></tr>
<tr><td><strong>AI / Semiconductors</strong></td><td class="neg">Deep correction</td><td>Thesis intact — accumulation zone</td><td class="warn">Wait · CPI first</td></tr>
<tr><td><strong>Enterprise AI Software</strong></td><td class="neg">Under pressure</td><td>PLTR, NOW: dip = opportunity</td><td class="pos">Selective accumulate</td></tr>
<tr><td><strong>Defense & Aerospace</strong></td><td class="pos">Outperforming</td><td>Structural tailwind from Iran conflict</td><td class="pos">Bullish</td></tr>
<tr><td><strong>Energy / Oil</strong></td><td class="pos">Elevated</td><td>Near-term $85-100. Resolution = sharp drop</td><td class="warn">Neutral</td></tr>
<tr><td><strong>Gold / Metals</strong></td><td class="pos">Strong</td><td>Structural bull market through 2027</td><td class="pos">Bullish</td></tr>
<tr><td><strong>Crypto (broad)</strong></td><td class="neg">Bear pressure</td><td>BTC $60K defense. CLARITY Act = catalyst</td><td class="warn">Selective by asset</td></tr>
</table>

<div class="sec"><div class="dot"></div>🎯 Scenario Probabilities</div>
<div class="sc3">
  <div class="scn s-bull">
    <div class="sn-t">🟢 Bull Scenario</div><div class="prob">25%</div>
    <p>Cool CPI + Iran deal + CLARITY Act → explosive recovery in semis and crypto. S&P 500 above 7,600. XRP +50%+.</p>
  </div>
  <div class="scn s-base">
    <div class="sn-t">🔵 Base Scenario</div><div class="prob">50%</div>
    <p>Muddle-through → Fed on hold → Iran contained → range-bound 7,000-7,600. Slow partial recovery.</p>
  </div>
  <div class="scn s-bear">
    <div class="sn-t">🔴 Bear Scenario</div><div class="prob">25%</div>
    <p>Hot CPI + Iran escalation + Warsh hike signal → JP Morgan's 35% recession materializes → S&P 500 tests 6,500.</p>
  </div>
</div>

<div class="sec"><div class="dot"></div>🌟 Investment Opportunities</div>
<div class="opp">
  <div class="opp-t">🟢 Opportunity 1: Bitcoin (BTC) — $60K = Institutional Entry Price</div>
  <p>BTC at $60K today is the same level institutions paid in April. Strategy added 80,000 BTC in 2026 alone. BlackRock ETF continues daily accumulation. $60K is the critical psychological support — the most likely scenario is a hold and bounce.<br><br><strong>Entry:</strong> $58-62K in tranches · <strong>Target:</strong> $80-90K on macro improvement · <strong>Stop:</strong> $54K</p>
</div>
<div class="opp">
  <div class="opp-t">🟢 Opportunity 2: Coinbase (COIN) — CLARITY Act Proxy Trade</div>
  <p>COIN is the single largest beneficiary of US regulatory clarity. Platform volume exceeds $1.5T annually. CLARITY Act unlocks institutional asset management on-chain at unprecedented scale. Stock down 30% from peak.<br><br><strong>Entry:</strong> $180-200 · <strong>Target:</strong> $280+ (12 months) · <strong>Catalyst:</strong> CLARITY Act vote June 2026</p>
</div>
<div class="opp">
  <div class="opp-t">🟡 Opportunity 3: AMD — Better-Valued Chip Diversification</div>
  <p>AMD fell 12.6% in the same selloff but trades at a more reasonable valuation than MU. MI300X GPU gaining AI market share. No direct China revenue exposure — key advantage in the chip war environment.<br><br><strong>Entry:</strong> $100-115 · <strong>Target:</strong> $150+ · <strong>Risk:</strong> Medium</p>
</div>
<div class="opp">
  <div class="opp-t">🟢 Opportunity 4: Stellar (XLM) — Tokenization Wave</div>
  <p>XLM surged 40% after DTCC chose its network for tokenized securities — proof that traditional finance is beginning to adopt public blockchains. XLM has a similar use case to XRP but lower valuation.<br><br><strong>Entry:</strong> $0.08-0.10 · <strong>Target:</strong> $0.20-0.25 · <strong>Catalyst:</strong> DTCC + bank partnerships</p>
</div>

<div class="bline">
  <h3>⚡ Bottom Line — My Complete Assessment</h3>
  <p>We are in temporary pressure driven by three converging forces: AI valuation reset post-Broadcom, rate-hike fears from the jobs report, and oil pressure from the Hormuz crisis. <strong>None of this invalidates the structural thesis</strong> of your portfolio or crypto broadly.<br><br>
  This week's priorities: (1) June 10 CPI — if cool, add to NOW. (2) Watch CBRS Form 4 daily. (3) Do nothing on MU until June 24. For opportunities outside your portfolio: BTC at $60K and COIN pre-CLARITY Act are the two best near-term setups.</p>
</div>

<div class="cal-g">
  <div class="cal hot"><div class="cal-d">Tue Jun 10</div><div class="cal-e">🔴 May CPI</div></div>
  <div class="cal warm"><div class="cal-d">Thu Jun 12</div><div class="cal-e">🚀 SpaceX IPO $75B</div></div>
  <div class="cal cool"><div class="cal-d">~Jun 2026</div><div class="cal-e">⚖️ CLARITY Act</div></div>
  <div class="cal cool"><div class="cal-d">Jun 16-17</div><div class="cal-e">🏦 FOMC — Warsh</div></div>
  <div class="cal hot"><div class="cal-d">Tue Jun 24</div><div class="cal-e">🔴 MU Earnings</div></div>
</div>
<div class="footer">Daily Market Analysis · {date_str} · For informational purposes only · Not financial advice · Powered by Claude + Alpha Vantage</div>
</div>
</body></html>"""

# ── BUILD PDFs ────────────────────────────────────────────────
def build_pdf(html, out_path):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        pg.set_content(html, wait_until='networkidle')
        pg.wait_for_timeout(3000)
        pg.pdf(path=out_path, width='1240px', print_background=True,
               margin={"top":"0","bottom":"0","left":"0","right":"0"})
        browser.close()
    kb = os.path.getsize(out_path) // 1024
    print(f"  ✅ {os.path.basename(out_path)} ({kb} KB)")

def build_all_pdfs(data, date_str, session="الصباحي", session_en="Morning", icon="🌅", time_gst="10:30 GST"):
    print("\n🎨 Building PDFs...")
    am  = b64f(f"{FONT_DIR}/Amiri-Regular.ttf")
    amb = b64f(f"{FONT_DIR}/Amiri-Bold.ttf")
    dv  = b64f(f"{FONT_DIR}/DejaVuSans.ttf")
    dvb = b64f(f"{FONT_DIR}/DejaVuSans-Bold.ttf")
    out = os.getcwd()
    ds  = date_str.replace(",","").replace(" ","_")
    pdfs = {}
    configs = [
        ("portfolio_ar",  build_portfolio_ar(data, date_str, session, icon, time_gst, am, amb, dv, dvb), f"{out}/1_portfolio_ar_{ds}.pdf"),
        ("portfolio_en",  build_portfolio_en(data, date_str, session_en, icon, time_gst, am, amb, dv, dvb), f"{out}/2_portfolio_en_{ds}.pdf"),
        ("market_ar",     build_market_ar(data, date_str, session, icon, time_gst, am, amb, dv, dvb),    f"{out}/3_market_ar_{ds}.pdf"),
        ("market_en",     build_market_en(data, date_str, session_en, icon, time_gst, am, amb, dv, dvb), f"{out}/4_market_en_{ds}.pdf"),
    ]
    for key, html, path in configs:
        build_pdf(html, path)
        pdfs[key] = path
    return pdfs

# ── UPLOAD & EMAIL ────────────────────────────────────────────
def upload_pdf(local_path, gh_name):
    with open(local_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    H = {"Authorization": f"token {GITHUB_PAT}",
         "Accept": "application/vnd.github.v3+json",
         "Content-Type": "application/json"}
    api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/reports/{gh_name}"
    chk = requests.get(api, headers=H)
    sha = chk.json().get("sha") if chk.status_code == 200 else None
    up  = {"message": f"Update {gh_name}", "content": b64, "branch": "main"}
    if sha: up["sha"] = sha
    r = requests.put(api, headers=H, json=up)
    if r.status_code in (200, 201):
        url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/reports/{gh_name}"
        print(f"  ✅ Uploaded: {gh_name}")
        return url
    print(f"  ⚠️ Upload failed: {r.status_code}")
    return ""

def send_email(subject, body):
    H = {"Authorization": f"token {GITHUB_PAT}",
         "Accept": "application/vnd.github.v3+json",
         "Content-Type": "application/json"}
    payload = {"event_type": "send-email", "client_payload": {
        "from": EMAIL_FROM, "to": EMAIL_TO,
        "subject": subject, "text": body
    }}
    r = requests.post(
        f"https://api.github.com/repos/{GITHUB_REPO}/dispatches",
        headers=H, json=payload)
    if r.status_code == 204:
        print("  ✅ Email dispatched!")
    else:
        print(f"  ⚠️ Email failed: {r.status_code}")

def send_briefing(pdfs, data, date_str, session="الصباحي", session_en="Morning", icon="🌅", time_gst="10:30 GST", greeting="صباح الخير"):
    print("\n📧 Uploading and sending email...")
    time.sleep(2)
    urls = {}
    for key, path in pdfs.items():
        name = os.path.basename(path)
        url  = upload_pdf(path, name)
        if url: urls[key] = url
        time.sleep(1)
    time.sleep(4)

    # Build quick summary for email body
    lines_s, lines_c = [], []
    t_cost = t_val = 0
    for s in PORTFOLIO["stocks"]:
        q = data["stocks"][s["sym"]].get("quote", {})
        cur = q.get("price", s["buy"])
        val = s["qty"] * cur
        cost= s["qty"] * s["buy"]
        pnl = ((val-cost)/cost)*100
        t_cost += cost; t_val += val
        lines_s.append(f"  {s['sym']:5} {fmt_price(cur):>10}  {'+' if pnl>=0 else ''}{pnl:.1f}%")
    for c in PORTFOLIO["crypto"]:
        p = data["crypto"][c["sym"]].get("price", {})
        cur = p.get("price", c["buy"])
        val = c["qty"] * cur
        cost= c["qty"] * c["buy"]
        pnl = ((val-cost)/cost)*100
        t_cost += cost; t_val += val
        lines_c.append(f"  {c['sym']:5} {fmt_price(cur,c['sym']):>14}  {'+' if pnl>=0 else ''}{pnl:.1f}%")

    t_pnl = t_val - t_cost
    t_pct = (t_pnl/t_cost)*100 if t_cost else 0

    body = f"""{greeting} سيف {icon}

تقاريرك {session}ية جاهزة — {date_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 الأسهم:
{chr(10).join(lines_s)}

₿ الكريبتو:
{chr(10).join(lines_c)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💼 إجمالي المحفظة:
   الاستثمار: {fmt_price(t_cost)}
   القيمة الحالية: {fmt_price(t_val)}
   الربح/الخسارة: {'+' if t_pnl>=0 else ''}{fmt_price(t_pnl)} ({'+' if t_pct>=0 else ''}{t_pct:.1f}%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📥 التقارير الكاملة (4 ملفات PDF):

🇸🇦 محفظتك الشخصية (عربي):
{urls.get('portfolio_ar', 'غير متاح')}

🇬🇧 Your Portfolio (English):
{urls.get('portfolio_en', 'N/A')}

🇸🇦 تحليل السوق + فرص الدخول (عربي):
{urls.get('market_ar', 'غير متاح')}

🇬🇧 Market Analysis + Opportunities (English):
{urls.get('market_en', 'N/A')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 Claude · Alpha Vantage MCP
⚠️ للأغراض المعلوماتية فقط · ليس نصيحة مالية
"""
    send_email(f"📊 تقريرك {session} {icon} | {date_str} | {time_gst}", body)

# ── MAIN ──────────────────────────────────────────────────────
def run():
    now      = datetime.datetime.utcnow()
    gst_hour = (now.hour + 4) % 24
    gst_min  = now.minute
    time_gst = f"{gst_hour:02d}:{gst_min:02d} GST"

    if gst_hour < 17:
        session    = "الصباحي"
        session_en = "Morning"
        greeting   = "صباح الخير"
        icon       = "🌅"
    else:
        session    = "المسائي"
        session_en = "Evening"
        greeting   = "مساء الخير"
        icon       = "🌙"

    date_str = now.strftime("%A, %B %d, %Y")

    print(f"\n{'='*50}")
    print(f"  {session_en.upper()} BRIEFING — {date_str} {time_gst}")
    print(f"{'='*50}")

    data = collect_data()
    pdfs = build_all_pdfs(data, date_str, session, session_en, icon, time_gst)
    send_briefing(pdfs, data, date_str, session, session_en, icon, time_gst, greeting)
    print(f"\n✅ Done — {date_str} {time_gst}\n")

if __name__ == "__main__":
    run()
