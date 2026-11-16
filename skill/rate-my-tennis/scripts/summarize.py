#!/usr/bin/env python3
"""Rate My Tennis - metric averages per stroke, using the labels YOU confirmed by eye.

  python summarize.py OUT_DIR --labels "1:forehand,2:serve,4:forehand,18:backhand,44:skip"

Prints mean / spread / range of every metric per stroke type, and saves labels into analysis.json.
Swings you do not list are left out (same as "skip"), so list every swing you want counted.
"""
import argparse
import json
import os

ap = argparse.ArgumentParser()
ap.add_argument("analysis_dir")
ap.add_argument("--labels", required=True)
a = ap.parse_args()
path = os.path.join(a.analysis_dir, "analysis.json")
with open(path) as f:
    data = json.load(f)
labels = {int(k): v.strip() for k, v in (x.split(":") for x in a.labels.split(",") if x.strip())}
groups = {}
for s in data["swings"]:
    lab = labels.get(s["id"], "skip")
    s["label"] = lab
    if s.get("metrics") and lab != "skip":
        groups.setdefault(lab, []).append(s)
out = {}
for lab, ss in sorted(groups.items()):
    print("\n== %s  (n=%d, swings %s)" % (lab, len(ss), [s["id"] for s in ss]))
    out[lab] = {"count": len(ss), "swings": [s["id"] for s in ss]}
    for k in ss[0]["metrics"]:
        vals = [s["metrics"][k] for s in ss if isinstance(s["metrics"][k], (int, float)) and not isinstance(s["metrics"][k], bool)]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        out[lab][k] = {"mean": round(mean, 2), "sd": round(sd, 2), "min": min(vals), "max": max(vals)}
        print("  %-30s mean %7.2f   sd %6.2f   range %g .. %g" % (k, mean, sd, min(vals), max(vals)))
data["aggregate_by_label"] = out
with open(path, "w") as f:
    json.dump(data, f, indent=1)
