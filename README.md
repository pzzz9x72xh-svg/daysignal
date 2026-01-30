# DaySignal Web-App (läuft direkt auf dem iPhone)

Diese Web-App zeigt:
- Markt-Ampel (grün/gelb/rot) basierend auf SPY vs. VWAP
- BUY/WAIT Signale (Long-only, VWAP Reclaim)
- Entry/Stop/TP1/TP2 + Stückzahl (bei 25€ Risiko)

## Nutzung am iPhone
1) Öffne `index.html` über eine Webseite/Hosting (z.B. Cloudflare Pages, Vercel, Netlify, GitHub Pages)
2) In Safari: Teilen -> "Zum Home-Bildschirm"
3) In der Web-App: Backend URL eintragen (dein Live-Backend)

## Hinweis
Wenn dein Backend zuhause läuft, funktioniert es nur im gleichen WLAN.
Für überall-Zugriff: Backend auf Render/Railway/Fly.io hosten.
