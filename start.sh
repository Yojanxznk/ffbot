#!/bin/bash
set -e

echo "[start.sh] Arrancando FF Bot..."
python Main.py &
BOT_PID=$!

echo "[start.sh] Arrancando Panel Web..."
python web_panel.py &
PANEL_PID=$!

echo "[start.sh] Bot PID=$BOT_PID | Panel PID=$PANEL_PID"

wait -n $BOT_PID $PANEL_PID
echo "[start.sh] Un proceso murió, cerrando el otro..."
kill $BOT_PID $PANEL_PID 2>/dev/null || true
exit 1
