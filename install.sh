#!/usr/bin/env bash
set -euo pipefail

REQUIRED_CMDS="python3 curl pip3"
MISSING=0
for cmd in $REQUIRED_CMDS; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: $cmd is required but not installed."
    MISSING=1
  fi
done
[ $MISSING -eq 1 ] && exit 1

echo "================================================"
echo "  JARVIS HUB — Personal AI Agent System"
echo "  Instalare și configurare"
echo "================================================"
echo ""

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "[1/5] Verificare Ollama..."
if command -v ollama &>/dev/null; then
  echo "  ✓ Ollama găsit"
else
  echo "  Instalare Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
fi

echo ""
echo "[2/5] Pull modele LLM..."
echo "  deepseek-r1:32b (~20GB) — poate dura..."
ollama pull deepseek-r1:32b &
PID_DS=$!
ollama pull qwen2.5:14b &
PID_Q14=$!
ollama pull qwen2.5:7b &
PID_Q7=$!
wait $PID_DS 2>/dev/null || echo "  ⚠ deepseek-r1:32b eșuat (poți rula manual)"
wait $PID_Q14 2>/dev/null || echo "  ⚠ qwen2.5:14b eșuat"
wait $PID_Q7 2>/dev/null || echo "  ⚠ qwen2.5:7b eșuat"

echo ""
echo "[3/5] Instalare dependențe Python..."
pip3 install -r requirements.txt --quiet 2>/dev/null || pip install -r requirements.txt --quiet

echo ""
echo "[4/5] Pregătire directoare..."
mkdir -p data/memory data/backups
if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "  ✓ .env creat din .env.example — completează-ți cheile!"
fi

echo ""
echo "[5/5] Verificare finală..."
python3 -c "
from core.agent_loader import AgentLoader
a = AgentLoader('agents')
agents = a.discover_all()
print(f'  {len(agents)} agenți descoperiți:')
for ag in agents:
    hb = '❤' if ag.heartbeat_interval_minutes else '  '
    status = '✓' if ag.enabled else '✗'
    print(f'    {status} {ag.id:15s} | {ag.model:20s} | {ag.channel:10s} {hb}')
" 2>/dev/null || python3 -c "
import sys; sys.path.insert(0, '.')
from core.agent_loader import AgentLoader
a = AgentLoader('agents')
agents = a.discover_all()
print(f'  {len(agents)} agenți descoperiți:')
for ag in agents:
    hb = '❤' if ag.heartbeat_interval_minutes else '  '
    status = '✓' if ag.enabled else '✗'
    print(f'    {status} {ag.id:15s} | {ag.model:20s} | {ag.channel:10s} {hb}')
"

echo ""
echo "================================================"
echo "  Instalare completă!"
echo ""
echo "  Rulează: python main.py"
echo "  Web UI:  http://localhost:8765"
echo "================================================"
