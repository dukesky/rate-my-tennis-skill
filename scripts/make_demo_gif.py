#!/usr/bin/env python3
"""Render the red -> green correction animation of report evidence as a GIF (for the README).

  python scripts/make_demo_gif.py REPORT_JSON ANALYSIS_DIR OUT.gif "issue_index:evidence_index" [...]
"""
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins", "rate-my-tennis",
                                "skills", "rate-my-tennis", "scripts"))
import build_report as br  # noqa: E402

rep_path, an_dir, out = sys.argv[1:4]
picks = [tuple(int(v) for v in p.split(":")) for p in sys.argv[4:]]
rep = json.load(open(rep_path, encoding="utf-8"))
an = br.Analysis(an_dir)
H = 440


def panel_frames(ev, fracs):
    sid = ev["swing"]
    fno = an.frame_no(sid, ev.get("frame", "contact"), ev.get("offset", 0))
    img, lm = an.image(sid, fno), an.landmarks(sid, fno)
    h, w = img.shape[:2]
    prims, T = br.marks_to_prims(ev.get("marks"), lm, w, h)
    box = [int(v) for v in br.auto_view(prims, lm, T, w, h)]
    frames = []
    for f in fracs:
        ps = []
        for p in prims:
            q = dict(p)
            if p["k"] in ("ghost_rot", "ghost_chain"):
                q["delta"] = p["delta"] * f
                if f < 0.98:
                    q["text"] = None          # the target label appears once the ghost arrives
            elif p["k"] == "ghost_move":
                q["b"] = p["a"] + (p["b"] - p["a"]) * max(f, 0.02)
                if f < 0.98:
                    q["text"] = None
            ps.append(q)
        im = br.bake(img, ps, T, box)[box[1]:box[3], box[0]:box[2]]
        frames.append(cv2.resize(im, (int(im.shape[1] * H / im.shape[0]), H), interpolation=cv2.INTER_AREA))
    return frames


ease = [0.5 - 0.5 * np.cos(np.pi * t) for t in np.linspace(0, 1, 14)]
fracs = [0.0] * 6 + ease + [1.0] * 12
panels = [panel_frames(rep["issues"][i]["evidence"][j], fracs) for i, j in picks]
gap = np.full((H, 10, 3), 255, np.uint8)
frames = []
for k in range(len(fracs)):
    row = panels[0][k]
    for p in panels[1:]:
        row = np.concatenate([row, gap, p[k]], axis=1)
    frames.append(Image.fromarray(cv2.cvtColor(row, cv2.COLOR_BGR2RGB)).quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
frames[0].save(out, save_all=True, append_images=frames[1:], duration=70, loop=0, optimize=True)
print("wrote %s  %dx%d  %d frames  %.1f MB" % (out, frames[0].width, frames[0].height, len(frames), os.path.getsize(out) / 1e6))
