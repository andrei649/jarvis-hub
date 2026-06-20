"""
widget.py — H10.1 Embeddable Chat Widget.

Issues per-site widget tokens and renders a self-contained JS snippet (with
inline CSS) that drops a floating Jarvis chat bubble onto any website. Theming
(title, accent color, position, greeting) is configurable per token from Admin.
The snippet posts messages to a token-scoped endpoint, so a site embeds the
widget without ever holding an admin credential.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from string import Template
from typing import Optional

from agents.core.paths import data_path

from .persistence import JsonStore

DEFAULT_PATH = data_path("widgets.json")

_DEFAULTS = {
    "title": "Jarvis",
    "color": "#4f46e5",
    "position": "bottom-right",
    "greeting": "Hi! How can I help?",
}


class WidgetStore(JsonStore):
    _widgets: dict[str, dict]

    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        super().__init__(path)

    def _serialize(self):
        return self._widgets

    def _deserialize(self, raw) -> None:
        self._widgets = raw if isinstance(raw, dict) else {}

    def issue(self, config: Optional[dict] = None) -> dict:
        token = secrets.token_urlsafe(12)
        cfg = {**_DEFAULTS, **{k: v for k, v in (config or {}).items() if k in _DEFAULTS}}
        cfg["token"] = token
        with self._lock:
            self._widgets[token] = cfg
            self._save()
        return dict(cfg)

    def get(self, token: str) -> Optional[dict]:
        with self._lock:
            cfg = self._widgets.get(token)
            return dict(cfg) if cfg else None

    def update(self, token: str, config: dict) -> Optional[dict]:
        with self._lock:
            cfg = self._widgets.get(token)
            if cfg is None:
                return None
            for k, v in (config or {}).items():
                if k in _DEFAULTS:
                    cfg[k] = v
            self._save()
            return dict(cfg)

    def revoke(self, token: str) -> bool:
        with self._lock:
            if token in self._widgets:
                del self._widgets[token]
                self._save()
                return True
            return False

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(c) for c in self._widgets.values()]


# Self-contained widget snippet. $-placeholders are filled by render_snippet;
# JS braces are doubled where needed via the Template ($$ would escape, but this
# template uses no literal $ so plain braces are fine).
_SNIPPET = Template("""(function(){
  var T="$token", BASE="$base", TITLE="$title", COLOR="$color",
      POS="$position", GREET="$greeting";
  var side = POS.indexOf("left")>=0 ? "left" : "right";
  var btn=document.createElement("div");
  btn.textContent="💬";
  btn.style.cssText="position:fixed;bottom:20px;"+side+":20px;width:56px;height:56px;"
    +"border-radius:50%;background:"+COLOR+";color:#fff;font-size:24px;display:flex;"
    +"align-items:center;justify-content:center;cursor:pointer;z-index:2147483647;"
    +"box-shadow:0 2px 12px rgba(0,0,0,.3)";
  var panel=document.createElement("div");
  panel.style.cssText="position:fixed;bottom:88px;"+side+":20px;width:320px;max-height:440px;"
    +"display:none;flex-direction:column;background:#fff;border-radius:12px;overflow:hidden;"
    +"z-index:2147483647;box-shadow:0 4px 24px rgba(0,0,0,.25);font-family:sans-serif";
  panel.innerHTML="<div style='background:"+COLOR+";color:#fff;padding:12px;font-weight:600'>"
    +TITLE+"</div><div id='jv-log' style='flex:1;overflow-y:auto;padding:12px;font-size:14px'></div>"
    +"<div style='display:flex;border-top:1px solid #eee'>"
    +"<input id='jv-in' style='flex:1;border:0;padding:12px;font-size:14px;outline:none' "
    +"placeholder='Type a message...'/></div>";
  document.body.appendChild(btn); document.body.appendChild(panel);
  var log; function add(who,text){var d=document.createElement("div");
    d.style.cssText="margin:6px 0;"+(who==="you"?"text-align:right":"");
    d.innerHTML="<span style='display:inline-block;padding:6px 10px;border-radius:10px;background:"
      +(who==="you"?COLOR+";color:#fff":"#f0f0f3")+"'>"+text.replace(/</g,"&lt;")+"</span>";
    log.appendChild(d); log.scrollTop=log.scrollHeight;}
  btn.onclick=function(){var open=panel.style.display==="flex";
    panel.style.display=open?"none":"flex";
    if(!open && !log){log=panel.querySelector("#jv-log"); if(GREET) add("bot",GREET);}};
  panel.addEventListener("keydown",function(e){
    if(e.key!=="Enter") return; var inp=panel.querySelector("#jv-in");
    var msg=inp.value.trim(); if(!msg) return; inp.value=""; add("you",msg);
    fetch(BASE+"/api/widget/"+T+"/message",{method:"POST",
      headers:{"Content-Type":"application/json"},body:JSON.stringify({message:msg})})
      .then(function(r){return r.json();})
      .then(function(d){add("bot",d.reply||d.error||"(no reply)");})
      .catch(function(){add("bot","(connection error)");});
  });
})();""")


def render_snippet(config: dict, base_url: str = "") -> str:
    """Render the embeddable JS for a widget config."""
    return _SNIPPET.substitute(
        token=config.get("token", ""),
        base=base_url,
        title=config.get("title", _DEFAULTS["title"]).replace('"', "'"),
        color=config.get("color", _DEFAULTS["color"]),
        position=config.get("position", _DEFAULTS["position"]),
        greeting=config.get("greeting", _DEFAULTS["greeting"]).replace('"', "'"),
    )
