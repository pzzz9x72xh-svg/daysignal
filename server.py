import os
from datetime import datetime, timedelta, timezone

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

load_dotenv()

API_KEY = os.getenv("ALPACA_API_KEY")
API_SECRET = os.getenv("ALPACA_API_SECRET")

if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing ALPACA_API_KEY / ALPACA_API_SECRET in .env")

client = StockHistoricalDataClient(API_KEY, API_SECRET)

app = FastAPI(title="DaySignal Backend (Live)")

# Allow the web app to call this API from your phone browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # for MVP. Later: restrict to your domain.
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

WATCHLIST = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]
RISK_EUR = float(os.getenv("RISK_EUR", "25.0"))


def compute_vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = tp * df["volume"]
    return pv.cumsum() / df["volume"].cumsum()


def avg_vol_last(df: pd.DataFrame, n=20) -> float:
    return float(df["volume"].tail(n).mean()) if len(df) >= n else float(df["volume"].mean())


def traffic_light_from_spy(df_spy: pd.DataFrame) -> tuple[str, str]:
    df = df_spy.copy()
    df["vwap"] = compute_vwap(df)
    last = df.iloc[-1]
    if last["close"] >= last["vwap"]:
        return "GREEN", "Markt OK (SPY über VWAP)"
    if last["close"] < last["vwap"] * 0.998:
        return "RED", "Vorsicht (SPY unter VWAP)"
    return "YELLOW", "Markt neutral"


def vwap_reclaim_long_signal(df: pd.DataFrame, market_light: str):
    if market_light != "GREEN":
        return {"action": "WAIT", "confidence": 35, "reasons": ["Markt nicht grün → kein Long-Trade"]}

    if len(df) < 50:
        return {"action": "WAIT", "confidence": 40, "reasons": ["Zu wenig Live-Daten (warte ein paar Minuten)"]}

    d = df.copy()
    d["vwap"] = compute_vwap(d)

    last = d.iloc[-1]
    prev = d.iloc[-2]

    dip = (d["close"].tail(30) < d["vwap"].tail(30)).any()
    reclaim = (last["close"] > last["vwap"]) and (prev["close"] <= prev["vwap"])
    vol_ok = last["volume"] >= 1.3 * avg_vol_last(d, 20)

    reasons = []
    if dip: reasons.append("Kurs war unter VWAP (Dip)")
    if reclaim: reasons.append("Kurs wieder über VWAP (Reclaim)")
    if vol_ok: reasons.append("Volumen bestätigt")

    if dip and reclaim and vol_ok:
        entry = float(last["close"])
        recent_low = float(d["low"].tail(10).min())
        stop = recent_low - 0.001 * entry  # 0.1% buffer

        r = entry - stop
        if r <= 0:
            return {"action": "WAIT", "confidence": 50, "reasons": reasons + ["Stop unplausibel → kein Trade"]}

        shares = int(RISK_EUR / r)
        if shares < 1:
            return {"action": "WAIT", "confidence": 55, "reasons": reasons + ["Stop zu groß für Risiko → kein Trade"]}

        tp1 = entry + 1.0 * r
        tp2 = entry + 2.0 * r

        return {
            "action": "BUY",
            "confidence": 75,
            "entryPrice": entry,
            "stop": float(stop),
            "tp1": float(tp1),
            "tp2": float(tp2),
            "shares": shares,
            "reasons": reasons + ["Regeln erfüllt (VWAP Reclaim Long)"],
        }

    if reclaim and not vol_ok:
        return {"action": "WAIT", "confidence": 55, "reasons": reasons + ["Volumen fehlt → warten"]}

    return {"action": "WAIT", "confidence": 45, "reasons": reasons or ["Kein sauberes Setup"]


@app.get("/today")
def today():
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=220)

        req = StockBarsRequest(
            symbol_or_symbols=WATCHLIST,
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
        )

        bars = client.get_stock_bars(req).df
        if bars is None or bars.empty:
            raise RuntimeError("No bars returned. Check Alpaca key/plan and symbol coverage.")

        # Market light
        if "SPY" not in bars.index.get_level_values(0):
            market_light, market_note = "YELLOW", "SPY Daten fehlen (warte)"
        else:
            spy_df = bars.xs("SPY", level=0).reset_index().sort_values("timestamp")
            market_light, market_note = traffic_light_from_spy(spy_df)

        out = []
        for sym in WATCHLIST:
            if sym not in bars.index.get_level_values(0):
                continue
            df = bars.xs(sym, level=0).reset_index().sort_values("timestamp")
            sig = vwap_reclaim_long_signal(df, market_light)

            out.append({
                "id": sym,
                "symbol": sym,
                "action": sig["action"],
                "setup": "VWAP Reclaim (Long)",
                "confidence": sig.get("confidence", 50),
                "entryTriggerText": "Kaufen, wenn Kurs nach Dip wieder über VWAP schließt UND Volumen bestätigt.",
                "entryPrice": sig.get("entryPrice"),
                "stop": sig.get("stop"),
                "tp1": sig.get("tp1"),
                "tp2": sig.get("tp2"),
                "riskEUR": RISK_EUR,
                "shares": sig.get("shares", 0),
                "reasons": sig.get("reasons", []),
                "updatedAtISO": datetime.now(timezone.utc).isoformat(),
            })

        return {"market": {"spyLight": market_light, "note": market_note}, "signals": out}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
