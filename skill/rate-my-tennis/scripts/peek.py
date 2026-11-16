#!/usr/bin/env python3
"""Rate My Tennis - look closely at one cached frame, with a coordinate grid.

  python peek.py OUT_DIR SWING FRAME [--offset N] [--no-grid] [--skeleton] [-o peek.jpg]
  python peek.py OUT_DIR SWING contact --seq -0.2 0.3      # montage of every cached frame in that time window

FRAME is a phase name (ready|backswing|forward|contact|extension|finish) or a frame number.
--offset steps N cached frames earlier (-) or later (+).
--seq FROM TO (seconds relative to FRAME) writes a labelled montage instead - use it to find the true contact
frame when the detected one looks wrong; each tile shows its frame number, usable as "frame" in report.json.
The grid is labelled in fractions (0.0-1.0) of the frame: use those numbers for [x, y] points in marks
(e.g. to circle the ball or the racket head, which have no landmark).
"""
import argparse
import json
import os

import cv2

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("analysis_dir")
ap.add_argument("swing", type=int)
ap.add_argument("frame")
ap.add_argument("--offset", type=int, default=0)
ap.add_argument("--seq", nargs=2, type=float, metavar=("FROM", "TO"))
ap.add_argument("--no-grid", action="store_true")
ap.add_argument("--skeleton", action="store_true")
ap.add_argument("-o", "--out", default="")
a = ap.parse_args()
with open(os.path.join(a.analysis_dir, "analysis.json")) as f:
    data = json.load(f)
s = next(x for x in data["swings"] if x["id"] == a.swing)
fno = s["phases"][a.frame] if a.frame in s["phases"] else int(a.frame)
frames = s["frames"]
i = min(range(len(frames)), key=lambda k: abs(frames[k] - fno))
fno = frames[max(0, min(len(frames) - 1, i + a.offset))]
if a.seq:
    import numpy as np
    fps = data["video"]["fps"]
    pick = [f for f in frames if a.seq[0] <= (f - fno) / fps <= a.seq[1]]
    pick = pick[::max(1, -(-len(pick) // 12))]
    tiles = []
    for f in pick:
        im = cv2.imread(os.path.join(a.analysis_dir, s["dir"], "f%06d.jpg" % f))
        im = cv2.resize(im, (int(im.shape[1] * 300 / im.shape[0]), 300))
        txt = "f%d  %+.2fs" % (f, (f - s["phases"]["contact"]) / fps)
        cv2.rectangle(im, (0, 0), (190, 24), (20, 20, 20), -1)
        cv2.putText(im, txt, (5, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (120, 255, 255), 1, cv2.LINE_AA)
        tiles.append(im)
    cols = min(4, len(tiles))
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    sheet = np.concatenate([np.concatenate(tiles[k:k + cols], axis=1) for k in range(0, len(tiles), cols)], axis=0)
    out = a.out or os.path.join(a.analysis_dir, "peek_s%02d_seq.jpg" % a.swing)
    cv2.imwrite(out, sheet)
    print("%s  (swing %d, %d frames; times are relative to the detected contact)" % (out, a.swing, len(pick)))
    raise SystemExit
img = cv2.imread(os.path.join(a.analysis_dir, s["dir"], "f%06d.jpg" % fno))
h, w = img.shape[:2]
if a.skeleton:
    with open(os.path.join(a.analysis_dir, s["dir"], "landmarks.json")) as f:
        lm = json.load(f)["frames"].get(str(fno))
    if lm:
        for p, q in [(11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24), (23, 25), (25, 27), (24, 26), (26, 28)]:
            if lm[p][2] > 0.3 and lm[q][2] > 0.3:
                cv2.line(img, (int(lm[p][0]), int(lm[p][1])), (int(lm[q][0]), int(lm[q][1])), (255, 220, 90), 2, cv2.LINE_AA)
if not a.no_grid:
    for k in range(1, 10):
        x, y = int(w * k / 10), int(h * k / 10)
        cv2.line(img, (x, 0), (x, h), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(img, (0, y), (w, y), (255, 255, 255), 1, cv2.LINE_AA)
        for org, txt in (((x + 3, 14), "%.1f" % (k / 10)), ((3, y - 4), "%.1f" % (k / 10))):
            cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
out = a.out or os.path.join(a.analysis_dir, "peek_s%02d_%s.jpg" % (a.swing, fno))
cv2.imwrite(out, img)
t = (fno - s["phases"]["contact"]) / data["video"]["fps"]
print("%s  (swing %d, frame %d, %+.2fs from contact, %dx%d)" % (out, a.swing, fno, t, w, h))
