"""pack.py — 0.42 Security Skills Pack (curated defensive-security knowledge).

A pure, offline, deterministic knowledge pack over **public** security taxonomies:

  * **MITRE ATT&CK** (enterprise) — adversary *tactics* (the "why") and a curated set
    of representative *techniques* (the "how").
  * **MITRE D3FEND** — *defensive* countermeasures, mapped to the ATT&CK techniques
    they counter.
  * **NIST CSF 2.0** — the six high-level *functions* a defensive program organizes around.

It maps a free-text behavior to candidate ATT&CK techniques (an honest keyword
heuristic — never fabricated), and assembles a **defensive playbook**: per technique,
the D3FEND countermeasures and CSF functions that address it, with honest gaps where
the curated mapping has none.

Scope honesty (the same ethos as the market/creative packs):
  * This is a **curated educational subset**, NOT the full corpus (ATT&CK alone has
    600+ techniques). Every payload carries ``curated: true`` + ``DISCLAIMER`` and the
    authoritative ``SOURCES``. It never claims completeness and never fabricates an ID.
  * Read-only and offline: no network, no external calls, no state. It informs; it does
    not act.
"""

from __future__ import annotations

DISCLAIMER = (
    "Curated educational subset of public security taxonomies (MITRE ATT&CK, MITRE "
    "D3FEND, NIST CSF 2.0). NOT a complete control set and NOT security advice — "
    "verify against the authoritative sources before relying on it operationally."
)

SOURCES = {
    "attack": "https://attack.mitre.org/ (MITRE ATT&CK Enterprise)",
    "d3fend": "https://d3fend.mitre.org/ (MITRE D3FEND)",
    "nist_csf": "https://www.nist.gov/cyberframework (NIST CSF 2.0)",
}


# ── MITRE ATT&CK enterprise tactics (the 14, complete) ───────────────────────────
TACTICS: tuple[dict, ...] = (
    {"id": "TA0043", "name": "Reconnaissance", "summary": "Gather information to plan future operations."},
    {"id": "TA0042", "name": "Resource Development", "summary": "Establish resources to support operations."},
    {"id": "TA0001", "name": "Initial Access", "summary": "Get into the network."},
    {"id": "TA0002", "name": "Execution", "summary": "Run adversary-controlled code."},
    {"id": "TA0003", "name": "Persistence", "summary": "Maintain a foothold across restarts/credentials changes."},
    {"id": "TA0004", "name": "Privilege Escalation", "summary": "Gain higher-level permissions."},
    {"id": "TA0005", "name": "Defense Evasion", "summary": "Avoid being detected."},
    {"id": "TA0006", "name": "Credential Access", "summary": "Steal account names and passwords."},
    {"id": "TA0007", "name": "Discovery", "summary": "Figure out the environment."},
    {"id": "TA0008", "name": "Lateral Movement", "summary": "Move through the environment."},
    {"id": "TA0009", "name": "Collection", "summary": "Gather data of interest to the goal."},
    {"id": "TA0011", "name": "Command and Control", "summary": "Communicate with compromised systems."},
    {"id": "TA0010", "name": "Exfiltration", "summary": "Steal data."},
    {"id": "TA0040", "name": "Impact", "summary": "Manipulate, interrupt, or destroy systems and data."},
)
_TACTIC_BY_ID = {t["id"]: t for t in TACTICS}


# ── A curated set of representative ATT&CK techniques ────────────────────────────
# Real ATT&CK IDs/names; ``keywords`` drive the behavior→technique heuristic.
TECHNIQUES: tuple[dict, ...] = (
    {"id": "T1566", "name": "Phishing", "tactics": ["TA0001"],
     "summary": "Send malicious messages to gain access.",
     "keywords": ["phish", "phishing", "spear", "lure", "malicious email", "attachment link"]},
    {"id": "T1190", "name": "Exploit Public-Facing Application", "tactics": ["TA0001"],
     "summary": "Exploit a weakness in an Internet-facing host or app.",
     "keywords": ["exploit", "public-facing", "web app", "rce", "sql injection", "deserialization", "cve"]},
    {"id": "T1059", "name": "Command and Scripting Interpreter", "tactics": ["TA0002"],
     "summary": "Abuse shells/interpreters (bash, PowerShell, Python) to run code.",
     "keywords": ["shell", "powershell", "bash", "python", "interpreter", "script execution", "command"]},
    {"id": "T1053", "name": "Scheduled Task/Job", "tactics": ["TA0002", "TA0003", "TA0004"],
     "summary": "Use task scheduling (cron, at, schtasks) to run or persist code.",
     "keywords": ["cron", "scheduled task", "schtasks", "at job", "systemd timer", "persistence schedule"]},
    {"id": "T1543", "name": "Create or Modify System Process", "tactics": ["TA0003", "TA0004"],
     "summary": "Install or modify services/daemons to persist.",
     "keywords": ["service", "daemon", "systemd", "launchd", "persistence service", "new process"]},
    {"id": "T1548", "name": "Abuse Elevation Control Mechanism", "tactics": ["TA0004", "TA0005"],
     "summary": "Bypass sudo/UAC/setuid to elevate privileges.",
     "keywords": ["sudo", "uac", "setuid", "elevation", "privilege escalation", "bypass control"]},
    {"id": "T1027", "name": "Obfuscated Files or Information", "tactics": ["TA0005"],
     "summary": "Encode/encrypt/pack payloads to evade detection.",
     "keywords": ["obfuscate", "encode", "base64", "packed", "encrypt payload", "evade", "steganography"]},
    {"id": "T1110", "name": "Brute Force", "tactics": ["TA0006"],
     "summary": "Guess or spray credentials.",
     "keywords": ["brute force", "password spray", "credential stuffing", "guess password", "login attempts"]},
    {"id": "T1003", "name": "OS Credential Dumping", "tactics": ["TA0006"],
     "summary": "Dump credentials from the OS (LSASS, /etc/shadow, SAM).",
     "keywords": ["credential dump", "lsass", "mimikatz", "shadow file", "sam", "hashdump"]},
    {"id": "T1082", "name": "System Information Discovery", "tactics": ["TA0007"],
     "summary": "Enumerate host/OS details.",
     "keywords": ["enumerate", "discovery", "system info", "uname", "hostname", "recon host"]},
    {"id": "T1021", "name": "Remote Services", "tactics": ["TA0008"],
     "summary": "Use valid accounts over SSH/RDP/SMB to move laterally.",
     "keywords": ["ssh", "rdp", "smb", "lateral movement", "remote service", "winrm"]},
    {"id": "T1071", "name": "Application Layer Protocol", "tactics": ["TA0011"],
     "summary": "Blend C2 into web/DNS/mail protocols.",
     "keywords": ["c2", "command and control", "beacon", "http c2", "dns tunnel", "covert channel"]},
    {"id": "T1041", "name": "Exfiltration Over C2 Channel", "tactics": ["TA0010"],
     "summary": "Steal data back over the existing C2 channel.",
     "keywords": ["exfiltrate", "exfil", "data theft", "steal data", "upload stolen", "leak data"]},
    {"id": "T1486", "name": "Data Encrypted for Impact", "tactics": ["TA0040"],
     "summary": "Encrypt data to disrupt availability (ransomware).",
     "keywords": ["ransomware", "encrypt files", "ransom", "impact availability", "lock files"]},
)
_TECH_BY_ID = {t["id"]: t for t in TECHNIQUES}


# ── MITRE D3FEND defensive tactics + curated ATT&CK→countermeasure mapping ───────
D3FEND_TACTICS: tuple[dict, ...] = (
    {"id": "D3-MODEL", "name": "Model", "summary": "Inventory and understand assets and behavior."},
    {"id": "D3-HARDEN", "name": "Harden", "summary": "Reduce attack surface before compromise."},
    {"id": "D3-DETECT", "name": "Detect", "summary": "Identify adversary activity."},
    {"id": "D3-ISOLATE", "name": "Isolate", "summary": "Create barriers that limit reach."},
    {"id": "D3-DECEIVE", "name": "Deceive", "summary": "Mislead the adversary (decoys, honeypots)."},
    {"id": "D3-EVICT", "name": "Evict", "summary": "Remove the adversary from the environment."},
    {"id": "D3-RESTORE", "name": "Restore", "summary": "Return to a known-good state."},
)

# Curated countermeasures (D3FEND-aligned) keyed by ATT&CK technique id. Honest gaps
# are allowed — a technique with no entry simply reports "no curated countermeasures".
COUNTERMEASURES: dict[str, tuple[dict, ...]] = {
    "T1566": ({"id": "D3-MA", "name": "Message Analysis", "d3fend_tactic": "D3-DETECT"},
              {"id": "D3-UA", "name": "User Awareness Training", "d3fend_tactic": "D3-HARDEN"}),
    "T1190": ({"id": "D3-ACA", "name": "Application Configuration Hardening", "d3fend_tactic": "D3-HARDEN"},
              {"id": "D3-NTA", "name": "Network Traffic Analysis", "d3fend_tactic": "D3-DETECT"}),
    "T1059": ({"id": "D3-SEA", "name": "Script Execution Analysis", "d3fend_tactic": "D3-DETECT"},
              {"id": "D3-EAL", "name": "Executable Allowlisting", "d3fend_tactic": "D3-HARDEN"}),
    "T1053": ({"id": "D3-SJA", "name": "Scheduled Job Analysis", "d3fend_tactic": "D3-DETECT"},),
    "T1543": ({"id": "D3-PSA", "name": "Process Spawn Analysis", "d3fend_tactic": "D3-DETECT"},
              {"id": "D3-EAL", "name": "Executable Allowlisting", "d3fend_tactic": "D3-HARDEN"}),
    "T1548": ({"id": "D3-LFP", "name": "Local File Permissions", "d3fend_tactic": "D3-HARDEN"},
              {"id": "D3-PSA", "name": "Process Spawn Analysis", "d3fend_tactic": "D3-DETECT"}),
    "T1027": ({"id": "D3-FCA", "name": "File Content Analysis", "d3fend_tactic": "D3-DETECT"},),
    "T1110": ({"id": "D3-MFA", "name": "Multi-factor Authentication", "d3fend_tactic": "D3-HARDEN"},
              {"id": "D3-ANAA", "name": "Authentication Event Thresholding", "d3fend_tactic": "D3-DETECT"}),
    "T1003": ({"id": "D3-CH", "name": "Credential Hardening", "d3fend_tactic": "D3-HARDEN"},
              {"id": "D3-PSA", "name": "Process Spawn Analysis", "d3fend_tactic": "D3-DETECT"}),
    "T1082": ({"id": "D3-SFA", "name": "System File Analysis", "d3fend_tactic": "D3-DETECT"},),
    "T1021": ({"id": "D3-NI", "name": "Network Isolation", "d3fend_tactic": "D3-ISOLATE"},
              {"id": "D3-MFA", "name": "Multi-factor Authentication", "d3fend_tactic": "D3-HARDEN"}),
    "T1071": ({"id": "D3-NTA", "name": "Network Traffic Analysis", "d3fend_tactic": "D3-DETECT"},
              {"id": "D3-OTF", "name": "Outbound Traffic Filtering", "d3fend_tactic": "D3-ISOLATE"}),
    "T1041": ({"id": "D3-OTF", "name": "Outbound Traffic Filtering", "d3fend_tactic": "D3-ISOLATE"},
              {"id": "D3-NTA", "name": "Network Traffic Analysis", "d3fend_tactic": "D3-DETECT"}),
    "T1486": ({"id": "D3-FBA", "name": "File Backup & Restore", "d3fend_tactic": "D3-RESTORE"},
              {"id": "D3-FCA", "name": "File Content Analysis", "d3fend_tactic": "D3-DETECT"}),
}


# ── NIST CSF 2.0 functions (the six, complete) ───────────────────────────────────
CSF_FUNCTIONS: tuple[dict, ...] = (
    {"id": "GV", "name": "Govern", "summary": "Establish and monitor the cybersecurity risk strategy."},
    {"id": "ID", "name": "Identify", "summary": "Understand assets, risks, and the environment."},
    {"id": "PR", "name": "Protect", "summary": "Safeguards to ensure delivery of services."},
    {"id": "DE", "name": "Detect", "summary": "Find and analyze possible attacks and compromises."},
    {"id": "RS", "name": "Respond", "summary": "Take action on a detected incident."},
    {"id": "RC", "name": "Recover", "summary": "Restore assets and operations after an incident."},
)

# Which CSF functions a D3FEND defensive tactic primarily contributes to.
_D3FEND_TO_CSF: dict[str, tuple[str, ...]] = {
    "D3-MODEL": ("ID",), "D3-HARDEN": ("PR",), "D3-DETECT": ("DE",),
    "D3-ISOLATE": ("PR",), "D3-DECEIVE": ("DE",), "D3-EVICT": ("RS",), "D3-RESTORE": ("RC",),
}


# ── public API ───────────────────────────────────────────────────────────────────
def _meta() -> dict:
    return {"curated": True, "disclaimer": DISCLAIMER, "sources": SOURCES}


def tactics() -> dict:
    """ATT&CK enterprise tactics (complete: all 14)."""
    return {"tactics": list(TACTICS), "count": len(TACTICS), **_meta()}


def techniques(tactic: str | None = None) -> dict:
    """Curated ATT&CK techniques, optionally filtered to one tactic id (e.g. ``TA0002``)."""
    items = list(TECHNIQUES)
    if tactic:
        tactic = tactic.strip().upper()
        items = [t for t in items if tactic in t["tactics"]]
    pub = [{k: v for k, v in t.items() if k != "keywords"} for t in items]
    return {"techniques": pub, "count": len(pub), "tactic": tactic or None, **_meta()}


def technique(tid: str) -> dict | None:
    """One technique's detail, enriched with its D3FEND countermeasures + CSF functions.
    Returns ``None`` for an unknown id (the router maps that to 404)."""
    t = _TECH_BY_ID.get((tid or "").strip().upper())
    if t is None:
        return None
    pub = {k: v for k, v in t.items() if k != "keywords"}
    pub["tactic_names"] = [_TACTIC_BY_ID[x]["name"] for x in t["tactics"] if x in _TACTIC_BY_ID]
    cms = list(COUNTERMEASURES.get(t["id"], ()))
    pub["countermeasures"] = cms
    pub["csf_functions"] = sorted({
        f for cm in cms for f in _D3FEND_TO_CSF.get(cm["d3fend_tactic"], ())
    })
    return {"technique": pub, **_meta()}


def map_behavior(text: str, top_k: int = 5) -> dict:
    """Map a free-text behavior to candidate ATT&CK techniques via a keyword heuristic.

    Honest by construction: this is a transparent keyword match (the matched terms are
    returned as ``evidence``), NOT a classifier — it surfaces *candidates* to investigate
    and never asserts a definitive attribution. Empty input → no candidates.
    """
    text_l = (text or "").lower()
    top_k = max(1, min(int(top_k or 5), 20))
    scored: list[dict] = []
    if text_l.strip():
        for t in TECHNIQUES:
            hits = [kw for kw in t["keywords"] if kw in text_l]
            if hits:
                scored.append({
                    "id": t["id"], "name": t["name"],
                    "tactics": t["tactics"], "score": len(hits), "evidence": hits,
                })
    scored.sort(key=lambda c: (-c["score"], c["id"]))
    return {"candidates": scored[:top_k], "count": len(scored[:top_k]),
            "heuristic": "keyword-match", **_meta()}


def frameworks() -> dict:
    """Overview of the three frameworks: ATT&CK tactics, D3FEND tactics, CSF functions."""
    return {
        "attack_tactics": list(TACTICS),
        "d3fend_tactics": list(D3FEND_TACTICS),
        "csf_functions": list(CSF_FUNCTIONS),
        **_meta(),
    }


def build_playbook(technique_ids: list[str]) -> dict:
    """Assemble a defensive playbook for a set of ATT&CK techniques.

    For each *known* technique: the D3FEND countermeasures and the NIST CSF functions
    that address it. Unknown ids are reported under ``unknown`` (never silently dropped),
    and a technique with no curated countermeasure is reported with an explicit gap — the
    pack states what it does NOT cover rather than fabricating coverage. ``generated:
    false`` marks this as a curated assembly, not AI-authored advice.
    """
    items: list[dict] = []
    unknown: list[str] = []
    covered_csf: set[str] = set()
    for raw in technique_ids or []:
        tid = (raw or "").strip().upper()
        t = _TECH_BY_ID.get(tid)
        if t is None:
            unknown.append(raw)
            continue
        cms = list(COUNTERMEASURES.get(tid, ()))
        csf = sorted({f for cm in cms for f in _D3FEND_TO_CSF.get(cm["d3fend_tactic"], ())})
        covered_csf.update(csf)
        items.append({
            "id": tid, "name": t["name"], "tactics": t["tactics"],
            "countermeasures": cms, "csf_functions": csf,
            "gap": not cms,  # honest: True when we have no curated countermeasure
        })
    return {
        "playbook": items,
        "unknown": unknown,
        "csf_coverage": sorted(covered_csf),
        "csf_gaps": [f["id"] for f in CSF_FUNCTIONS if f["id"] not in covered_csf],
        "generated": False,
        **_meta(),
    }
