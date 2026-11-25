"""Summarise qa-render2 reports under a run folder.

usage: python -I qa-summary.py <run-dir> [<out.md>]
Prints, per job: frames, errors, and the worst frames for each metric with samples.
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
run = Path(sys.argv[1])
out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
lines = []
p = lines.append

frames = []
for rep in sorted(run.glob("*/report.json")):
    job = rep.parent.name
    for e in json.loads(rep.read_text(encoding="utf-8")):
        e["job"] = job
        frames.append(e)

p(f"# QA summary for {run}\n\nframes: {len(frames)}")
bad_load = [f for f in frames if not f.get("ok")]
p(f"failed loads: {len(bad_load)}")
for f in bad_load[:20]:
    p(f"- {f['job']} {f['look']}-{f['scheme']} {f['route']}: {str(f.get('error'))[:200]}")

wrong_look = [f for f in frames if f.get("ok") and (f.get("htmlLook") != f["look"] or f.get("htmlScheme") != f["scheme"])]
p(f"\nframes whose <html> did not take the chosen look/scheme: {len(wrong_look)}")
for f in wrong_look[:10]:
    p(f"- {f['look']}-{f['scheme']} {f['route']}: html={f.get('htmlLook')}/{f.get('htmlScheme')}")

def top(metric, label, sample_key=None, n=25, only_nerva=False):
    rows = [f for f in frames if f.get("ok") and (f.get(metric) or 0) > 0 and not (only_nerva and f["look"] in ("obsidian", "graphite"))]
    rows.sort(key=lambda f: -(f.get(metric) or 0))
    total = sum(f.get(metric) or 0 for f in rows)
    p(f"\n## {label}: {len(rows)} frames, {total} total")
    by_look = Counter()
    for f in rows:
        by_look[f"{f['look']}-{f['scheme']}"] += f.get(metric) or 0
    p("by look: " + ", ".join(f"{k} {v}" for k, v in by_look.most_common()))
    for f in rows[:n]:
        s = ""
        if sample_key and f.get(sample_key):
            s = " | " + " ; ".join(str(x) for x in f[sample_key][:4])
        p(f"- {f[metric]:>4} {f['look']}-{f['scheme']} {f['route']}{s}")
    # most common samples across frames (by selector prefix)
    if sample_key:
        sel = Counter()
        for f in rows:
            for x in f.get(sample_key) or []:
                sel[str(x).split(' ')[0][:80]] += 1
        p("most frequent elements: " + "; ".join(f"{k} ×{v}" for k, v in sel.most_common(15)))

top("under12", "visible text under 12px", "under12Samples")
top("classicLeaks", "Classic colour leaks in Nerva looks", "leakSamples", only_nerva=True)
top("whiteControls", "white platform controls on dark", "whiteSamples")
top("contrastFails", "axe colour-contrast failures", "contrastSamples")
ovf = [f for f in frames if f.get("hOverflow")]
p(f"\n## horizontal overflow: {len(ovf)} frames")
for f in ovf[:25]:
    p(f"- {f['look']}-{f['scheme']} {f['route']}")
errs = [f for f in frames if f.get("errors")]
p(f"\n## frames with page/console errors: {len(errs)}")
msg = Counter()
for f in errs:
    for m in f["errors"]:
        msg[m[:140]] += 1
for m, c in msg.most_common(15):
    p(f"- ×{c} {m}")
small = Counter()
for f in frames:
    if f.get("ok") and f.get("smallest") is not None:
        small[f["smallest"]] += 1
p("\nsmallest font distribution: " + ", ".join(f"{k}px ×{v}" for k, v in sorted(small.items())))

text = "\n".join(lines)
print(text)
if out:
    out.write_text(text + "\n", encoding="utf-8")
