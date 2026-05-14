#!/usr/bin/env python3
"""
Bridge responder helper — run this via opencode to answer pending prompts.
Usage:
  python3 data/bridge/respond.py list              # list pending prompts
  python3 data/bridge/respond.py show <id>          # show full prompt
  python3 data/bridge/respond.py answer <id> <text> # write response
"""
import json
import os
import sys
from pathlib import Path

BRIDGE_DIR = Path(__file__).parent


def list_pending():
    prompts = sorted(BRIDGE_DIR.glob("prompt_*.json"))
    responses = {f.stem.replace("response_", "") for f in BRIDGE_DIR.glob("response_*.json")}
    pending = [p for p in prompts if p.stem.replace("prompt_", "") not in responses]
    if not pending:
        print("No pending prompts.")
        return
    for p in pending:
        data = json.loads(p.read_text())
        pid = data["id"][:20]
        agent = data["agent_id"]
        prompt_preview = data["prompt"][:80].replace("\n", " ")
        print(f"  [{pid}] agent={agent} | {prompt_preview}...")


def show_prompt(pid: str):
    for f in BRIDGE_DIR.glob(f"prompt_{pid}*.json"):
        data = json.loads(f.read_text())
        print(f"Agent:  {data['agent_id']}")
        print(f"Model:  {data['model']}")
        print(f"Time:   {data['created_at']}")
        print(f"Prompt:\n{'-'*40}")
        print(data["prompt"])
        print(f"{'-'*40}")
        return
    print(f"Prompt '{pid}' not found.")


def answer_prompt(pid: str, text: str):
    prompt_file = None
    for f in BRIDGE_DIR.glob(f"prompt_{pid}*.json"):
        prompt_file = f
        break
    if not prompt_file:
        print(f"Prompt '{pid}' not found.")
        return
    data = json.loads(prompt_file.read_text())
    response = {"id": data["id"], "response": text, "responded_at": __import__("datetime").datetime.now().isoformat()}
    resp_file = BRIDGE_DIR / f"response_{data['id']}.json"
    resp_file.write_text(json.dumps(response, indent=2, ensure_ascii=False))
    print(f"Response written to {resp_file.name}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "list":
        list_pending()
    elif cmd == "show" and len(sys.argv) > 2:
        show_prompt(sys.argv[2])
    elif cmd == "answer" and len(sys.argv) > 3:
        answer_prompt(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
