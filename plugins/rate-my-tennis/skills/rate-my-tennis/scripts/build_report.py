#!/usr/bin/env python3
"""Rate My Tennis - step 2: turn the coach's findings (report.json) into an illustrated report.

  python build_report.py report.json --analysis OUT_DIR --out report.html
         [--previous old_report.html|tennis-progress.json] [--export-images DIR]

Outputs
  report.html            self-contained (images embedded, works offline, printable)
  tennis-progress.json   small file to keep; pass it as --previous next time to see progress
  DIR/issue_*.jpg        (optional) annotated stills, for showing inline in a chat

report.json schema: see references/report-schema.md
"""
import argparse
import base64
import datetime
import html
import json
import math
import os
import re
import sys

import cv2
import numpy as np

LM = {
    "nose": 0, "left_shoulder": 11, "right_shoulder": 12, "left_elbow": 13, "right_elbow": 14,
    "left_wrist": 15, "right_wrist": 16, "left_hip": 23, "right_hip": 24, "left_knee": 25,
    "right_knee": 26, "left_ankle": 27, "right_ankle": 28, "left_heel": 29, "right_heel": 30,
    "left_foot": 31, "right_foot": 32,
}
BONES = [(11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24),
         (23, 25), (25, 27), (24, 26), (26, 28), (27, 31), (28, 32)]
JOINT_TRIPLES = {  # joint -> (proximal neighbour, joint, distal neighbour)
    "elbow": ("shoulder", "elbow", "wrist"), "knee": ("hip", "knee", "ankle"),
    "shoulder": ("hip", "shoulder", "elbow"), "hip": ("shoulder", "hip", "knee"),
}
COLORS = {"bad": "#ff5a3c", "good": "#16c172", "info": "#ffd23f", "white": "#ffffff"}

L10N = {
    "en": dict(title="Tennis Technique Report", overall="Overall", level="Estimated level", dims="Skill radar",
               strokes="Stroke by stroke", strengths="What you already do well", issues="Top things to fix",
               what="What we see", why="Why it matters", fix="How to fix it", cue="Cue", drills="Drills",
               now="Now", target="Target", flip="Your swing in slow motion", plan="Training plan",
               metrics="Measured numbers", progress="Progress since last report", tips="For your next recording",
               swings="swings", play="Play", pause="Pause", legend_now="red = now", legend_target="green = target",
               metric="Metric", you="You", ref="Reference", prev="Last time", disclaimer=(
                   "This report is produced by AI from a single camera. Angles and scores are estimates, "
                   "not measurements, and no substitute for a coach who can watch you live. "
                   "Stop any drill that causes pain."),
               high="Fix first", med="Important", low="Polish", shots="shots", confidence="confidence",
               frame="frame", speed="Speed", first_report="First report - record again in 2-4 weeks to see your progress here."),
    "zh": dict(title="网球技术评估报告", overall="综合评分", level="水平估计", dims="能力雷达", strokes="分项技术",
               strengths="你已经做得好的地方", issues="最值得优先改进的问题", what="看到了什么", why="为什么重要",
               fix="怎么改", cue="口诀", drills="练习方法", now="现在", target="目标", flip="你的挥拍慢动作",
               plan="训练计划", metrics="测量数据", progress="与上次相比的进步", tips="下次录像建议",
               swings="次挥拍", play="播放", pause="暂停", legend_now="红色 = 现在", legend_target="绿色 = 目标",
               metric="指标", you="你", ref="参考范围", prev="上次", disclaimer=(
                   "本报告由 AI 基于单机位视频生成，角度与评分均为估计值而非精确测量，不能替代现场教练的指导。"
                   "任何练习如引起疼痛请立即停止。"),
               high="优先解决", med="重要", low="细节打磨", shots="次", confidence="置信度", frame="帧", speed="速度",
               first_report="这是第一份报告——2到4周后再录一次，这里会显示你的进步。"),
}


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def rich(s):
    """Escape, then allow **bold** and newlines."""
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return s.replace("\n", "<br>")


# ----------------------------------------------------------------------------- evidence frames
class Analysis:
    def __init__(self, d):
        self.dir = d
        with open(os.path.join(d, "analysis.json")) as f:
            self.data = json.load(f)
        self.swings = {s["id"]: s for s in self.data["swings"]}
        self._lm = {}

    def swing(self, sid):
        if sid not in self.swings:
            sys.exit("ERROR: report references swing %s, not in analysis.json (have %s)" % (sid, sorted(self.swings)))
        return self.swings[sid]

    def frame_no(self, sid, frame, offset=0):
        s = self.swing(sid)
        fno = s["phases"][frame] if isinstance(frame, str) else int(frame)
        frames = s["frames"]
        i = min(range(len(frames)), key=lambda k: abs(frames[k] - fno))
        return frames[max(0, min(len(frames) - 1, i + int(offset)))]

    def image(self, sid, fno):
        return cv2.imread(os.path.join(self.dir, self.swing(sid)["dir"], "f%06d.jpg" % fno))

    def landmarks(self, sid, fno):
        if sid not in self._lm:
            with open(os.path.join(self.dir, self.swing(sid)["dir"], "landmarks.json")) as f:
                self._lm[sid] = json.load(f)["frames"]
        v = self._lm[sid].get(str(fno))
        return np.array(v, dtype=float) if v else None


def jpeg_b64(img, max_w=720, q=80):
    h, w = img.shape[:2]
    if w > max_w:
        img = cv2.resize(img, (max_w, int(h * max_w / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


# ----------------------------------------------------------------------------- marks -> primitives
def resolve(pt, lm, w, h):
    if isinstance(pt, (list, tuple)):
        return np.array([pt[0] * w, pt[1] * h], float)
    if lm is None:
        raise ValueError("no pose landmarks for this frame - give points as [x, y] fractions")
    if pt == "mid_hip":
        return (lm[23, :2] + lm[24, :2]) / 2
    if pt == "mid_shoulder":
        return (lm[11, :2] + lm[12, :2]) / 2
    if pt == "head":
        return lm[0, :2]
    if pt in LM:
        return lm[LM[pt], :2].copy()
    raise ValueError("unknown point %r" % (pt,))


def torso(lm, h):
    if lm is None:
        return 0.25 * h
    return max(20.0, float(np.linalg.norm((lm[11, :2] + lm[12, :2]) / 2 - (lm[23, :2] + lm[24, :2]) / 2)))


def joint_points(joint, lm, w, h):
    side, name = joint.split("_", 1)
    a, j, c = JOINT_TRIPLES[name]
    return [resolve("%s_%s" % (side, n), lm, w, h) for n in (a, j, c)]


def marks_to_prims(marks, lm, w, h):
    """Convert high-level marks (named joints, torso-length units) into drawable primitives in pixels."""
    T = torso(lm, h)
    prims = []
    for m in marks or []:
        k = m["type"]
        col = COLORS.get(m.get("color", ""), m.get("color")) if m.get("color") else None
        txt = m.get("text")
        if k in ("angle", "target_angle"):
            A, J, C = joint_points(m["joint"], lm, w, h)
            c1 = col or COLORS["bad"]
            prims += [dict(k="line", a=A, b=J, color=c1, w=1.0), dict(k="line", a=J, b=C, color=c1, w=1.0)]
            a0, a1 = math.atan2(*(A - J)[::-1]), math.atan2(*(C - J)[::-1])
            prims.append(dict(k="arc", c=J, r=0.2 * T, a0=a0, a1=a1, color=c1))
            if txt:
                mid = (A - J) / (np.linalg.norm(A - J) + 1e-6) + (C - J) / (np.linalg.norm(C - J) + 1e-6)
                n = np.linalg.norm(mid)
                d = mid / n if n > 0.2 else np.array([1.0, 0.0])
                prims.append(dict(k="text", p=J + d * 0.42 * T, text=txt, color=c1))
            if k == "target_angle":
                cur = math.degrees((a1 - a0 + math.pi) % (2 * math.pi) - math.pi)  # signed A->C
                tgt = math.copysign(float(m["target"]), cur if abs(cur) > 1 else 1)
                if m.get("move", "distal") == "distal":
                    prims.append(dict(k="ghost_rot", pivot=J, end=C, delta=tgt - cur, color=COLORS["good"],
                                      text=m.get("target_text")))
                else:
                    prims.append(dict(k="ghost_rot", pivot=J, end=A, delta=-(tgt - cur), color=COLORS["good"],
                                      text=m.get("target_text")))
        elif k == "rotate":
            # swing a whole chain (e.g. the arm, or the trunk) about a pivot: the "do this instead" ghost
            Pv = resolve(m["pivot"], lm, w, h)
            pts = [resolve(q, lm, w, h) for q in m["chain"]]
            deg = abs(float(m.get("deg", 20)))
            tw = m.get("toward", "up")
            goal = {"up": np.array([0, -1.0]), "down": np.array([0, 1.0]), "left": np.array([-1.0, 0]),
                    "right": np.array([1.0, 0])}.get(tw) if isinstance(tw, str) else None
            if goal is None:
                goal = resolve(tw, lm, w, h) - Pv
            goal = goal / (np.linalg.norm(goal) + 1e-6)
            end = pts[-1] - Pv
            score = {sg: float(np.dot((rot(pts[-1], Pv, sg * deg) - Pv) / (np.linalg.norm(end) + 1e-6), goal)) for sg in (1, -1)}
            delta = deg * max(score, key=score.get)
            c1 = col or COLORS["bad"]
            chain = [Pv] + pts
            for a_, b_ in zip(chain[:-1], chain[1:]):
                prims.append(dict(k="line", a=a_, b=b_, color=c1, w=1.0))
            if txt:
                prims.append(dict(k="text", p=(chain[0] + chain[-1]) / 2 + np.array([0, -0.12 * T]), text=txt, color=c1))
            prims.append(dict(k="ghost_chain", pivot=Pv, pts=pts, delta=delta, color=COLORS["good"], text=m.get("target_text")))
        elif k == "move":
            P = resolve(m["point"], lm, w, h)
            Q = P + np.array([m.get("dx", 0), m.get("dy", 0)], float) * T
            prims.append(dict(k="ghost_move", a=P, b=Q, r=0.09 * T, color=COLORS["good"], text=txt))
        elif k == "circle":
            P = resolve(m["at"], lm, w, h)
            prims.append(dict(k="circle", c=P, r=m.get("r", 0.18) * T, color=col or COLORS["bad"]))
            if txt:
                prims.append(dict(k="text", p=P + np.array([0, -(m.get("r", 0.18) + 0.14) * T]), text=txt,
                                  color=col or COLORS["bad"]))
        elif k == "arrow":
            P = resolve(m["from"], lm, w, h)
            Q = resolve(m["to"], lm, w, h) if "to" in m else P + np.array([m.get("dx", 0), m.get("dy", 0)], float) * T
            prims.append(dict(k="arrow", a=P, b=Q, color=col or COLORS["good"]))
            if txt:
                prims.append(dict(k="text", p=Q + (Q - P) / (np.linalg.norm(Q - P) + 1e-6) * 0.34 * T + np.array([0, 0.05 * T]),
                                  text=txt, color=col or COLORS["good"]))
        elif k == "line":
            P, Q = resolve(m["from"], lm, w, h), resolve(m["to"], lm, w, h)
            e = float(m.get("extend", 0))
            P, Q = P - (Q - P) * e, Q + (Q - P) * e
            prims.append(dict(k="line", a=P, b=Q, color=col or COLORS["info"], w=0.8, dash=m.get("dash", False)))
            if txt:
                prims.append(dict(k="text", p=Q + np.array([0, -0.1 * T]), text=txt, color=col or COLORS["info"]))
        elif k == "plumb":
            P = resolve(m["at"], lm, w, h)
            prims.append(dict(k="line", a=np.array([P[0], P[1] - 0.3 * T]), b=np.array([P[0], h * 0.98]),
                              color=col or COLORS["info"], w=0.6, dash=True))
            if txt:
                prims.append(dict(k="text", p=np.array([P[0], P[1] - 0.42 * T]), text=txt, color=col or COLORS["info"]))
        elif k == "label":
            prims.append(dict(k="text", p=resolve(m["at"], lm, w, h) + np.array([m.get("dx", 0), m.get("dy", 0)], float) * T,
                              text=txt, color=col or COLORS["white"]))
        else:
            raise ValueError("unknown mark type %r" % k)
    return prims, T


def rot(p, pivot, deg):
    a = math.radians(deg)
    d = p - pivot
    return pivot + np.array([d[0] * math.cos(a) - d[1] * math.sin(a), d[0] * math.sin(a) + d[1] * math.cos(a)])


def prims_to_svg(prims, T, w, h, lm=None, skeleton=False, view=None):
    sw = max(2.5, T * 0.035)
    fs = max(13, T * 0.15)
    if view:  # keep labels readable when zoomed out, never huge when zoomed in
        fs = min(max(fs, (view[2] - view[0]) * 0.034), (view[2] - view[0]) * 0.05)
    o = ['<svg class="ov" viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg">' % (w, h)]
    o.append('<defs><marker id="ah" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" '
             'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="context-stroke"/></marker></defs>')
    if skeleton and lm is not None:
        for a, b in BONES:
            if lm[a, 2] > 0.3 and lm[b, 2] > 0.3:
                o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#fff" stroke-opacity=".55" stroke-width="%.1f" '
                         'stroke-linecap="round"/>' % (lm[a, 0], lm[a, 1], lm[b, 0], lm[b, 1], sw * 0.6))
    dur = "3.2s"
    texts = []
    for p in prims:
        k, c = p["k"], p.get("color", "#fff")
        if k == "line":
            o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%.1f" stroke-linecap="round"%s/>'
                     % (p["a"][0], p["a"][1], p["b"][0], p["b"][1], c, sw * p.get("w", 1),
                        ' stroke-dasharray="%.0f %.0f"' % (sw * 2.4, sw * 2.4) if p.get("dash") else ""))
        elif k == "arc":
            d = (p["a1"] - p["a0"] + math.pi) % (2 * math.pi) - math.pi
            x0, y0 = p["c"][0] + p["r"] * math.cos(p["a0"]), p["c"][1] + p["r"] * math.sin(p["a0"])
            x1, y1 = p["c"][0] + p["r"] * math.cos(p["a0"] + d), p["c"][1] + p["r"] * math.sin(p["a0"] + d)
            o.append('<path d="M%.1f,%.1f A%.1f,%.1f 0 0 %d %.1f,%.1f" fill="none" stroke="%s" stroke-width="%.1f"/>'
                     % (x0, y0, p["r"], p["r"], 1 if d > 0 else 0, x1, y1, c, sw * 0.7))
        elif k == "circle":
            o.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" stroke-width="%.1f"/>'
                     % (p["c"][0], p["c"][1], p["r"], c, sw * 0.8))
        elif k == "arrow":
            o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%.1f" stroke-linecap="round" '
                     'marker-end="url(#ah)"/>' % (p["a"][0], p["a"][1], p["b"][0], p["b"][1], c, sw))
        elif k == "ghost_rot":
            pv, e = p["pivot"], p["end"]
            anim = ('<animateTransform attributeName="transform" type="rotate" dur="%s" repeatCount="indefinite" '
                    'values="0 %.1f %.1f;0 %.1f %.1f;%.1f %.1f %.1f;%.1f %.1f %.1f" keyTimes="0;0.15;0.6;1" '
                    'calcMode="spline" keySplines="0 0 1 1;.4 0 .2 1;0 0 1 1"/>'
                    % (dur, pv[0], pv[1], pv[0], pv[1], p["delta"], pv[0], pv[1], p["delta"], pv[0], pv[1]))
            o.append('<g>%s<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%.1f" stroke-linecap="round" '
                     'stroke-dasharray="%.0f %.0f"/><circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="#fff" stroke-width="2"/></g>'
                     % (anim, pv[0], pv[1], e[0], e[1], c, sw * 1.25, sw * 2.2, sw * 1.6, e[0], e[1], sw * 1.5, c))
            if p.get("text"):
                texts.append((rot(e, pv, p["delta"]) + np.array([0, -0.16 * T]), p["text"], c))
        elif k == "ghost_chain":
            pv = p["pivot"]
            anim = ('<animateTransform attributeName="transform" type="rotate" dur="%s" repeatCount="indefinite" '
                    'values="0 %.1f %.1f;0 %.1f %.1f;%.1f %.1f %.1f;%.1f %.1f %.1f" keyTimes="0;0.15;0.6;1" '
                    'calcMode="spline" keySplines="0 0 1 1;.4 0 .2 1;0 0 1 1"/>'
                    % (dur, pv[0], pv[1], pv[0], pv[1], p["delta"], pv[0], pv[1], p["delta"], pv[0], pv[1]))
            poly = " ".join("%.1f,%.1f" % (q[0], q[1]) for q in [pv] + p["pts"])
            dots = "".join('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="#fff" stroke-width="2"/>' % (q[0], q[1], sw * 1.4, c)
                           for q in p["pts"])
            o.append('<g>%s<polyline points="%s" fill="none" stroke="%s" stroke-width="%.1f" stroke-linecap="round" '
                     'stroke-linejoin="round" stroke-dasharray="%.0f %.0f"/>%s</g>' % (anim, poly, c, sw * 1.25, sw * 2.2, sw * 1.6, dots))
            if p.get("text"):
                texts.append((rot(p["pts"][-1], pv, p["delta"]) + np.array([0, -0.16 * T]), p["text"], c))
        elif k == "ghost_move":
            a, b = p["a"], p["b"]
            o.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%.1f" stroke-dasharray="%.0f %.0f" '
                     'marker-end="url(#ah)"/>' % (a[0], a[1], b[0], b[1], c, sw * 0.8, sw * 2, sw * 2))
            o.append('<circle r="%.1f" fill="%s" fill-opacity=".35" stroke="%s" stroke-width="%.1f">'
                     '<animate attributeName="cx" dur="%s" repeatCount="indefinite" values="%.1f;%.1f;%.1f;%.1f" keyTimes="0;0.15;0.6;1"/>'
                     '<animate attributeName="cy" dur="%s" repeatCount="indefinite" values="%.1f;%.1f;%.1f;%.1f" keyTimes="0;0.15;0.6;1"/>'
                     '</circle>' % (p["r"], c, c, sw * 0.8, dur, a[0], a[0], b[0], b[0], dur, a[1], a[1], b[1], b[1]))
            if p.get("text"):
                texts.append((b + np.array([0, -p["r"] - 0.08 * T]), p["text"], c))
        elif k == "text":
            texts.append((p["p"], p["text"], c))
    placed = []
    x0, y0, x1, y1 = view or (0, 0, w, h)
    for pos, text, c in texts:  # text last so it sits on top; keep inside the view and off other labels
        tw_ = sum(fs * (1.0 if ord(ch) > 0x2E7F else 0.58) for ch in str(text)) + fs * 0.7
        th_ = fs * 1.45
        x = min(max(pos[0], x0 + tw_ / 2 + 3), x1 - tw_ / 2 - 3)
        y = min(max(pos[1], y0 + th_ + 2), y1 - 6)
        for _ in range(12):
            hit = [q for q in placed if abs(q[0] - x) < (q[2] + tw_) / 2 and abs(q[1] - y) < th_ * 1.02]
            if not hit:
                break
            y = hit[0][1] + th_ * 1.08 if y + th_ * 1.1 < y1 - 6 else hit[0][1] - th_ * 1.08
        placed.append((x, y, tw_))
        o.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%.1f" fill="rgba(12,20,16,.78)"/>'
                 % (x - tw_ / 2, y - th_ * 0.76, tw_, th_, th_ * 0.3))
        o.append('<text x="%.1f" y="%.1f" font-size="%.1f" text-anchor="middle" fill="%s" class="ovt">%s</text>'
                 % (x, y, fs, c, esc(text)))
    o.append("</svg>")
    return "".join(o)


def bake(img, prims, T, view=None):
    """Draw primitives into the image (static version: ghosts at their target). ASCII-safe text only."""
    def col(c):
        c = c.lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (4, 2, 0))

    def P(p):
        return int(round(p[0])), int(round(p[1]))

    sw = max(2, int(T * 0.035))
    out = img.copy()

    def dashed(a, b, c, t):
        n = max(2, int(np.linalg.norm(b - a) / (sw * 5)))
        for i in range(n):
            if i % 2 == 0:
                cv2.line(out, P(a + (b - a) * i / n), P(a + (b - a) * (i + 1) / n), c, t, cv2.LINE_AA)

    labels = []

    def text(p, s, c):
        labels.append((p, str(s), c))

    for p in prims:
        k, c = p["k"], col(p.get("color", "#ffffff"))
        if k == "line":
            (dashed if p.get("dash") else lambda a, b, c_, t: cv2.line(out, P(a), P(b), c_, t, cv2.LINE_AA))(p["a"], p["b"], c, sw)
        elif k == "arc":
            d = (p["a1"] - p["a0"] + math.pi) % (2 * math.pi) - math.pi
            pts = [p["c"] + p["r"] * np.array([math.cos(p["a0"] + d * i / 20), math.sin(p["a0"] + d * i / 20)]) for i in range(21)]
            cv2.polylines(out, [np.array([P(q) for q in pts], np.int32)], False, c, max(1, sw - 1), cv2.LINE_AA)
        elif k == "circle":
            cv2.circle(out, P(p["c"]), int(p["r"]), c, sw, cv2.LINE_AA)
        elif k == "arrow":
            cv2.arrowedLine(out, P(p["a"]), P(p["b"]), c, sw, cv2.LINE_AA, tipLength=0.25)
        elif k == "ghost_rot":
            e = rot(p["end"], p["pivot"], p["delta"])
            dashed(p["pivot"], e, c, sw + 1)
            cv2.circle(out, P(e), sw + 3, c, -1, cv2.LINE_AA)
            if p.get("text"):
                text(e + np.array([0, -0.16 * T]), p["text"], c)
        elif k == "ghost_chain":
            pts = [p["pivot"]] + [rot(q, p["pivot"], p["delta"]) for q in p["pts"]]
            for a_, b_ in zip(pts[:-1], pts[1:]):
                dashed(a_, b_, c, sw + 1)
                cv2.circle(out, P(b_), sw + 2, c, -1, cv2.LINE_AA)
            if p.get("text"):
                text(pts[-1] + np.array([0, -0.16 * T]), p["text"], c)
        elif k == "ghost_move":
            cv2.arrowedLine(out, P(p["a"]), P(p["b"]), c, sw, cv2.LINE_AA, tipLength=0.2)
            cv2.circle(out, P(p["b"]), int(p["r"]), c, sw, cv2.LINE_AA)
            if p.get("text"):
                text(p["b"] + np.array([0, -p["r"] - 0.08 * T]), p["text"], c)
        elif k == "text":
            text(p["p"], p["text"], c)
    return draw_labels(out, labels, T, view)


FONT_PATHS = [
    "/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc", "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", "C:/Windows/Fonts/msyh.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def draw_labels(img, labels, T, view=None):
    """Text for baked stills. Uses Pillow + a system font when possible; non-renderable text is skipped."""
    if not labels:
        return img
    size = int(max(15, T * 0.16))
    try:
        from PIL import Image, ImageDraw, ImageFont
        font = None
        for fp in FONT_PATHS:
            if os.path.exists(fp):
                try:
                    font = ImageFont.truetype(fp, size)
                    break
                except Exception:  # noqa: BLE001
                    continue
        if font is None:
            raise RuntimeError("no font")
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(pil, "RGBA")
        placed = []
        for p, s, c in labels:
            l, t, r, b = d.textbbox((0, 0), s, font=font)
            tw, th = r - l + size * 0.7, size * 1.45
            vx0, vy0, vx1, vy1 = view or (0, 0, pil.width, pil.height)
            x = min(max(p[0], vx0 + tw / 2 + 3), vx1 - tw / 2 - 3)
            y = min(max(p[1], vy0 + th + 2), vy1 - 6)
            for _ in range(12):
                hit = [q for q in placed if abs(q[0] - x) < (q[2] + tw) / 2 and abs(q[1] - y) < th * 1.02]
                if not hit:
                    break
                y = hit[0][1] + th * 1.08 if y + th * 1.1 < vy1 - 6 else hit[0][1] - th * 1.08
            placed.append((x, y, tw))
            d.rounded_rectangle([x - tw / 2, y - th * 0.76, x + tw / 2, y + th * 0.24], radius=th * 0.3, fill=(12, 20, 16, 200))
            d.text((x, y - th * 0.26), s, font=font, fill=(c[2], c[1], c[0]), anchor="mm")
        return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    except Exception:  # noqa: BLE001 - Pillow or fonts missing: plain ASCII via OpenCV
        for p, s, c in labels:
            if not s.isascii():
                continue
            sc = max(0.45, T / 260)
            (tw, th), _ = cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, sc, 2)
            x = int(min(max(4, p[0] - tw / 2), img.shape[1] - tw - 4))
            y = int(min(max(th + 4, p[1]), img.shape[0] - 6))
            cv2.putText(img, s, (x, y), cv2.FONT_HERSHEY_SIMPLEX, sc, (0, 0, 0), 5, cv2.LINE_AA)
            cv2.putText(img, s, (x, y), cv2.FONT_HERSHEY_SIMPLEX, sc, c, 2, cv2.LINE_AA)
        return img


def prim_points(prims):
    pts = []
    for p in prims:
        for key in ("a", "b", "c", "p", "pivot", "end"):
            if key in p:
                pts.append(np.asarray(p[key], float))
        if p["k"] == "ghost_rot":
            pts.append(rot(p["end"], p["pivot"], p["delta"]))
        if p["k"] == "ghost_chain":
            pts += [rot(q, p["pivot"], p["delta"]) for q in p["pts"]]
    return pts


def auto_view(prims, lm, T, w, h):
    """Crop to the player + everything drawn, with breathing room, aspect between 4:5 and 5:4."""
    pts = [q[:2] for q in lm if q[2] > 0.3] + prim_points(prims)
    pts = np.array(pts)
    x1, y1, x2, y2 = pts[:, 0].min() - 0.75 * T, pts[:, 1].min() - 0.7 * T, pts[:, 0].max() + 0.75 * T, pts[:, 1].max() + 0.35 * T
    bw, bh = x2 - x1, y2 - y1
    if bw < 0.8 * bh:
        x1, x2 = (x1 + x2) / 2 - 0.4 * bh, (x1 + x2) / 2 + 0.4 * bh
    elif bh < 0.8 * bw:
        y1, y2 = (y1 + y2) / 2 - 0.4 * bw, (y1 + y2) / 2 + 0.4 * bw
    dx = max(0, -x1) - max(0, x2 - w)
    dy = max(0, -y1) - max(0, y2 - h)
    return [max(0, x1 + dx), max(0, y1 + dy), min(w, x2 + dx), min(h, y2 + dy)]


def render_evidence(an, ev, L, export=None):
    """One annotated still -> html <figure>. ev: {swing, frame, offset?, marks?, caption?, zoom?, skeleton?}"""
    sid = ev["swing"]
    fno = an.frame_no(sid, ev.get("frame", "contact"), ev.get("offset", 0))
    img = an.image(sid, fno)
    if img is None:
        sys.exit("ERROR: missing cached frame for swing %s frame %s" % (sid, fno))
    lm = an.landmarks(sid, fno)
    h, w = img.shape[:2]
    try:
        prims, T = marks_to_prims(ev.get("marks"), lm, w, h)
    except (ValueError, KeyError) as e:
        sys.exit("ERROR in marks for swing %s frame %s: %s" % (sid, ev.get("frame"), e))
    full = img
    box = [0, 0, w, h]
    if ev.get("zoom"):
        x1, y1, x2, y2 = ev["zoom"]
        box = [x1 * w, y1 * h, x2 * w, y2 * h]
    elif ev.get("zoom", True) is not False and lm is not None:
        box = auto_view(prims, lm, T, w, h)
    box = [int(v) for v in box]
    vb = (box[0], box[1], box[2] - box[0], box[3] - box[1])
    img = img[box[1]:box[3], box[0]:box[2]]
    if export:
        cv2.imwrite(export, bake(full, prims, T, box)[box[1]:box[3], box[0]:box[2]], [cv2.IMWRITE_JPEG_QUALITY, 88])
    svg = prims_to_svg(prims, T, w, h, lm, ev.get("skeleton", False), box)
    svg = svg.replace('viewBox="0 0 %d %d"' % (w, h), 'viewBox="%d %d %d %d"' % vb, 1)
    animated = any(p["k"].startswith("ghost") for p in prims)
    t_rel = (fno - an.swing(sid)["phases"]["contact"]) / an.data["video"]["fps"]
    meta = "#%d · %s %+.2fs" % (sid, esc(ev.get("frame", "contact")) if isinstance(ev.get("frame", "contact"), str) else L["frame"], t_rel)
    legend = ('<span class="lg"><i style="background:%s"></i>%s<i style="background:%s"></i>%s</span>'
              % (COLORS["bad"], esc(L["legend_now"]), COLORS["good"], esc(L["legend_target"]))) if animated else ""
    cap = '<figcaption>%s<span class="meta">%s</span>%s</figcaption>' % (rich(ev.get("caption", "")), meta, legend)
    return '<figure class="ev"><div class="evi"><img src="%s" alt="">%s</div>%s</figure>' % (jpeg_b64(img), svg, cap)


def render_flipbook(an, fb, L, idx):
    sid = fb["swing"]
    s = an.swing(sid)
    fps = an.data["video"]["fps"]
    c = s["phases"]["contact"]
    lo, hi = c + fb.get("from", -0.55) * fps, c + fb.get("to", 0.45) * fps
    frames = [f for f in s["frames"] if lo <= f <= hi]
    step = max(1, int(math.ceil(len(frames) / fb.get("max_frames", 30))))
    frames = frames[::step]
    imgs = []
    for f in frames:
        im = an.image(sid, f)
        lm = an.landmarks(sid, f)
        if fb.get("skeleton", True) and lm is not None:
            t = max(2, im.shape[0] // 220)
            for a, b in BONES:
                if lm[a, 2] > 0.3 and lm[b, 2] > 0.3:
                    cv2.line(im, (int(lm[a, 0]), int(lm[a, 1])), (int(lm[b, 0]), int(lm[b, 1])), (255, 235, 120), t, cv2.LINE_AA)
        imgs.append(jpeg_b64(im, 520, 68))
    ci = min(range(len(frames)), key=lambda k: abs(frames[k] - c))
    times = [round((f - c) / fps, 2) for f in frames]
    return ('<figure class="fb" data-fb="%d"><div class="evi"><img alt=""></div>'
            '<div class="ctl"><button type="button">%s</button><input type="range" min="0" max="%d" value="0">'
            '<span class="t"></span></div><figcaption>%s<span class="meta">#%d</span></figcaption>'
            '<script type="application/json">%s</script></figure>'
            % (idx, esc(L["pause"]), len(frames) - 1, rich(fb.get("caption", "")), sid,
               json.dumps({"frames": imgs, "times": times, "contact": ci})))


# ----------------------------------------------------------------------------- charts
def radar_svg(dims, prev=None):
    n = len(dims)
    cx = cy = 170
    R = 112

    def pt(i, v):
        a = -math.pi / 2 + 2 * math.pi * i / n
        return cx + R * v / 10 * math.cos(a), cy + R * v / 10 * math.sin(a)

    o = ['<svg viewBox="-56 -2 452 344" class="radar" role="img">']
    for ring in (2.5, 5, 7.5, 10):
        o.append('<polygon points="%s" class="ring"/>' % " ".join("%.1f,%.1f" % pt(i, ring) for i in range(n)))
    for i, d in enumerate(dims):
        x, y = pt(i, 10)
        o.append('<line x1="%d" y1="%d" x2="%.1f" y2="%.1f" class="spoke"/>' % (cx, cy, x, y))
        lx, ly = pt(i, 12.6)
        anchor = "middle" if abs(lx - cx) < 30 else ("start" if lx > cx else "end")
        name = str(d["name"])
        # Long side labels (English) would run off the chart: wrap them onto two lines.
        width = sum(14.5 if ord(ch) > 0x2E7F else 7.8 for ch in name)
        over = (anchor == "start" and lx + width > 392) or (anchor == "end" and lx - width < -52)
        lines = [name]
        if over and " " in name.strip():
            words = name.split()
            k = min(range(1, len(words)), key=lambda j: abs(len(" ".join(words[:j])) - len(" ".join(words[j:]))))
            lines = [" ".join(words[:k]), " ".join(words[k:])]
        y0 = ly - 3 - 8 * (len(lines) - 1)
        for j, ln in enumerate(lines):
            o.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="rl">%s</text>' % (lx, y0 + 17 * j, anchor, esc(ln)))
        o.append('<text x="%.1f" y="%.1f" text-anchor="%s" class="rv">%s</text>' % (lx, y0 + 17 * (len(lines) - 1) + 18, anchor, fmt(d["score"])))
    if prev:
        pm = {p.get("key"): p.get("score") for p in prev}
        if all(d.get("key") in pm for d in dims):
            o.append('<polygon points="%s" class="prevp"/>' % " ".join("%.1f,%.1f" % pt(i, pm[d["key"]]) for i, d in enumerate(dims)))
    o.append('<polygon points="%s" class="youp"/>' % " ".join("%.1f,%.1f" % pt(i, d["score"]) for i, d in enumerate(dims)))
    for i, d in enumerate(dims):
        o.append('<circle cx="%.1f" cy="%.1f" r="3.5" class="dot"/>' % pt(i, d["score"]))
    o.append("</svg>")
    return "".join(o)


def ring_svg(score, label):
    r, c = 54, 2 * math.pi * 54
    return ('<svg viewBox="0 0 140 140" class="ringc"><circle cx="70" cy="70" r="%d" class="bg"/>'
            '<circle cx="70" cy="70" r="%d" class="fg" stroke-dasharray="%.1f %.1f" transform="rotate(-90 70 70)"/>'
            '<text x="70" y="74" text-anchor="middle" class="num">%s</text>'
            '<text x="70" y="96" text-anchor="middle" class="lab">%s</text></svg>'
            % (r, r, c * max(0, min(100, score)) / 100, c, fmt(score), esc(label)))


def fmt(v):
    return ("%g" % round(float(v), 1)) if isinstance(v, (int, float)) else esc(v)


def delta_chip(now, before, unit=""):
    if before is None or now is None:
        return ""
    d = round(float(now) - float(before), 1)
    cls = "up" if d > 0 else ("down" if d < 0 else "same")
    return '<span class="delta %s">%s%g%s</span>' % (cls, "▲ +" if d > 0 else ("▼ " if d < 0 else "● "), d, unit)


# ----------------------------------------------------------------------------- html
CSS = """
:root{--paper:#f5f2ea;--card:#fffdf8;--ink:#15261d;--mute:#5d6b62;--line:#ddd8c9;--court:#1d5c41;--court2:#2f7d5b;
--ball:#d9f03c;--clay:#c8552f;--good:#168a55;--warn:#b7791f}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",Roboto,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:0 20px 64px}
header.hero{background:var(--court);color:#f4f7ee;margin:0 -20px 28px;padding:36px 28px 30px;position:relative;overflow:hidden}
header.hero:before{content:"";position:absolute;inset:14px;border:2px solid rgba(255,255,255,.22);pointer-events:none}
header.hero:after{content:"";position:absolute;left:14px;right:14px;top:50%;border-top:2px solid rgba(255,255,255,.12);pointer-events:none}
.hero .in{position:relative;z-index:1;display:grid;grid-template-columns:1fr auto;gap:24px;align-items:center}
.kicker{font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--ball);font-weight:700}
h1{font-size:clamp(26px,4.4vw,40px);line-height:1.15;margin:6px 0 10px;letter-spacing:-.01em;text-wrap:balance}
.hero p{margin:0;max-width:62ch;color:#dfe9dc}
.hero .sub{font-size:13px;color:#b9cdbd;margin-top:12px}
.scorebox{display:flex;gap:18px;align-items:center}
.ringc{width:132px;height:132px}.ringc .bg{fill:none;stroke:rgba(255,255,255,.18);stroke-width:11}
.ringc .fg{fill:none;stroke:var(--ball);stroke-width:11;stroke-linecap:round}
.ringc .num{font-size:38px;font-weight:800;fill:#fff;font-variant-numeric:tabular-nums}.ringc .lab{font-size:11px;fill:#cfe0cf;letter-spacing:.06em}
.lvl{border-left:2px solid rgba(255,255,255,.25);padding-left:18px}
.lvl .v{font-size:28px;font-weight:800;color:var(--ball);line-height:1.1;font-variant-numeric:tabular-nums}
.lvl .l{font-size:12px;color:#cfe0cf;letter-spacing:.06em}.lvl .n{font-size:13px;color:#e6efe2;max-width:22ch;margin-top:4px;line-height:1.4}
h2{font-size:22px;margin:44px 0 14px;display:flex;align-items:center;gap:10px;letter-spacing:-.005em}
h2:before{content:"";width:12px;height:12px;border-radius:50%;background:var(--ball);box-shadow:0 0 0 2px var(--court);flex:none}
h3{font-size:18px;margin:0 0 6px;line-height:1.35}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px}
.grid2{display:grid;grid-template-columns:minmax(0,400px) 1fr;gap:20px;align-items:start}
.radar{width:100%;max-width:440px;display:block;margin:auto}
.radar .ring{fill:none;stroke:var(--line)}.radar .spoke{stroke:var(--line)}
.radar .youp{fill:rgba(47,125,91,.28);stroke:var(--court);stroke-width:2.5;stroke-linejoin:round}
.radar .prevp{fill:none;stroke:var(--clay);stroke-width:1.5;stroke-dasharray:4 4}
.radar .dot{fill:var(--court)}.radar .rl{font-size:14.5px;fill:var(--ink);font-weight:600}.radar .rv{font-size:13px;fill:var(--mute);font-variant-numeric:tabular-nums}
.dim{display:grid;grid-template-columns:1fr auto;gap:2px 12px;padding:10px 0;border-bottom:1px dashed var(--line)}
.dim:last-child{border:0}.dim b{font-size:15px}.dim .s{font-weight:800;font-variant-numeric:tabular-nums;color:var(--court)}
.dim .bar{grid-column:1/-1;height:6px;border-radius:3px;background:#e8e3d4;overflow:hidden}.dim .bar i{display:block;height:100%;background:var(--court2);border-radius:3px}
.dim p{grid-column:1/-1;margin:2px 0 0;font-size:14px;color:var(--mute)}
.strokes{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
.stroke .top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.stroke .sc{font-size:30px;font-weight:800;color:var(--court);font-variant-numeric:tabular-nums}.stroke .sc small{font-size:13px;color:var(--mute);font-weight:500}
.stroke .cnt{font-size:12px;color:var(--mute)}.stroke p{margin:6px 0 0;font-size:14.5px}
.stroke ul{margin:8px 0 0;padding-left:18px;font-size:14px}.stroke li.plus::marker{color:var(--good)}.stroke li.minus::marker{color:var(--clay)}
.strengths{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
.strength{border-left:5px solid var(--good)}.strength p{margin:4px 0 0;font-size:14.5px}
.issue{margin-bottom:20px;display:grid;grid-template-columns:minmax(0,5fr) minmax(0,6fr);gap:22px;border-left:5px solid var(--clay)}
.issue.med{border-left-color:var(--warn)}.issue.low{border-left-color:var(--court2)}
.issue .evs{display:grid;gap:12px;align-content:start}
.tag{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:2px 9px;border-radius:99px;background:var(--clay);color:#fff;margin-right:6px}
.tag.med{background:var(--warn)}.tag.low{background:var(--court2)}.tag.st{background:#e8e3d4;color:var(--ink)}
.num{font-variant-numeric:tabular-nums}
.issue .n{font-size:13px;color:var(--mute);font-weight:700;margin-right:6px}
dl{margin:12px 0 0}dt{font-size:12px;font-weight:700;letter-spacing:.08em;color:var(--court);text-transform:uppercase;margin-top:12px}
dd{margin:2px 0 0;font-size:15px}
.cue{margin-top:14px;background:var(--court);color:#fff;border-radius:10px;padding:10px 14px;font-weight:700;font-size:16px;display:flex;gap:10px;align-items:baseline}
.cue span{font-size:11px;letter-spacing:.1em;color:var(--ball);text-transform:uppercase;flex:none}
.mt{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;font-size:13.5px;align-items:center}
.mt .chip{border:1px solid var(--line);border-radius:8px;padding:4px 10px;background:#fff;font-variant-numeric:tabular-nums}
.mt .chip b{color:var(--clay)}.mt .chip.t b{color:var(--good)}
.drills{margin:8px 0 0;padding:0;list-style:none}.drills li{padding:8px 0 8px 26px;border-top:1px dashed var(--line);position:relative;font-size:14.5px}
.drills li:before{content:"";position:absolute;left:4px;top:15px;width:10px;height:10px;border-radius:50%;background:var(--ball);border:1.5px solid var(--court)}
.drills .r{color:var(--mute);font-size:13px;display:block}
figure{margin:0}.evi{position:relative;border-radius:10px;overflow:hidden;background:#111;line-height:0}
.evi img{width:100%;height:auto;display:block}.ov{position:absolute;inset:0;width:100%;height:100%}
.ovt{font-weight:700;font-family:inherit}
figcaption{font-size:13px;color:var(--mute);margin-top:6px;line-height:1.45}
figcaption .meta{font-size:11px;color:#8b958d;margin-left:8px;font-variant-numeric:tabular-nums;white-space:nowrap}
.lg{display:block;font-size:11.5px;margin-top:2px}.lg i{display:inline-block;width:9px;height:9px;border-radius:50%;margin:0 4px 0 0}.lg i+i,.lg i:nth-of-type(2){margin-left:12px}
.fbs{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
.fb .ctl{display:flex;gap:10px;align-items:center;margin-top:8px}.fb button{font:inherit;font-size:13px;font-weight:700;border:1.5px solid var(--court);background:#fff;color:var(--court);border-radius:8px;padding:4px 12px;cursor:pointer;min-width:64px}
.fb input{flex:1;accent-color:var(--court)}.fb .t{font-size:12px;color:var(--mute);font-variant-numeric:tabular-nums;min-width:70px;text-align:right}
.fb .t.hit{color:var(--clay);font-weight:800}
.plan{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}.plan .wk{font-size:12px;font-weight:700;color:var(--court);letter-spacing:.08em;text-transform:uppercase}
.plan ul{margin:8px 0 0;padding-left:18px;font-size:14.5px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--mute)}td.num{white-space:nowrap}
.tw{overflow-x:auto}
.delta{font-size:12px;font-weight:700;border-radius:6px;padding:1px 7px;margin-left:8px;font-variant-numeric:tabular-nums;white-space:nowrap}
.delta.up{background:#dff3e6;color:var(--good)}.delta.down{background:#fbe3da;color:var(--clay)}.delta.same{background:#ece8da;color:var(--mute)}
.tips{padding-left:20px;margin:0}.note{font-size:13px;color:var(--mute);margin-top:32px;border-top:1px solid var(--line);padding-top:14px}
@media(max-width:760px){.hero .in{grid-template-columns:1fr}.grid2,.issue{grid-template-columns:1fr}.scorebox{flex-wrap:wrap}}
@media print{body{background:#fff}.card{break-inside:avoid}.fb .ctl{display:none}header.hero{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
@media(prefers-reduced-motion:reduce){.ov animate,.ov animateTransform{display:none}}
"""

JS = """
document.querySelectorAll('.fb').forEach(function(el){
  var d=JSON.parse(el.querySelector('script').textContent),img=el.querySelector('img'),r=el.querySelector('input'),
      b=el.querySelector('button'),t=el.querySelector('.t'),i=0,playing=true,L=%s;
  function show(k){i=k;img.src=d.frames[k];r.value=k;var s=d.times[k];t.textContent=(s>0?'+':'')+s.toFixed(2)+'s';t.classList.toggle('hit',k===d.contact)}
  function tick(){if(playing){show((i+1)%%d.frames.length)}setTimeout(tick,i===d.contact?650:(i===d.frames.length-1?700:130))}
  r.addEventListener('input',function(){playing=false;b.textContent=L.play;show(+r.value)});
  b.addEventListener('click',function(){playing=!playing;b.textContent=playing?L.pause:L.play});
  show(0);setTimeout(tick,400);
});
"""


def load_previous(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    if path.lower().endswith((".html", ".htm")):
        m = re.search(r'<script type="application/json" id="rmt-progress">(.*?)</script>', txt, re.S)
        if not m:
            sys.exit("ERROR: no progress data embedded in %s" % path)
        txt = html.unescape(m.group(1))
    data = json.loads(txt)
    hist = data.get("history", [data] if "overall_score" in data else [])
    return hist


def build(rep, an, prev_hist, export_dir):
    lang = rep.get("lang", "en")
    L = dict(L10N.get(lang[:2], L10N["en"]))
    L.update(rep.get("labels", {}))
    prev = prev_hist[-1] if prev_hist else None
    o = []
    v = an.data["video"]
    date = rep.get("date") or datetime.date.today().isoformat()
    lvl = rep.get("level", {})
    o.append('<header class="hero"><div class="in"><div><div class="kicker">Rate My Tennis</div><h1>%s</h1><p>%s</p>'
             '<div class="sub">%s · %s · %d %s · %.0fs</div></div>'
             % (esc(rep.get("title") or L["title"]), rich(rep.get("summary", "")), esc(date), esc(rep.get("session", v["file"])),
                an.data["swings_detected"], esc(L["swings"]), v["duration_s"]))
    o.append('<div class="scorebox">%s<div class="lvl"><div class="l">%s</div><div class="v">%s</div><div class="n">%s</div></div></div></div></header>'
             % (ring_svg(rep.get("overall_score", 0), L["overall"] + " /100"), esc(L["level"]), esc(lvl.get("value", "–")),
                rich(lvl.get("note", ""))))

    # progress
    if prev:
        o.append("<h2>%s</h2><div class='card'><div class='tw'><table><tr><th>%s</th><th>%s (%s)</th><th>%s</th></tr>"
                 % (esc(L["progress"]), esc(L["metric"]), esc(L["prev"]), esc(prev.get("date", "")), esc(L["you"])))
        o.append("<tr><td><b>%s</b></td><td class='num'>%s</td><td class='num'><b>%s</b>%s</td></tr>"
                 % (esc(L["overall"]), fmt(prev.get("overall_score")), fmt(rep.get("overall_score")),
                    delta_chip(rep.get("overall_score"), prev.get("overall_score"))))
        pd = {d.get("key"): d for d in prev.get("dimensions", [])}
        for d in rep.get("dimensions", []):
            p = pd.get(d.get("key"))
            if p:
                o.append("<tr><td>%s</td><td class='num'>%s</td><td class='num'><b>%s</b>%s</td></tr>"
                         % (esc(d["name"]), fmt(p["score"]), fmt(d["score"]), delta_chip(d["score"], p["score"])))
        ps = {s.get("type"): s for s in prev.get("strokes", [])}
        for s in rep.get("strokes", []):
            p = ps.get(s.get("type"))
            if p:
                o.append("<tr><td>%s</td><td class='num'>%s</td><td class='num'><b>%s</b>%s</td></tr>"
                         % (esc(s["name"]), fmt(p["score"]), fmt(s["score"]), delta_chip(s["score"], p["score"])))
        o.append("</table></div>%s</div>" % ("<p>%s</p>" % rich(rep["progress_note"]) if rep.get("progress_note") else ""))

    # radar + dims
    dims = rep.get("dimensions", [])
    if dims:
        o.append("<h2>%s</h2><div class='grid2'><div class='card'>%s</div><div class='card'>" % (esc(L["dims"]), radar_svg(dims, prev.get("dimensions") if prev else None)))
        for d in dims:
            o.append("<div class='dim'><b>%s</b><span class='s'>%s<small style='color:var(--mute);font-weight:500'> /10</small></span>"
                     "<div class='bar'><i style='width:%.0f%%'></i></div><p>%s</p></div>"
                     % (esc(d["name"]), fmt(d["score"]), float(d["score"]) * 10, rich(d.get("comment", ""))))
        o.append("</div></div>")

    # strokes
    if rep.get("strokes"):
        o.append("<h2>%s</h2><div class='strokes'>" % esc(L["strokes"]))
        for s in rep["strokes"]:
            o.append("<div class='card stroke'><div class='top'><h3>%s</h3><span class='sc'>%s<small> /100</small></span></div>"
                     "<div class='cnt'>%s %s</div><p>%s</p><ul>%s%s</ul></div>"
                     % (esc(s["name"]), fmt(s["score"]), fmt(s.get("count", "")), esc(L["shots"]) if s.get("count") is not None else "",
                        rich(s.get("summary", "")),
                        "".join("<li class='plus'>%s</li>" % rich(x) for x in s.get("good", [])),
                        "".join("<li class='minus'>%s</li>" % rich(x) for x in s.get("work_on", []))))
        o.append("</div>")

    # strengths
    if rep.get("strengths"):
        o.append("<h2>%s</h2><div class='strengths'>" % esc(L["strengths"]))
        for i, s in enumerate(rep["strengths"]):
            ev = ""
            if s.get("evidence"):
                ex = os.path.join(export_dir, "strength_%d.jpg" % (i + 1)) if export_dir else None
                ev = "<div style='margin-top:12px'>%s</div>" % render_evidence(an, s["evidence"], L, ex)
            o.append("<div class='card strength'><h3>%s</h3><p>%s</p>%s</div>" % (esc(s["title"]), rich(s.get("detail", "")), ev))
        o.append("</div>")

    # issues
    if rep.get("issues"):
        o.append("<h2>%s</h2>" % esc(L["issues"]))
        for i, it in enumerate(rep["issues"]):
            sev = it.get("severity", "med")
            evs = it.get("evidence") or []
            evs = evs if isinstance(evs, list) else [evs]
            figs = []
            for j, ev in enumerate(evs):
                ex = os.path.join(export_dir, "issue_%d%s.jpg" % (i + 1, "abc"[j] if len(evs) > 1 else "")) if export_dir else None
                figs.append(render_evidence(an, ev, L, ex))
            o.append("<article class='card issue %s'><div class='evs'>%s</div><div>" % (esc(sev), "".join(figs)))
            o.append("<div><span class='tag %s'>%s</span>%s</div><h3 style='margin-top:8px'><span class='n'>%d</span>%s</h3>"
                     % (esc(sev), esc(L.get(sev, sev)), "<span class='tag st'>%s</span>" % esc(it["stroke"]) if it.get("stroke") else "",
                        i + 1, esc(it["title"])))
            if it.get("metric"):
                m = it["metric"]
                o.append("<div class='mt'><span>%s</span><span class='chip'>%s <b>%s</b></span><span>→</span><span class='chip t'>%s <b>%s</b></span></div>"
                         % (esc(m.get("name", "")), esc(L["now"]), esc(m.get("value", "")), esc(L["target"]), esc(m.get("target", ""))))
            o.append("<dl>")
            for key in ("what", "why", "fix"):
                if it.get(key):
                    o.append("<dt>%s</dt><dd>%s</dd>" % (esc(L[key]), rich(it[key])))
            o.append("</dl>")
            if it.get("cue"):
                o.append("<div class='cue'><span>%s</span>%s</div>" % (esc(L["cue"]), rich(it["cue"])))
            if it.get("drills"):
                o.append("<dl><dt>%s</dt></dl><ul class='drills'>" % esc(L["drills"]))
                for d in it["drills"]:
                    o.append("<li><b>%s</b> — %s%s</li>" % (esc(d.get("name", "")), rich(d.get("how", "")),
                                                           "<span class='r'>%s</span>" % esc(d["dose"]) if d.get("dose") else ""))
                o.append("</ul>")
            o.append("</div></article>")

    # flipbooks
    if rep.get("flipbooks"):
        o.append("<h2>%s</h2><div class='fbs'>" % esc(L["flip"]))
        for i, fb in enumerate(rep["flipbooks"]):
            o.append("<div class='card'>%s</div>" % render_flipbook(an, fb, L, i))
        o.append("</div>")

    # plan
    if rep.get("plan"):
        o.append("<h2>%s</h2><div class='plan'>" % esc(L["plan"]))
        for p in rep["plan"]:
            o.append("<div class='card'><div class='wk'>%s</div><h3>%s</h3><ul>%s</ul></div>"
                     % (esc(p.get("when", "")), esc(p.get("focus", "")), "".join("<li>%s</li>" % rich(t) for t in p.get("tasks", []))))
        o.append("</div>")

    # metrics table
    if rep.get("metrics_table"):
        o.append("<h2>%s</h2><div class='card'><div class='tw'><table><tr><th>%s</th><th>%s</th><th>%s</th><th></th></tr>"
                 % (esc(L["metrics"]), esc(L["metric"]), esc(L["you"]), esc(L["ref"])))
        for m in rep["metrics_table"]:
            o.append("<tr><td><b>%s</b></td><td class='num'>%s</td><td class='num'>%s</td><td>%s</td></tr>"
                     % (esc(m.get("name", "")), esc(m.get("value", "")), esc(m.get("reference", "")), rich(m.get("note", ""))))
        o.append("</table></div></div>")

    if rep.get("next_recording_tips"):
        o.append("<h2>%s</h2><div class='card'><ul class='tips'>%s</ul></div>"
                 % (esc(L["tips"]), "".join("<li>%s</li>" % rich(t) for t in rep["next_recording_tips"])))
    if not prev:
        o.append("<p class='note' style='border:0;margin-top:20px'>%s</p>" % esc(L["first_report"]))
    o.append("<p class='note'>%s</p>" % esc(rep.get("disclaimer") or L["disclaimer"]))

    snap = {"date": date, "session": rep.get("session", v["file"]), "overall_score": rep.get("overall_score"),
            "level": lvl.get("value"),
            "dimensions": [{"key": d.get("key"), "name": d["name"], "score": d["score"]} for d in dims],
            "strokes": [{"type": s.get("type"), "name": s["name"], "score": s["score"]} for s in rep.get("strokes", [])],
            "issues": [{"title": it["title"], "severity": it.get("severity"), "stroke": it.get("stroke"),
                        "metric": it.get("metric")} for it in rep.get("issues", [])],
            "aggregate_metrics": an.data.get("aggregate_by_guess")}
    progress = {"tool": "rate-my-tennis", "history": (prev_hist or []) + [snap]}
    page = ("<!doctype html><html lang='%s'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>%s</title><style>%s</style></head><body><div class='wrap'>%s</div>"
            "<script type=\"application/json\" id=\"rmt-progress\">%s</script><script>%s</script></body></html>"
            % (esc(lang), esc(rep.get("title") or L["title"]), CSS, "".join(o), esc(json.dumps(progress, ensure_ascii=False)),
               JS % json.dumps({"play": L["play"], "pause": L["pause"]}, ensure_ascii=False)))
    return page, progress


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report_json")
    ap.add_argument("--analysis", required=True, help="output dir of analyze_video.py")
    ap.add_argument("--out", default="report.html")
    ap.add_argument("--previous", default="", help="earlier report.html or tennis-progress.json")
    ap.add_argument("--export-images", default="", help="also write annotated stills into this dir")
    a = ap.parse_args()
    with open(a.report_json, encoding="utf-8") as f:
        rep = json.load(f)
    an = Analysis(a.analysis)
    if a.export_images:
        os.makedirs(a.export_images, exist_ok=True)
    page, progress = build(rep, an, load_previous(a.previous), a.export_images or None)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(page)
    pj = os.path.join(os.path.dirname(os.path.abspath(a.out)), "tennis-progress.json")
    with open(pj, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=1)
    print("wrote %s (%.1f MB) and %s" % (a.out, os.path.getsize(a.out) / 1e6, pj))


if __name__ == "__main__":
    main()
