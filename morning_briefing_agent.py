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
        {"sym":"MU",   "name":"مايكرون تكنولوجي",    "name_en":"Micron Technology",    "qty":34,             "buy":1031.90, "color":"E53E3E", "earn":"24 يونيو 2026"},
        {"sym":"NOW",  "name":"سيرفس ناو",            "name_en":"ServiceNow",           "qty":112,            "buy":133.01,  "color":"059669", "earn":"29 يوليو 2026"},
        {"sym":"PLTR", "name":"بالانتير",             "name_en":"Palantir Technologies","qty":62,             "buy":157.58,  "color":"7C3AED", "earn":"10 أغسطس 2026"},
    ],
    "crypto": [
        {"sym":"XRP",  "name":"ريبل",        "name_en":"Ripple",     "qty":1091.9141638,   "buy":0.94640265, "color":"0284C7", "cat":"مدفوعات"},
        {"sym":"SOL",  "name":"سولانا",      "name_en":"Solana",     "qty":18.67559317,    "buy":82.35,      "color":"9945FF", "cat":"بنية تحتية"},
        {"sym":"HBAR", "name":"هيدرا",       "name_en":"Hedera",     "qty":6888.17073321,  "buy":0.27098023, "color":"0D9488", "cat":"بنية تحتية"},
    ]
}

# ════════════════════════════════════════════════════════════
# LIVE WINDOW ENGINE  — per-report time-window data + real signals
# Makes the two reports genuinely different: each reads ONLY the
# price action inside its own time window and computes signals live.
# ════════════════════════════════════════════════════════════
import datetime as _dt

UTC = _dt.timezone.utc
GST = _dt.timezone(_dt.timedelta(hours=4))

# yfinance symbol map for crypto (intraday + indicators)
CRYPTO_YF = {
    "XRP":"XRP-USD","SOL":"SOL-USD","HBAR":"HBAR-USD","SHIB":"SHIB-USD",
    "ADA":"ADA-USD","ARB":"ARB-USD","DOT":"DOT-USD","GALA":"GALA-USD",
    "BTC":"BTC-USD","ETH":"ETH-USD","XLM":"XLM-USD",
}

def window_bounds(now_utc, session):
    """Time window each report analyzes (GST = UTC+4):
       Evening (run ~9 PM GST): 2:30 PM -> 9 PM GST  = today 10:30 -> now UTC
       Morning (run ~2:30 PM GST): prev 9 PM -> 2:30 PM GST = prev 17:00 -> now UTC
    """
    d = now_utc.date()
    if session == "evening":
        start = _dt.datetime(d.year, d.month, d.day, 10, 30, tzinfo=UTC)
        la = "الفترة المُحلَّلة: من 2:30 ظهرًا إلى 9 مساءً (جلسة اليوم الحية)"
        le = "Window analyzed: 2:30 PM → 9:00 PM GST (today's live session)"
    else:
        prev = now_utc - _dt.timedelta(days=1)
        start = _dt.datetime(prev.year, prev.month, prev.day, 17, 0, tzinfo=UTC)
        la = "الفترة المُحلَّلة: من 9 مساء أمس ← بعد الإغلاق ← ما قبل الافتتاح (حتى 2:30 ظهرًا)"
        le = "Window analyzed: 9 PM yesterday → after-hours → pre-market (until 2:30 PM GST)"
    end = now_utc
    if start >= end:
        start = end - _dt.timedelta(hours=6)
    return start, end, la, le

def _to_utc(df):
    try:
        idx = df.index
        df.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    except Exception:
        pass
    return df

def fetch_window(symbol, start_utc, end_utc):
    """5-min bars (incl pre/post) sliced to the report window only."""
    out = {"ok":False,"open":None,"last":None,"high":None,"low":None,
           "chg":0.0,"chg_pct":0.0,"vol":0,"bars":0}
    try:
        import yfinance as yf
        df = yf.Ticker(symbol).history(period="5d", interval="5m", prepost=True)
        if df is None or df.empty:
            return out
        df = _to_utc(df)
        win = df[(df.index >= start_utc) & (df.index <= end_utc)]
        if win.empty:
            win = df.tail(72)               # safety: last ~6h
        o = float(win["Open"].iloc[0]); l = float(win["Close"].iloc[-1])
        out.update({"ok":True,"open":round(o,4),"last":round(l,4),
                    "high":round(float(win["High"].max()),4),
                    "low":round(float(win["Low"].min()),4),
                    "chg":round(l-o,4),
                    "chg_pct":round((l-o)/o*100,2) if o else 0.0,
                    "vol":int(win["Volume"].sum()),"bars":int(len(win))})
    except Exception as e:
        print(f"  ⚠️ window {symbol}: {e}")
    return out

def fetch_indicators(symbol):
    """Daily-bar technicals: RSI(14), SMA20/50, ATR(14), trend."""
    out = {"rsi":None,"sma20":None,"sma50":None,"atr":None,"price":None,"trend":"neutral"}
    try:
        import yfinance as yf
        df = yf.Ticker(symbol).history(period="6mo", interval="1d")
        if df is None or len(df) < 30:
            return out
        c, h, lo = df["Close"], df["High"], df["Low"]
        delta = c.diff()
        up = delta.clip(lower=0).rolling(14).mean()
        dn = (-delta.clip(upper=0)).rolling(14).mean()
        rs = up / dn.replace(0, 1e-9)
        rsi = 100 - 100/(1+rs)
        prev_c = c.shift()
        tr = (h-lo).combine((h-prev_c).abs(), max).combine((lo-prev_c).abs(), max)
        atr = tr.rolling(14).mean()
        price = float(c.iloc[-1])
        sma20 = float(c.rolling(20).mean().iloc[-1])
        sma50 = float(c.rolling(50).mean().iloc[-1])
        out.update({"rsi":round(float(rsi.iloc[-1]),1),"sma20":round(sma20,4),
                    "sma50":round(sma50,4),"atr":round(float(atr.iloc[-1]),4),
                    "price":round(price,4)})
        if price > sma20 > sma50:   out["trend"] = "up"
        elif price < sma20 < sma50: out["trend"] = "down"
    except Exception as e:
        print(f"  ⚠️ indicators {symbol}: {e}")
    return out

def recommend(sym, entry, price, win, ind, lang="ar"):
    """Real BUY/SELL/HOLD with entry/target/stop/reason from live numbers."""
    rsi   = ind.get("rsi")
    trend = ind.get("trend","neutral")
    atr   = ind.get("atr") or (price*0.04 if price else 0)
    sma50 = ind.get("sma50")
    wpct  = (win or {}).get("chg_pct", 0)
    pnl   = ((price-entry)/entry*100) if entry else 0

    score = 0; drivers = []
    if rsi is not None:
        if rsi < 30:   score += 2; drivers.append(("RSI %.0f تشبّع بيعي"%rsi, "RSI %.0f oversold"%rsi))
        elif rsi < 45: score += 1; drivers.append(("RSI %.0f منخفض"%rsi, "RSI %.0f soft"%rsi))
        elif rsi > 70: score -= 2; drivers.append(("RSI %.0f تشبّع شرائي"%rsi, "RSI %.0f overbought"%rsi))
        elif rsi > 58: score -= 1; drivers.append(("RSI %.0f مرتفع"%rsi, "RSI %.0f elevated"%rsi))
    if trend == "up":   score += 1; drivers.append(("اتجاه صاعد فوق المتوسطات","uptrend above MAs"))
    elif trend == "down": score -= 1; drivers.append(("اتجاه هابط تحت المتوسطات","downtrend below MAs"))
    if wpct >= 1.5:   score += 1; drivers.append(("زخم +%.1f%% في الفترة"%wpct, "+%.1f%% window momentum"%wpct))
    elif wpct <= -1.5: score -= 1; drivers.append(("ضعف %.1f%% في الفترة"%wpct, "%.1f%% window weakness"%wpct))
    if pnl <= -20: score += 1; drivers.append(("خصم %.0f%% عن دخولك"%pnl, "%.0f%% below your entry"%pnl))
    if pnl >= 60:  score -= 1; drivers.append(("ربح +%.0f%% — جني محتمل"%pnl, "+%.0f%% gain — trim candidate"%pnl))

    if   score >= 3: act_ar, act_en, css = "شراء قوي", "STRONG BUY", "pos"
    elif score == 2: act_ar, act_en, css = "شراء / تراكم", "BUY / Accumulate", "pos"
    elif score in (0,1): act_ar, act_en, css = "انتظار · احتفظ", "HOLD", "hl"
    elif score == -1: act_ar, act_en, css = "تخفيف", "TRIM", "warn"
    else: act_ar, act_en, css = "بيع · خروج", "REDUCE / SELL", "neg"

    p = price or 0
    if score >= 2:
        e_lo, e_hi = p-0.4*atr, p
        target = max((win or {}).get("high", p) or p, p+2.2*atr)
        stop   = min(sma50 if sma50 else p-1.6*atr, p-1.6*atr)
    elif score <= -1:
        e_lo, e_hi = p, p+0.4*atr
        target = p+1.4*atr; stop = p-1.4*atr
    else:
        e_lo, e_hi = p-0.5*atr, p+0.2*atr
        target = p+1.8*atr; stop = p-1.5*atr

    dr_ar = "، ".join(d[0] for d in drivers[:3]) or "إشارات محايدة"
    dr_en = ", ".join(d[1] for d in drivers[:3]) or "neutral signals"
    return {"action": act_ar if lang=="ar" else act_en,
            "action_ar":act_ar, "action_en":act_en, "css":css, "score":score,
            "entry_lo":round(e_lo,6),"entry_hi":round(e_hi,6),
            "target":round(target,6),"stop":round(max(stop,0),6),
            "reason": dr_ar if lang=="ar" else dr_en,
            "reason_ar":dr_ar,"reason_en":dr_en}

def fetch_market_snapshot(start_utc, end_utc):
    """Live index/commodity snapshot with WINDOW-specific change."""
    syms = {"sp":"^GSPC","ndx":"^IXIC","brent":"BZ=F","gold":"GC=F","btc":"BTC-USD"}
    snap = {}
    for k, s in syms.items():
        w = fetch_window(s, start_utc, end_utc)
        snap[k] = {"val": w.get("last"), "pct": w.get("chg_pct", 0), "ok": w.get("ok")}
        time.sleep(0.2)
    return snap

def ai_narrate(prompt, max_tokens=900):
    """Optional AI narrative. Provider via env AI_PROVIDER + AI_KEY.
       Returns None on any failure -> caller uses the computational text."""
    prov = os.environ.get("AI_PROVIDER","").lower().strip()
    key  = os.environ.get("AI_KEY","").strip()
    if not prov or not key:
        return None
    try:
        if prov == "anthropic":
            r = requests.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key":key,"anthropic-version":"2023-06-01","content-type":"application/json"},
                json={"model":os.environ.get("AI_MODEL","claude-3-5-haiku-20241022"),
                      "max_tokens":max_tokens,"messages":[{"role":"user","content":prompt}]}, timeout=45)
            if r.status_code==200: return r.json()["content"][0]["text"].strip()
            print("  ⚠️ AI anthropic", r.status_code, r.text[:160])
        elif prov == "gemini":
            m = os.environ.get("AI_MODEL","gemini-1.5-flash")
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}",
                json={"contents":[{"parts":[{"text":prompt}]}]}, timeout=45)
            if r.status_code==200: return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            print("  ⚠️ AI gemini", r.status_code, r.text[:160])
        elif prov == "openai":
            r = requests.post("https://api.openai.com/v1/chat/completions",
                headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
                json={"model":os.environ.get("AI_MODEL","gpt-4o-mini"),
                      "max_tokens":max_tokens,"messages":[{"role":"user","content":prompt}]}, timeout=45)
            if r.status_code==200: return r.json()["choices"][0]["message"]["content"].strip()
            print("  ⚠️ AI openai", r.status_code, r.text[:160])
    except Exception as e:
        print("  ⚠️ AI error", e)
    return None

# ── LIVE MARKET HTML HELPERS ──────────────────────────────────
def _idx_cell(val, pct, label, fmt="{:,.0f}"):
    if val is None:
        vtxt = "N/A"; col = "#718096"; bg = "#f1f5f9"
    else:
        vtxt = fmt.format(val)
        col = "#c53030" if pct < 0 else "#276749"
        bg = "linear-gradient(135deg,#fff5f5,#ffe8e8)" if pct < 0 else "linear-gradient(135deg,#f0fff4,#e6ffed)"
    sgn = "▼" if pct < 0 else "▲"
    return (f'<div class="sc" style="background:{bg}">'
            f'<div class="sv" style="color:{col};font-family:DV">{vtxt}</div>'
            f'<div class="sl">{label} ({sgn}{abs(pct):.2f}%)</div></div>')

def live_strip_html(snap):
    snap = snap or {}
    g = lambda k: snap.get(k, {"val": None, "pct": 0})
    sp, ndx, br, gd, bt = g("sp"), g("ndx"), g("brent"), g("gold"), g("btc")
    return ('<div class="strip">'
            + _idx_cell(sp["val"], sp["pct"], "S&P 500")
            + _idx_cell(ndx["val"], ndx["pct"], "Nasdaq")
            + _idx_cell(br["val"], br["pct"], "Brent/bbl", "${:,.1f}")
            + _idx_cell(gd["val"], gd["pct"], "Gold/oz", "${:,.0f}")
            + _idx_cell(bt["val"], bt["pct"], "BTC", "${:,.0f}")
            + '</div>')

def dynamic_headline(snap, lang="ar"):
    ndx = (snap or {}).get("ndx", {"pct": 0})
    p = ndx.get("pct", 0)
    if p <= -1.5:
        return ("🔴", "a-r",
                ("موجة بيع في الفترة" if lang=="ar" else "Risk-off this window"),
                (f"ناسداك {p:.2f}% خلال الفترة — ضغط هبوطي واضح على التقنية. تحوّط ومتابعة المستويات."
                 if lang=="ar" else
                 f"Nasdaq {p:.2f}% this window — clear tech pressure. Risk-managed, watch levels."))
    if p >= 1.5:
        return ("🟢", "a-b",
                ("زخم صاعد في الفترة" if lang=="ar" else "Risk-on this window"),
                (f"ناسداك +{p:.2f}% خلال الفترة — شهية مخاطرة إيجابية تدعم الأصول النامية."
                 if lang=="ar" else
                 f"Nasdaq +{p:.2f}% this window — positive risk appetite supports growth assets."))
    return ("🟡", "a-a",
            ("تداول متباين في الفترة" if lang=="ar" else "Mixed / range-bound window"),
            (f"ناسداك {p:+.2f}% خلال الفترة — حركة محدودة. انتظار محفزات أوضح."
             if lang=="ar" else
             f"Nasdaq {p:+.2f}% this window — limited move. Awaiting clearer catalysts."))

def opp_levels(w):
    """Compute live entry/target/stop for a watch asset from its window bars."""
    p = (w or {}).get("last")
    if not p:
        return None
    hi = (w or {}).get("high") or p
    lo = (w or {}).get("low") or p
    rng = max(hi - lo, p * 0.03)
    return {"price": p,
            "entry_lo": round(p - 0.4 * rng, 4), "entry_hi": round(p, 4),
            "target": round(max(hi, p + 1.6 * rng), 4),
            "stop": round(max(lo - 0.3 * rng, p * 0.90), 4),
            "pct": (w or {}).get("chg_pct", 0)}

def opp_blocks_html(data, lang="ar"):
    names = {
        "BTC-USD": ("بيتكوين (BTC)", "Bitcoin (BTC)"),
        "COIN":    ("كوينبيس (COIN)", "Coinbase (COIN)"),
        "AMD":     ("AMD — رقائق", "AMD — chips"),
        "XLM-USD": ("ستيلر (XLM)", "Stellar (XLM)"),
        "ETH-USD": ("إيثيريوم (ETH)", "Ethereum (ETH)"),
    }
    ow = data.get("opp_win", {})
    out = ""
    for sym, (nar, nen) in names.items():
        lv = opp_levels(ow.get(sym))
        if not lv:
            continue
        nm = nar if lang == "ar" else nen
        pct = lv["pct"]; pcol = "#c53030" if pct < 0 else "#276749"
        psgn = "▼" if pct < 0 else "▲"
        align = "right" if lang == "ar" else "left"
        if lang == "ar":
            body = (f'السعر الحالي <span style="font-family:DV">{fmt_price(lv["price"],sym)}</span> '
                    f'(<span style="color:{pcol}">{psgn}{abs(pct):.2f}%</span> خلال الفترة).<br>'
                    f'<strong>نطاق الدخول:</strong> <span style="font-family:DV">{fmt_price(lv["entry_lo"],sym)}–{fmt_price(lv["entry_hi"],sym)}</span> · '
                    f'<strong>الهدف:</strong> <span style="font-family:DV;color:#276749">{fmt_price(lv["target"],sym)}</span> · '
                    f'<strong>وقف الخسارة:</strong> <span style="font-family:DV;color:#c53030">{fmt_price(lv["stop"],sym)}</span>')
        else:
            body = (f'Live price <span style="font-family:DV">{fmt_price(lv["price"],sym)}</span> '
                    f'(<span style="color:{pcol}">{psgn}{abs(pct):.2f}%</span> this window).<br>'
                    f'<strong>Entry:</strong> <span style="font-family:DV">{fmt_price(lv["entry_lo"],sym)}–{fmt_price(lv["entry_hi"],sym)}</span> · '
                    f'<strong>Target:</strong> <span style="font-family:DV;color:#276749">{fmt_price(lv["target"],sym)}</span> · '
                    f'<strong>Stop:</strong> <span style="font-family:DV;color:#c53030">{fmt_price(lv["stop"],sym)}</span>')
        out += (f'<div class="opp"><div class="opp-t" style="text-align:{align}">🎯 {nm}</div>'
                f'<p style="text-align:{align}">{body}</p></div>')
    return out or '<div class="opp"><p>تعذّر جلب بيانات الفرص الآن.</p></div>'

def portfolio_signal_table(data, lang="ar"):
    """Computed scoreboard of holdings by window move + action."""
    rows = []
    for kind in ("stocks", "crypto"):
        for item in PORTFOLIO[kind]:
            sym = item["sym"]; d = data[kind].get(sym, {})
            rec = d.get("rec", {}); win = d.get("win", {}) or {}
            rows.append((sym, item["color"], win.get("chg_pct", 0),
                         rec.get("action_ar" if lang == "ar" else "action_en", "—"),
                         rec.get("css", "hl")))
    rows.sort(key=lambda r: r[2], reverse=True)
    th = (("الأصل","تغيّر الفترة","الإشارة") if lang=="ar"
          else ("Asset","Window %","Signal"))
    align = "right" if lang == "ar" else "left"
    direction = "rtl" if lang == "ar" else "ltr"
    body = ""
    for sym, col, pct, act, css in rows:
        pcol = "#c53030" if pct < 0 else "#276749"
        sgn = "▼" if pct < 0 else "▲"
        body += (f'<tr><td style="text-align:{align}"><strong style="color:#{col}">{sym}</strong></td>'
                 f'<td style="font-family:DV;color:{pcol};text-align:{align}">{sgn}{abs(pct):.2f}%</td>'
                 f'<td class="{css}" style="text-align:{align};font-weight:700">{act}</td></tr>')
    return (f'<table class="tbl" style="direction:{direction}">'
            f'<tr><th style="text-align:{align}">{th[0]}</th>'
            f'<th style="text-align:{align}">{th[1]}</th>'
            f'<th style="text-align:{align}">{th[2]}</th></tr>{body}</table>')

def market_read(data, lang="ar"):
    """AI narrative if AI_KEY set, else computed read from live signals."""
    snap = data.get("snapshot", {})
    win = data.get("window", {})
    label = win.get("la" if lang == "ar" else "le", "")
    # build compact facts
    facts = []
    for k, nm in [("sp","S&P500"),("ndx","Nasdaq"),("brent","Brent"),("gold","Gold"),("btc","BTC")]:
        s = snap.get(k, {})
        if s.get("val") is not None:
            facts.append(f"{nm} {s.get('pct',0):+.2f}%")
    movers = []
    for kind in ("stocks", "crypto"):
        for item in PORTFOLIO[kind]:
            d = data[kind].get(item["sym"], {})
            w = d.get("win", {}) or {}
            movers.append((item["sym"], w.get("chg_pct", 0),
                           d.get("rec", {}).get("action_ar" if lang=="ar" else "action_en","")))
    movers.sort(key=lambda x: x[1])
    worst = movers[:2]; best = movers[-2:][::-1]
    facts_txt = " · ".join(facts)
    prompt = (
        ("اكتب فقرة موجزة (4-6 جمل) بالعربية كخبير أسواق، تحليل لحظي للفترة التالية فقط دون تكرار: "
         if lang=="ar" else
         "Write a concise 4-6 sentence market read in English as a markets expert, for THIS window only, no fluff: ")
        + f"\nWindow: {label}\nIndices: {facts_txt}\n"
        + "Top gainers: " + ", ".join(f"{s} {p:+.1f}%" for s,p,_ in best) + "\n"
        + "Top losers: " + ", ".join(f"{s} {p:+.1f}%" for s,p,_ in worst) + "\n"
        + ("اربط الحركة بالمخاطرة العامة وأعطِ خلاصة قابلة للتنفيذ." if lang=="ar"
           else "Tie moves to risk sentiment and end with an actionable takeaway.")
    )
    ai = ai_narrate(prompt, max_tokens=500)
    if ai:
        return ai
    # computed fallback
    if lang == "ar":
        bt = " · ".join(facts) or "بيانات محدودة"
        bo = "، ".join(f"{s} ({p:+.1f}%)" for s,p,_ in best)
        wo = "، ".join(f"{s} ({p:+.1f}%)" for s,p,_ in worst)
        return (f"خلال هذه الفترة ({label}): المؤشرات — {bt}. "
                f"الأفضل أداءً في محفظتك: {bo}؛ والأضعف: {wo}. "
                f"التوصيات في الجداول أعلاه محسوبة لحظيًا من حركة كل أصل ومؤشراته الفنية داخل هذه الفترة تحديدًا — "
                f"وهي تختلف عن تقرير الفترة الأخرى لأن البيانات تتغيّر بتغيّر السوق. "
                f"التزم بمستويات الدخول/الهدف/الوقف ولا تطارد الحركة.")
    bt = " · ".join(facts) or "limited data"
    bo = ", ".join(f"{s} ({p:+.1f}%)" for s,p,_ in best)
    wo = ", ".join(f"{s} ({p:+.1f}%)" for s,p,_ in worst)
    return (f"This window ({label}): indices — {bt}. "
            f"Portfolio leaders: {bo}; laggards: {wo}. "
            f"The recommendation tables above are computed live from each asset's move and technicals within THIS window — "
            f"they differ from the other report because the data changes with the market. "
            f"Respect the entry/target/stop levels; don't chase.")

def _market_ar_live(data, date_str, session, time_gst, css):
    win_la = data.get("window", {}).get("la", "")
    strip  = live_strip_html(data.get("snapshot", {}))
    hicon, hcls, htitle, hbody = dynamic_headline(data.get("snapshot", {}), "ar")
    signals = portfolio_signal_table(data, "ar")
    read = market_read(data, "ar").replace("\n", "<br>")
    opps = opp_blocks_html(data, "ar")
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>{css}</style></head>
<body>
<div class="page ar">
<div class="hdr" style="flex-direction:row-reverse">
  <div style="text-align:right">
    <div class="hdr-badge">تحليل السوق اللحظي · {session}</div>
    <div class="hdr-title">تحليل السوق العالمي والفرص</div>
    <div class="hdr-sub">مؤشرات حية · إشارات المحفظة · قراءة السوق · الفرص</div>
  </div>
  <div style="text-align:left">
    <div style="font-size:18px;font-weight:700;color:#fff">{date_str}</div>
    <div style="font-size:10px;color:rgba(255,255,255,.7);margin-top:3px">{time_gst} · بتوقيت الخليج</div>
    <div style="font-size:9.5px;color:rgba(255,255,255,.9);margin-top:5px;background:rgba(255,255,255,.14);border-radius:6px;padding:3px 9px;display:inline-block">🕐 {win_la}</div>
  </div>
</div>
{strip}
<div class="alert alert-ar {hcls}">
  <div class="a-icon">{hicon}</div>
  <div style="flex:1;text-align:right">
    <div class="a-title">{htitle}</div>
    <div class="a-body">{hbody}</div>
  </div>
</div>
<div class="sec sec-ar"><div class="dot"></div>📊 إشارات محفظتك خلال الفترة (مرتّبة بالأداء)</div>
{signals}
<div class="sec sec-ar"><div class="dot"></div>🧠 قراءة السوق اللحظية</div>
<div class="bline" style="text-align:right"><h3>⚡ خلاصة الفترة</h3><p>{read}</p></div>
<div class="footer">تحليل السوق اللحظي · {date_str} · للأغراض المعلوماتية فقط · ليس نصيحة مالية</div>
</div>

<div class="page ar">
<div style="background:linear-gradient(135deg,#0f2d5a,#1d4ed8);border-radius:12px;padding:18px 26px;margin-bottom:18px;display:flex;justify-content:space-between;align-items:center">
  <div style="text-align:right">
    <div style="font-size:10px;color:rgba(255,255,255,.65);margin-bottom:3px">تحليل السوق اللحظي · الفرص</div>
    <div style="font-size:19px;font-weight:700;color:#fff">فرص الدخول — مستويات محسوبة لحظيًا</div>
  </div>
  <div style="font-size:10.5px;color:rgba(255,255,255,.75)">{date_str}</div>
</div>
<div class="sec sec-ar"><div class="dot"></div>🌟 فرص خارج محفظتك (أسعار ومستويات حية)</div>
{opps}
<div class="bline" style="text-align:right"><h3>⚡ تنبيه</h3><p>المستويات أعلاه محسوبة آليًا من حركة كل أصل داخل هذه الفترة فقط، وتتغيّر مع كل تقرير. ليست نصيحة مالية — أدِر المخاطر دائمًا.</p></div>
<div class="footer">تحليل السوق اللحظي · الفرص · {date_str} · للأغراض المعلوماتية فقط · ليس نصيحة مالية</div>
</div>
</body></html>"""

def _market_en_live(data, date_str, session_en, time_gst, css):
    win_le = data.get("window", {}).get("le", "")
    strip  = live_strip_html(data.get("snapshot", {}))
    hicon, hcls, htitle, hbody = dynamic_headline(data.get("snapshot", {}), "en")
    signals = portfolio_signal_table(data, "en")
    read = market_read(data, "en").replace("\n", "<br>")
    opps = opp_blocks_html(data, "en")
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>{css}</style></head>
<body>
<div class="page en">
<div class="hdr">
  <div>
    <div class="hdr-badge">Live Market Analysis · {session_en}</div>
    <div class="hdr-title">Global Market Intelligence & Opportunities</div>
    <div class="hdr-sub">Live indices · Portfolio signals · Market read · Opportunities</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:18px;font-weight:700;color:#fff">{date_str}</div>
    <div style="font-size:10px;color:rgba(255,255,255,.7);margin-top:3px">{time_gst} · {session_en}</div>
    <div style="font-size:9.5px;color:rgba(255,255,255,.9);margin-top:5px;background:rgba(255,255,255,.14);border-radius:6px;padding:3px 9px;display:inline-block">🕐 {win_le}</div>
  </div>
</div>
{strip}
<div class="alert {hcls}">
  <div class="a-icon">{hicon}</div>
  <div style="flex:1">
    <div class="a-title">{htitle}</div>
    <div class="a-body">{hbody}</div>
  </div>
</div>
<div class="sec"><div class="dot"></div>📊 Your Portfolio Signals This Window (ranked)</div>
{signals}
<div class="sec"><div class="dot"></div>🧠 Live Market Read</div>
<div class="bline"><h3>⚡ Window Takeaway</h3><p>{read}</p></div>
<div class="footer">Live Market Analysis · {date_str} · For informational purposes only · Not financial advice</div>
</div>

<div class="page en">
<div style="background:linear-gradient(135deg,#0f2d5a,#1d4ed8);border-radius:12px;padding:18px 26px;margin-bottom:18px;display:flex;justify-content:space-between;align-items:center">
  <div>
    <div style="font-size:10px;color:rgba(255,255,255,.65);margin-bottom:3px">Live Market Analysis · Opportunities</div>
    <div style="font-size:19px;font-weight:700;color:#fff">Entry Opportunities — Live Computed Levels</div>
  </div>
  <div style="font-size:10.5px;color:rgba(255,255,255,.75)">{date_str}</div>
</div>
<div class="sec"><div class="dot"></div>🌟 Opportunities Outside Your Portfolio (live prices & levels)</div>
{opps}
<div class="bline"><h3>⚡ Note</h3><p>Levels above are computed automatically from each asset's move within THIS window only and change every report. Not financial advice — always manage risk.</p></div>
<div class="footer">Live Market Analysis · Opportunities · {date_str} · For informational purposes only · Not financial advice</div>
</div>
</body></html>"""

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


def collect_data(start_utc=None, end_utc=None, session="morning"):
    """Collect LIVE, WINDOW-SPECIFIC data + technical signals + recommendations.
    Each report passes its own [start_utc,end_utc] so the two reports differ."""
    if end_utc is None:
        end_utc = _dt.datetime.now(tz=UTC)
    _s, _e, win_la, win_le = window_bounds(end_utc, session)
    if start_utc is None:
        start_utc = _s
    print(f"📡 Fetching live data for window {start_utc:%m-%d %H:%M} → {end_utc:%m-%d %H:%M} UTC ...")
    data = {"stocks": {}, "crypto": {}, "window": {"start": start_utc.isoformat(),
            "end": end_utc.isoformat(), "session": session, "la": win_la, "le": win_le}}

    for s in PORTFOLIO["stocks"]:
        sym = s["sym"]
        print(f"  {sym}...")
        q    = fetch_quote(sym)
        win  = fetch_window(sym, start_utc, end_utc)
        ind  = fetch_indicators(sym)
        news = fetch_news(sym, 4)
        # current price preference: live window close > quote price > entry
        price = win.get("last") or q.get("price") or s["buy"]
        rec   = recommend(sym, s["buy"], price, win, ind)
        data["stocks"][sym] = {"quote": q, "win": win, "ind": ind,
                               "news": news, "price": price, "rec": rec}
        time.sleep(1.0)

    for c in PORTFOLIO["crypto"]:
        sym = c["sym"]
        print(f"  {sym}...")
        yfsym = CRYPTO_YF.get(sym, f"{sym}-USD")
        win   = fetch_window(yfsym, start_utc, end_utc)
        ind   = fetch_indicators(yfsym)
        price = win.get("last")
        if not price:                                  # fallback to Alpha Vantage
            price = fetch_crypto(sym).get("price", c["buy"])
        news  = fetch_news(f"CRYPTO:{sym}", 3)
        rec   = recommend(sym, c["buy"], price, win, ind)
        data["crypto"][sym] = {"price": {"price": price}, "win": win, "ind": ind,
                               "news": news, "rec": rec}
        time.sleep(1.0)

    # Live market index/commodity snapshot for THIS window
    print("  Fetching live market snapshot...")
    data["snapshot"] = fetch_market_snapshot(start_utc, end_utc)
    # Real-time opportunity asset prices (+ window change)
    print("  Fetching opportunity asset prices...")
    data["opp_prices"] = fetch_opportunity_prices()
    data["opp_win"] = {s: fetch_window(s, start_utc, end_utc)
                       for s in ["BTC-USD","COIN","AMD","XLM-USD","ETH-USD"]}
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
    win_la = data.get("window", {}).get("la", "")

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


        _d = data["stocks"][sym]
        cur = _d.get("price") or q.get("price", s["buy"])
        chg_pct = (_d.get("win") or {}).get("chg_pct", float(q.get("chg_pct", 0)))
        vol = fmt_vol((_d.get("win") or {}).get("vol") or q.get("volume", 0))
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
        <div style="font-family:DV;font-size:11px;color:{chg_col}">{arrow(chg_pct)} {abs(chg_pct):.2f}% خلال الفترة &nbsp;|&nbsp; حجم: {vol}</div>
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
    <div class="hdr-sub">MU · NOW · PLTR</div>
  </div>
  <div style="text-align:left">
    <div style="font-size:18px;font-weight:700;color:#fff">{date_str}</div>
    <div style="font-size:10px;color:rgba(255,255,255,.7);margin-top:3px">{time_gst} · {session} · بتوقيت الخليج</div>
    <div style="font-size:9.5px;color:rgba(255,255,255,.9);margin-top:5px;background:rgba(255,255,255,.14);border-radius:6px;padding:3px 9px;display:inline-block">🕐 {win_la}</div>
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
    <div class="hdr-sub">XRP · SOL · HBAR</div>
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

<div class="sec sec-ar"><div class="dot"></div>⚡ خطة العمل — توصيات محسوبة لحظيًا ({win_la})</div>
<table class="tbl" style="direction:rtl">
<tr><th style="text-align:right">الأصل</th><th style="text-align:right">السعر</th><th style="text-align:right">تغيّر الفترة</th><th style="text-align:right">التوصية</th><th style="text-align:right">دخول</th><th style="text-align:right">هدف</th><th style="text-align:right">وقف</th><th style="text-align:right">السبب</th></tr>"""

    def _rec_row_ar(item, kind):
        sym = item["sym"]
        d   = data[kind][sym]
        rec = d.get("rec", {})
        win = d.get("win", {}) or {}
        price = d.get("price") if kind == "stocks" else d.get("price", {}).get("price", item["buy"])
        wpct  = win.get("chg_pct", 0)
        col, css = item["color"], rec.get("css", "hl")
        wa  = "▲" if wpct >= 0 else "▼"
        wc  = "#276749" if wpct >= 0 else "#c53030"
        return (f'<tr><td><strong style="color:#{col}">{sym}</strong></td>'
                f'<td style="font-family:DV;font-weight:700">{fmt_price(price, sym)}</td>'
                f'<td style="font-family:DV;color:{wc}">{wa}{abs(wpct):.2f}%</td>'
                f'<td class="{css}" style="font-weight:700">{rec.get("action_ar","احتفظ")}</td>'
                f'<td style="font-family:DV;font-size:10px">{fmt_price(rec.get("entry_lo",0),sym)}<br>{fmt_price(rec.get("entry_hi",0),sym)}</td>'
                f'<td style="font-family:DV;font-size:10.5px;color:#276749;font-weight:700">{fmt_price(rec.get("target",0),sym)}</td>'
                f'<td style="font-family:DV;font-size:10.5px;color:#c53030;font-weight:700">{fmt_price(rec.get("stop",0),sym)}</td>'
                f'<td style="font-size:9.5px;color:#4a5568;text-align:right;line-height:1.5">{rec.get("reason_ar","")}</td></tr>')
    for s in PORTFOLIO["stocks"]:
        html += _rec_row_ar(s, "stocks")
    for c in PORTFOLIO["crypto"]:
        html += _rec_row_ar(c, "crypto")

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
    win_le = data.get("window", {}).get("le", "")

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

        _d     = data["stocks"][sym]
        cur    = _d.get("price") or q.get("price", s["buy"])
        chg_p  = (_d.get("win") or {}).get("chg_pct", float(q.get("chg_pct", 0)))
        vol    = fmt_vol((_d.get("win") or {}).get("vol") or q.get("volume", 0))
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
        <div style="font-family:DV;font-size:11px;color:{chg_col}">{arrow(chg_p)} {abs(chg_p):.2f}% this window &nbsp;|&nbsp; Vol: {vol}</div>
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

    # Action table — computed live recommendations
    def _rec_row_en(item, kind):
        sym = item["sym"]
        d   = data[kind][sym]
        rec = d.get("rec", {})
        win = d.get("win", {}) or {}
        price = d.get("price") if kind == "stocks" else d.get("price", {}).get("price", item["buy"])
        wpct  = win.get("chg_pct", 0)
        col, css = item["color"], rec.get("css", "hl")
        wc  = "#276749" if wpct >= 0 else "#c53030"
        return (f'<tr><td><strong style="color:#{col}">{sym}</strong></td>'
                f'<td style="font-family:DV;font-weight:700">{fmt_price(price, sym)}</td>'
                f'<td style="font-family:DV;color:{wc}">{arrow(wpct)}{abs(wpct):.2f}%</td>'
                f'<td class="{css}" style="font-weight:700">{rec.get("action_en","HOLD")}</td>'
                f'<td style="font-family:DV;font-size:10px">{fmt_price(rec.get("entry_lo",0),sym)}–{fmt_price(rec.get("entry_hi",0),sym)}</td>'
                f'<td style="font-family:DV;font-size:10.5px;color:#276749;font-weight:700">{fmt_price(rec.get("target",0),sym)}</td>'
                f'<td style="font-family:DV;font-size:10.5px;color:#c53030;font-weight:700">{fmt_price(rec.get("stop",0),sym)}</td>'
                f'<td style="font-size:9.5px;color:#4a5568;line-height:1.5">{rec.get("reason_en","")}</td></tr>')
    action_rows = "".join(_rec_row_en(s, "stocks") for s in port["stocks"])
    action_rows += "".join(_rec_row_en(c, "crypto") for c in port["crypto"])

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>{css}</style></head>
<body>
<!-- PAGE 1: STOCKS EN -->
<div class="page en">
<div class="hdr">
  <div>
    <div class="hdr-badge">Saif's Portfolio · {session_en} {icon} · Stocks</div>
    <div class="hdr-title">My Portfolio — Stocks</div>
    <div class="hdr-sub">MU · NOW · PLTR</div>
  </div>
  <div style="text-align:right">
    <div style="font-size:18px;font-weight:700;color:#fff">{date_str}</div>
    <div style="font-size:10px;color:rgba(255,255,255,.7);margin-top:3px">{time_gst} · {session_en}</div>
    <div style="font-size:9.5px;color:rgba(255,255,255,.9);margin-top:5px;background:rgba(255,255,255,.14);border-radius:6px;padding:3px 9px;display:inline-block">🕐 {win_le}</div>
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

<div class="sec"><div class="dot"></div>⚡ ACTION PLAN — Live Computed Recommendations ({win_le})</div>
<table class="tbl" style="direction:ltr">
<tr><th>Asset</th><th>Price</th><th>Window %</th><th>Action</th><th>Entry</th><th>Target</th><th>Stop</th><th>Why</th></tr>
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


def fetch_opportunity_prices() -> dict:
    """Fetch real-time prices for opportunity assets using yfinance."""
    prices = {}
    # Stocks to watch
    for sym in ["BTC-USD", "COIN", "AMD", "XLM-USD", "ETH-USD"]:
        try:
            import yfinance as yf
            t    = yf.Ticker(sym)
            info = t.info
            price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose") or 0
            prev  = info.get("previousClose") or price
            chg_p = ((price - prev) / prev * 100) if prev else 0
            # Pre/Post market
            pre_p  = info.get("preMarketPrice")
            pre_c  = info.get("preMarketChangePercent")
            post_p = info.get("postMarketPrice")
            post_c = info.get("postMarketChangePercent")
            prices[sym] = {
                "price":     round(float(price), 4),
                "chg_pct":   round(float(chg_p), 2),
                "pre_price": round(float(pre_p), 4) if pre_p else None,
                "pre_chg":   round(float(pre_c)*100, 2) if pre_c else None,
                "post_price":round(float(post_p), 4) if post_p else None,
                "post_chg":  round(float(post_c)*100, 2) if post_c else None,
            }
            time.sleep(0.3)
        except Exception as e:
            print(f"  ⚠️ Opp price error {sym}: {e}")
            prices[sym] = {"price": 0, "chg_pct": 0}
    return prices

def build_market_ar(data, date_str, session="الصباحي", icon="🌅", time_gst="10:30 GST", am="", amb="", dv="", dvb=""):
    css = build_css(am, amb, dv, dvb)
    return _market_ar_live(data, date_str, session, time_gst, css)

def build_market_en(data, date_str, session_en="Morning", icon="🌅", time_gst="10:30 GST", am="", amb="", dv="", dvb=""):
    css = build_css(am, amb, dv, dvb)
    return _market_en_live(data, date_str, session_en, time_gst, css)

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
        ("market_ar",     build_market_ar(data, date_str, session, icon, time_gst, am, amb, dv, dvb),    f"{out}/2_market_ar_{ds}.pdf"),
        ("market_en",     build_market_en(data, date_str, session_en, icon, time_gst, am, amb, dv, dvb), f"{out}/3_market_en_{ds}.pdf"),
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
    """Send email directly via Resend API — no dispatch needed."""
    RESEND_KEY = os.environ.get("RESEND_KEY", "")
    if not RESEND_KEY:
        raise RuntimeError("RESEND_KEY secret not set - cannot send email")
    r = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "from":    EMAIL_FROM,
            "to":      [EMAIL_TO],
            "subject": subject,
            "text":    body
        },
        timeout=30
    )
    if r.status_code in (200, 201):
        email_id = r.json().get("id", "?")
        print(f"  ✅ Email sent via Resend! ID: {email_id}")
    else:
        print(f"Resend send FAILED: HTTP {r.status_code} - {r.text[:300]}")
        raise RuntimeError(f"Resend send failed: HTTP {r.status_code} - {r.text[:300]}")

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

    lines_s, lines_c = [], []
    t_cost = t_val = 0
    for s in PORTFOLIO["stocks"]:
        q = data["stocks"][s["sym"]].get("quote", {})
        cur = data["stocks"][s["sym"]].get("price") or q.get("price", s["buy"])
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
    win_la = data.get("window", {}).get("la", "")

    body = f"""{greeting} سيف {icon}

تقاريرك {session}ية جاهزة — {date_str}
🕐 {win_la}

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
📥 التقارير الكاملة (3 ملفات PDF):

🇸🇦 محفظتك الشخصية (عربي):
{urls.get('portfolio_ar', 'غير متاح')}

🇸🇦 تحليل السوق + فرص الدخول (عربي):
{urls.get('market_ar', 'غير متاح')}

🇬🇧 Market Analysis + Opportunities (English):
{urls.get('market_en', 'N/A')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 Claude · محرك تحليل لحظي
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
    sess_key = "evening" if gst_hour >= 17 else "morning"

    print(f"\n{'='*50}")
    print(f"  {session_en.upper()} BRIEFING — {date_str} {time_gst}")
    print(f"  window session = {sess_key}")
    print(f"{'='*50}")

    data = collect_data(session=sess_key)
    pdfs = build_all_pdfs(data, date_str, session, session_en, icon, time_gst)
    send_briefing(pdfs, data, date_str, session, session_en, icon, time_gst, greeting)
    print(f"\n✅ Done — {date_str} {time_gst}\n")

if __name__ == "__main__":
    run()
# v2: live window engine + computed recommendations + AI layer
