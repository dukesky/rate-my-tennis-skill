#!/usr/bin/env python3
"""Rate My Tennis - step 1: turn a tennis video into evidence an LLM can look at.

What it does
  1. Scans the video with a pose model and finds every swing (racket-hand speed peaks).
  2. For up to --max-swings swings: re-runs pose on a zoomed crop of the player,
     caches the frames, computes body metrics, and writes a labelled filmstrip.
  3. Writes analysis.json (all numbers) + overview.jpg (one contact frame per swing).

Fallback: if mediapipe is not installed, swings are found from raw image motion and
filmstrips are written without skeletons or metrics (the LLM then judges by eye).

Usage
  python analyze_video.py VIDEO --out OUT_DIR [--hand auto|right|left]
                          [--max-swings 24] [--roi x1,y1,x2,y2] [--start S] [--end S]
"""
import argparse
import os
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import json
import math
import os
import sys
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_CANDIDATES = [
    os.path.join(HERE, "..", "assets", "pose_landmarker_full.task"),
    os.path.join(HERE, "pose_landmarker_full.task"),
    os.path.join(os.getcwd(), "pose_landmarker_full.task"),
]

LM = {
    "nose": 0, "left_shoulder": 11, "right_shoulder": 12, "left_elbow": 13, "right_elbow": 14,
    "left_wrist": 15, "right_wrist": 16, "left_hip": 23, "right_hip": 24, "left_knee": 25,
    "right_knee": 26, "left_ankle": 27, "right_ankle": 28, "left_heel": 29, "right_heel": 30,
    "left_foot": 31, "right_foot": 32,
}
BONES = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (24, 26), (26, 28), (27, 31), (28, 32), (27, 29), (28, 30),
]


# ----------------------------------------------------------------------------- pose backend
class PoseBackend:
    """Wraps whichever mediapipe API is available. detect(bgr) -> (img_pts[33,3], world[33,3]) or None.
    img_pts columns: x, y in pixels of the given image, visibility 0..1."""

    def __init__(self):
        self.kind = None
        self._impl = None
        try:
            import mediapipe as mp
        except Exception as e:  # noqa: BLE001
            self.error = "mediapipe not importable: %s" % e
            return
        self.mp = mp
        model = next((p for p in MODEL_CANDIDATES if os.path.exists(p)), None)
        try:
            if model is None:
                raise RuntimeError("pose_landmarker_full.task not found")
            from mediapipe.tasks import python as mpp
            from mediapipe.tasks.python import vision
            opts = vision.PoseLandmarkerOptions(
                base_options=mpp.BaseOptions(model_asset_path=os.path.abspath(model)),
                running_mode=vision.RunningMode.IMAGE, num_poses=1,
                min_pose_detection_confidence=0.4, min_pose_presence_confidence=0.4)
            self._impl = vision.PoseLandmarker.create_from_options(opts)
            self.kind = "tasks"
        except Exception as e_tasks:  # noqa: BLE001
            try:
                self._impl = mp.solutions.pose.Pose(static_image_mode=True, model_complexity=1,
                                                    min_detection_confidence=0.4)
                self.kind = "solutions"
            except Exception as e_sol:  # noqa: BLE001
                self.error = "tasks API: %s; solutions API: %s" % (e_tasks, e_sol)

    def detect(self, bgr):
        h, w = bgr.shape[:2]
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if self.kind == "tasks":
            res = self._impl.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb))
            if not res.pose_landmarks:
                return None
            lm, wl = res.pose_landmarks[0], res.pose_world_landmarks[0]
        else:
            res = self._impl.process(rgb)
            if not res.pose_landmarks:
                return None
            lm, wl = res.pose_landmarks.landmark, res.pose_world_landmarks.landmark
        img = np.array([[p.x * w, p.y * h, getattr(p, "visibility", 1.0) or 0.0] for p in lm], dtype=np.float32)
        world = np.array([[p.x, p.y, p.z] for p in wl], dtype=np.float32)
        return img, world


# ----------------------------------------------------------------------------- geometry helpers
def angle3(a, b, c):
    """Angle ABC in degrees (works for 2D or 3D points)."""
    v1, v2 = np.asarray(a, float) - np.asarray(b, float), np.asarray(c, float) - np.asarray(b, float)
    n = np.linalg.norm(v1) * np.linalg.norm(v2)
    if n < 1e-9:
        return float("nan")
    return float(np.degrees(np.arccos(np.clip(np.dot(v1, v2) / n, -1, 1))))


def torso_len(img):
    ms = (img[11, :2] + img[12, :2]) / 2
    mh = (img[23, :2] + img[24, :2]) / 2
    return float(np.linalg.norm(ms - mh))


def find_peaks(y, min_height, min_dist):
    """Indices of local maxima >= min_height, at least min_dist samples apart (keeps the taller)."""
    idx = [i for i in range(1, len(y) - 1) if y[i] >= min_height and y[i] >= y[i - 1] and y[i] > y[i + 1]]
    idx.sort(key=lambda i: -y[i])
    keep = []
    for i in idx:
        if all(abs(i - k) >= min_dist for k in keep):
            keep.append(i)
    return sorted(keep)


def smooth(y, k=3):
    if len(y) < k:
        return np.asarray(y, float)
    return np.convolve(np.asarray(y, float), np.ones(k) / k, mode="same")


def r1(x, nd=1):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


# ----------------------------------------------------------------------------- video io
def open_video(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        sys.exit("ERROR: cannot open video %s (try converting to .mp4 / H.264)" % path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if not (5 <= fps <= 480):
        fps = 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    return cap, fps, n


def fit(img, long_side):
    h, w = img.shape[:2]
    s = long_side / max(h, w)
    if s >= 1:
        return img, 1.0
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA), s


def apply_roi(frame, roi):
    if not roi:
        return frame
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = roi
    return frame[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]


# ----------------------------------------------------------------------------- audio (optional)
def audio_onsets(path):
    """Times (s) of sharp sounds (ball impacts, bounces). Needs ffmpeg; returns [] if unavailable."""
    import shutil
    import subprocess
    exe = shutil.which("ffmpeg")
    if not exe:
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001
            return []
    sr, hop = 16000, 80
    try:
        raw = subprocess.run([exe, "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                             capture_output=True, timeout=300).stdout
    except Exception:  # noqa: BLE001
        return []
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    if len(x) < sr:
        return []
    x = np.diff(x, prepend=0)  # crude high-pass: impacts are clicks
    n = len(x) // hop
    env = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1))
    flux = np.concatenate([[0], np.maximum(0, env[1:] - env[:-1])])
    thr = np.percentile(flux, 99.5)
    if thr <= 0:
        return []
    out = []
    for i in range(1, n - 1):
        if flux[i] > thr and flux[i] >= flux[i - 1] and flux[i] > flux[i + 1]:
            if out and (i - out[-1]) * hop / sr < 0.08:
                if flux[i] > flux[out[-1]]:
                    out[-1] = i
            else:
                out.append(i)
    return [i * hop / sr for i in out]


# ----------------------------------------------------------------------------- pass 1: scan
def scan(path, backend, args):
    """Return (fps, per-sample records, frame size). One record per sampled frame."""
    cap, fps, n = open_video(path)
    stride = max(1, int(round(fps / args.scan_fps)))
    f0, f1 = int(args.start * fps), (int(args.end * fps) if args.end else 10 ** 12)
    recs, i, prev_small, size = [], -1, None, None
    t0 = time.time()
    while True:
        ok = cap.grab()
        if not ok:
            break
        i += 1
        if i < f0 or i % stride:
            continue
        if i > f1:
            break
        ok, frame = cap.retrieve()
        if not ok:
            continue
        frame = apply_roi(frame, args.roi)
        size = frame.shape[1], frame.shape[0]
        rec = {"f": i, "pose": None, "motion": 0.0}
        if backend.kind:
            small, s = fit(frame, 640)
            det = backend.detect(small)
            if det is not None:
                img, world = det
                img[:, :2] /= s
                rec["pose"] = img
        else:
            g = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY)
            if prev_small is not None:
                rec["motion"] = float(np.mean(cv2.absdiff(g, prev_small) > 25))
            prev_small = g
        recs.append(rec)
        if len(recs) % 300 == 0:
            print("  scanned %.0fs of video (%.0fs elapsed)" % (i / fps, time.time() - t0), flush=True)
    cap.release()
    return fps, stride, recs, size


def detect_swings(fps, stride, recs, hand, onsets=()):
    """Find swing candidates. Returns (hand, list of dict(f=peak frame, speed=...))."""
    dt = stride / fps
    have_pose = any(r["pose"] is not None for r in recs)
    if not have_pose:
        m = smooth([r["motion"] for r in recs], 3)
        if len(m) < 5 or m.max() <= 0:
            return hand if hand != "auto" else "right", []
        med, p90 = np.median(m), np.percentile(m, 90)
        thr = med + 0.8 * (p90 - med)
        ons = np.asarray(onsets, float)
        out = []
        for i in find_peaks(m, thr, max(1, int(0.9 / dt))):
            t_pk, f = recs[i]["f"] / fps, recs[i]["f"]
            snd = False
            if len(ons):  # with audio, keep only motion bursts that coincide with an impact sound
                d = ons - t_pk
                ok = np.where((d >= -0.3) & (d <= 0.4))[0]
                if not len(ok):
                    continue
                f, snd = int(round(float(ons[ok[np.argmin(np.abs(d[ok]))]]) * fps)), True
            out.append({"f": f, "speed": float(m[i]), "sound": snd})
        return (hand if hand != "auto" else "right"), out

    speeds = {}
    for side, wi in (("left", 15), ("right", 16)):
        sp = np.zeros(len(recs))
        for k in range(1, len(recs)):
            a, b = recs[k - 1]["pose"], recs[k]["pose"]
            if a is None or b is None:
                continue
            tl = (torso_len(a) + torso_len(b)) / 2
            if tl < 8 or min(a[wi, 2], b[wi, 2]) < 0.3:
                continue
            sp[k] = np.linalg.norm(b[wi, :2] - a[wi, :2]) / tl / dt  # torso-lengths per second
        speeds[side] = np.minimum(sp, 40)  # clip tracking glitches
    conf = "given"
    if hand == "auto":
        score = {side: float(np.percentile(speeds[side], 97)) for side in speeds}
        hand = max(score, key=score.get)
        ratio = score[hand] / max(min(score.values()), 1e-6)
        # two-handed strokes move both wrists alike, so a small margin means "check by eye"
        conf = "high" if ratio > 1.5 else ("medium" if ratio > 1.2 else "low")
    detect_swings.hand_confidence = conf
    # two hands on the racket (or the racket hand hidden behind the body): the other wrist tells the same story
    other = "left" if hand == "right" else "right"
    wi = 15 if hand == "left" else 16
    joined = np.zeros(len(recs), bool)
    for k, r in enumerate(recs):
        p = r["pose"]
        if p is not None:
            joined[k] = (np.linalg.norm(p[15, :2] - p[16, :2]) < 0.45 * max(torso_len(p), 1.0)) or p[wi, 2] < 0.3
    joined = np.convolve(joined, np.ones(3), mode="same") > 0
    sp = smooth(np.where(joined, np.maximum(speeds[hand], speeds[other]), speeds[hand]), 3)
    strong = np.sort(sp)[-max(5, len(sp) // 50):]
    thr = max(3.5, 0.40 * float(np.median(strong)))
    onsets = np.asarray(onsets, float)
    out = []
    # a weaker hand-speed peak still counts when an impact sound confirms it
    for i in find_peaks(sp, 0.6 * thr if len(onsets) else thr, max(1, int(0.9 / dt))):
        t_pk, snd = recs[i]["f"] / fps, None
        if len(onsets):
            d = onsets - t_pk
            ok = np.where((d >= -0.2) & (d <= 0.3))[0]
            if len(ok):
                snd = float(onsets[ok[np.argmin(np.abs(d[ok] - 0.05))]])
        if sp[i] < thr and snd is None:
            continue
        f = int(round(snd * fps)) if snd is not None else recs[i]["f"]
        out.append({"f": f, "speed": float(sp[i]), "sound": snd is not None})
    return hand, out


def pick_detailed(swings, max_n):
    """Choose which swings get the detailed treatment: spread over time, preferring clean ones."""
    if len(swings) <= max_n:
        return list(range(len(swings)))
    # sound-confirmed swings first, then spread evenly over the session
    pool = [i for i, s in enumerate(swings) if s.get("sound")]
    if len(pool) < max_n:
        pool = list(range(len(swings)))
    buckets = np.array_split(np.array(pool), max_n)
    return [int(max(b, key=lambda i: swings[i]["speed"])) for b in buckets if len(b)]


def crop_box(recs, fps, stride, fpeak, size, pre, post):
    """Fixed crop (x1,y1,x2,y2) containing the player (and racket reach) for the whole swing window."""
    W, H = size
    pts = []
    for r in recs:
        if r["pose"] is not None and fpeak - pre * fps <= r["f"] <= fpeak + post * fps:
            p = r["pose"]
            pts.append(p[p[:, 2] > 0.2][:, :2])
    if not pts or not sum(len(p) for p in pts):
        return 0, 0, W, H
    pts = np.concatenate(pts)
    x1, y1, x2, y2 = pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max()
    bh = y2 - y1
    pad = 0.45 * bh  # racket adds roughly 40% of body height of reach
    x1, x2, y1, y2 = x1 - pad, x2 + pad, y1 - pad, y2 + 0.25 * bh
    # keep aspect ratio between 3:4 and 4:3 so strips tile nicely
    w, h = x2 - x1, y2 - y1
    if w < 0.75 * h:
        cx = (x1 + x2) / 2
        x1, x2 = cx - 0.375 * h, cx + 0.375 * h
    x1, y1, x2, y2 = max(0, int(x1)), max(0, int(y1)), min(W, int(x2)), min(H, int(y2))
    if x2 - x1 < 40 or y2 - y1 < 40:
        return 0, 0, W, H
    return x1, y1, x2, y2


# ----------------------------------------------------------------------------- pass 2: detail
def detail_pass(path, backend, args, fps, swings, detailed, recs, stride, size, out):
    pre, post = args.pre, args.post
    jobs = {}
    for sid in detailed:
        fpk = swings[sid]["f"]
        jobs[sid] = {"f0": int(fpk - pre * fps), "f1": int(fpk + post * fps), "sound": swings[sid].get("sound"),
                     "box": crop_box(recs, fps, stride, fpk, size, pre, post), "frames": []}
    cap, _, _ = open_video(path)
    i = -1
    last = max(j["f1"] for j in jobs.values()) if jobs else -1
    fine = max(1, int(round(fps / 60)))  # every frame up to 60 fps
    while i < last:
        if not cap.grab():
            break
        i += 1
        need = [sid for sid, j in jobs.items() if j["f0"] <= i <= j["f1"] and (i - j["f0"]) % fine == 0]
        if not need:
            continue
        ok, frame = cap.retrieve()
        if not ok:
            continue
        frame = apply_roi(frame, args.roi)
        for sid in need:
            x1, y1, x2, y2 = jobs[sid]["box"]
            crop = frame[y1:y2, x1:x2]
            crop, _ = fit(crop, args.crop_size)
            det = backend.detect(crop) if backend.kind else None
            jobs[sid]["frames"].append({"f": i, "img": crop.copy(), "pose": det})
    cap.release()
    return jobs


def draw_skeleton(img, pts, hand, thick=None):
    h = img.shape[0]
    t = thick or max(2, h // 220)
    dom = {"right": {12, 14, 16}, "left": {11, 13, 15}}[hand]
    for a, b in BONES:
        if pts[a, 2] < 0.3 or pts[b, 2] < 0.3:
            continue
        col = (60, 200, 255) if (a in dom and b in dom) else (255, 220, 90)
        cv2.line(img, tuple(map(int, pts[a, :2])), tuple(map(int, pts[b, :2])), col, t, cv2.LINE_AA)
    for k in set(sum(BONES, ())) | {0}:
        if pts[k, 2] >= 0.3:
            cv2.circle(img, tuple(map(int, pts[k, :2])), t + 1, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(img, tuple(map(int, pts[k, :2])), t + 1, (40, 40, 40), 1, cv2.LINE_AA)
    return img


def label(img, text, org=(8, 22), scale=0.55, color=(255, 255, 255)):
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    x, y = org
    cv2.rectangle(img, (x - 4, y - th - 5), (x + tw + 4, y + base + 1), (20, 20, 20), -1)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def swing_metrics(frames, fps, hand, contact_f=None):
    """Compute phases + metrics for one swing from its detailed frames. Returns dict or None."""
    D = {"right": dict(sh=12, el=14, wr=16, hip=24, kn=26, an=28, osh=11, oel=13, owr=15, ohip=23, okn=25, oan=27),
         "left": dict(sh=11, el=13, wr=15, hip=23, kn=25, an=27, osh=12, oel=14, owr=16, ohip=24, okn=26, oan=28)}[hand]
    idx = [k for k, fr in enumerate(frames) if fr["pose"] is not None]
    if len(idx) < 6:
        return None
    fs = np.array([frames[k]["f"] for k in idx])
    P = np.stack([frames[k]["pose"][0] for k in idx])   # image px (crop)
    Wd = np.stack([frames[k]["pose"][1] for k in idx])  # world metres, hip-centred
    tl = np.array([max(torso_len(p), 1.0) for p in P])
    # racket-hand speed per frame (torso lengths / s)
    sp = np.zeros(len(idx))
    for k in range(1, len(idx)):
        dtk = (fs[k] - fs[k - 1]) / fps
        sp[k] = np.linalg.norm(P[k, D["wr"], :2] - P[k - 1, D["wr"], :2]) / tl[k] / max(dtk, 1e-3)
    spo = np.zeros(len(idx))
    for k in range(1, len(idx)):
        dtk = (fs[k] - fs[k - 1]) / fps
        spo[k] = np.linalg.norm(P[k, D["owr"], :2] - P[k - 1, D["owr"], :2]) / tl[k] / max(dtk, 1e-3)
    joined = (np.linalg.norm(P[:, 15, :2] - P[:, 16, :2], axis=1) / tl < 0.45) | (P[:, D["wr"], 2] < 0.3)
    sp = smooth(np.minimum(np.where(joined, np.maximum(sp, spo), sp), 45), 3)
    sound_ok = False
    if contact_f is not None:  # contact suggested by an impact sound - accept only if the hand is really swinging then
        c = int(np.argmin(np.abs(fs - contact_f)))
        lo, hi = max(0, c - 2), min(len(sp), c + 3)
        sound_ok = float(sp[lo:hi].max()) >= 0.3 * float(sp.max()) or float(sp.max()) < 3.0
    if sound_ok:
        pass
    elif contact_f is not None:  # the sound was probably a bounce or the wall: use the fastest hand moment instead
        c = int(np.argmax(sp))
    else:  # otherwise: fastest hand moment near the scan peak
        mid = np.where(np.abs(fs - fs[len(fs) // 2]) <= 0.3 * fps)[0]
        c = int(mid[np.argmax(sp[mid])])
    t = (fs - fs[c]) / fps  # seconds relative to contact estimate

    def at(sec):
        return int(np.argmin(np.abs(t - sec)))

    # backswing end = slowest hand moment in the 0.15-0.7 s before contact
    pre = np.where((t >= -0.7) & (t <= -0.12))[0]
    if len(pre):
        quiet = pre[sp[pre] < max(0.3 * float(sp[c]), 1.5)]
        b = int(quiet[-1]) if len(quiet) else int(pre[np.argmin(sp[pre])])
    else:
        b = at(-0.35)
    post = np.where((t >= 0.12) & (t <= 0.6))[0]
    # finish = slowest moment after contact
    fin = int(post[np.argmin(sp[post])]) if len(post) else at(0.35)
    phases = {"ready": at(min(t[b] - 0.25, -0.6)), "backswing": b, "forward": at(t[c] - 0.07),
              "contact": c, "extension": at(0.08), "finish": fin}

    def elbow(k, side="dom"):
        s, e, w = (D["sh"], D["el"], D["wr"]) if side == "dom" else (D["osh"], D["oel"], D["owr"])
        return angle3(Wd[k, s], Wd[k, e], Wd[k, w])

    def knee(k, side):
        h_, kn, an = (D["hip"], D["kn"], D["an"]) if side == "dom" else (D["ohip"], D["okn"], D["oan"])
        return angle3(Wd[k, h_], Wd[k, kn], Wd[k, an])

    def azimuth(k, a, b_):
        v = Wd[k, a] - Wd[k, b_]
        return math.degrees(math.atan2(v[2], v[0]))

    def sep(k):  # shoulder line vs hip line, about the vertical axis
        d = azimuth(k, 12, 11) - azimuth(k, 24, 23)
        return abs((d + 180) % 360 - 180)

    prep = np.where((t >= -0.6) & (t <= 0))[0]
    p = P[c]
    msh, mhip = (p[11, :2] + p[12, :2]) / 2, (p[23, :2] + p[24, :2]) / 2
    shw = float(np.linalg.norm(Wd[c, 11] - Wd[c, 12])) or 0.35
    near = np.where(np.abs(t) <= 0.1)[0]
    after = np.where(t > 0)[0]
    # which side of the body the hand is on during the backswing (+ = hitting-arm side)
    ax = Wd[:, D["sh"]] - Wd[:, D["osh"]]
    ax /= np.maximum(np.linalg.norm(ax, axis=1, keepdims=True), 1e-6)
    side_proj = np.einsum("ij,ij->i", Wd[:, D["wr"]] - (Wd[:, 11] + Wd[:, 12]) / 2, ax) / shw
    bs = np.where((t >= -0.45) & (t <= -0.1))[0]
    side_val = float(np.mean(side_proj[bs])) if len(bs) else 0.0
    both_hands = bool(len(near)) and (
        float(np.median([np.linalg.norm(P[k, 15, :2] - P[k, 16, :2]) / tl[k] for k in near])) < 0.38
        and float(np.median([np.linalg.norm(Wd[k, 15] - Wd[k, 16]) for k in near])) < 0.32)
    contact_h = float((mhip[1] - p[D["wr"], 1]) / max(mhip[1] - msh[1], 1.0))  # 0 = hip, 1 = shoulder
    peak = float(np.max(sp[np.abs(t) <= 0.15]))
    if peak < 5.0:
        guess = "soft_touch"          # ball pick-up, feed, block - usually not worth rating
    elif contact_h > 1.25:
        guess = "serve_or_overhead"   # hand well above the shoulder at contact
    elif both_hands:
        guess = "backhand_two_handed"
    elif 0.5 * (side_val + float(side_proj[c])) < 0.45:
        guess = "backhand"            # hand stays in front of / across the body
    else:
        guess = "forehand"

    m = {
        "elbow_angle_contact": r1(elbow(c)),
        "elbow_angle_backswing": r1(elbow(b)),
        "off_arm_elbow_backswing": r1(elbow(b, "off")),
        "knee_min_hitting_side": r1(min(knee(k, "dom") for k in prep)),
        "knee_min_other_side": r1(min(knee(k, "off") for k in prep)),
        "knee_at_contact_avg": r1((knee(c, "dom") + knee(c, "off")) / 2),
        "hip_shoulder_separation_max": r1(max(sep(k) for k in prep)),
        "shoulder_rotation_range": r1(abs(((azimuth(fin, 12, 11) - azimuth(b, 12, 11)) + 180) % 360 - 180)),
        "contact_height": r1((mhip[1] - p[D["wr"], 1]) / max(mhip[1] - msh[1], 1.0), 2),
        "contact_side_reach": r1(float(side_proj[c]), 2),
        "stance_width": r1(float(np.linalg.norm(Wd[c, 27] - Wd[c, 28])) / shw, 2),
        "trunk_lean_deg": r1(math.degrees(math.atan2(abs(msh[0] - mhip[0]), max(mhip[1] - msh[1], 1.0)))),
        "head_movement": r1(float(np.linalg.norm(P[near[-1], 0, :2] - P[near[0], 0, :2]) / tl[c]) if len(near) > 1 else float("nan"), 2),
        "finish_height": r1(float(np.max((P[after, D["sh"], 1] - P[after, D["wr"], 1]) / tl[after])) if len(after) else float("nan"), 2),
        "peak_hand_speed": r1(float(np.max(sp[np.abs(t) <= 0.15]))),
        "backswing_to_contact_s": r1(float(t[c] - t[b]), 2),
        "two_hands_at_contact": bool(both_hands),
    }
    vis = float(np.mean(P[:, [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28], 2]))
    return {"idx": idx, "phases": phases, "metrics": m, "guess": guess, "pose_quality": round(vis, 2), "sound_ok": sound_ok,
            "contact_frame": int(fs[c])}


def write_swing(out, sid, job, info, fps, hand, strip_h):
    """Save cached frames + landmarks + filmstrip for one swing. Returns json-able dict."""
    d = os.path.join(out, "swings", "s%02d" % sid)
    os.makedirs(d, exist_ok=True)
    frames = job["frames"]
    lm_out = {}
    for fr in frames:
        cv2.imwrite(os.path.join(d, "f%06d.jpg" % fr["f"]), fr["img"], [cv2.IMWRITE_JPEG_QUALITY, 88])
        if fr["pose"] is not None:
            lm_out[str(fr["f"])] = [[round(float(x), 1), round(float(y), 1), round(float(v), 2)]
                                    for x, y, v in fr["pose"][0]]
    h, w = frames[0]["img"].shape[:2]
    rec = {"id": sid, "dir": os.path.relpath(d, out), "frame_size": [w, h],
           "frames": [fr["f"] for fr in frames], "crop_box": list(map(int, job["box"])),
           "contact_from_sound": bool(job.get("sound"))}
    order = ["ready", "backswing", "forward", "contact", "extension", "finish"]
    if info:
        ph = {k: frames[info["idx"][v]]["f"] for k, v in info["phases"].items()}
        rec["contact_from_sound"] = bool(info["sound_ok"])
        rec.update({"phases": ph, "metrics": info["metrics"], "guess": info["guess"],
                    "pose_quality": info["pose_quality"], "contact_frame": info["contact_frame"]})
        picks = [(k, ph[k]) for k in order]
    else:
        n = len(frames)
        picks = [(order[j], frames[min(n - 1, int(n * q))]["f"]) for j, q in enumerate((0.0, 0.3, 0.48, 0.55, 0.65, 0.95))]
        rec.update({"phases": dict(picks), "metrics": None, "guess": "unknown", "pose_quality": 0})
    with open(os.path.join(d, "landmarks.json"), "w") as f:
        json.dump({"frame_size": [w, h], "landmark_names": LM, "frames": lm_out}, f)
    byf = {fr["f"]: fr for fr in frames}
    tiles = []
    cf = rec["phases"]["contact"]
    for name, fno in picks:
        fr = byf[fno]
        im = fr["img"].copy()
        if fr["pose"] is not None:
            draw_skeleton(im, fr["pose"][0], hand)
        im = cv2.resize(im, (int(w * strip_h / h), strip_h), interpolation=cv2.INTER_AREA)
        label(im, "%s  %+.2fs" % (name, (fno - cf) / fps))
        tiles.append(im)
    strip = np.concatenate([np.concatenate(tiles[:3], axis=1), np.concatenate(tiles[3:], axis=1)], axis=0)
    label(strip, "swing #%d  t=%.1fs  guess=%s" % (sid, cf / fps, rec["guess"]), (8, 2 * strip_h - 10), 0.55, (120, 255, 255))
    cv2.imwrite(os.path.join(out, "strip_s%02d.jpg" % sid), strip, [cv2.IMWRITE_JPEG_QUALITY, 82])
    rec["strip"] = "strip_s%02d.jpg" % sid
    rec["time_s"] = round(cf / fps, 2)
    return rec, byf[cf]["img"]


def overview(out, thumbs, cols=6, th=220):
    tiles = []
    for sid, t_s, guess, im in thumbs:
        h, w = im.shape[:2]
        im = cv2.resize(im, (int(w * th / h), th), interpolation=cv2.INTER_AREA)
        tw = int(th * 0.9)
        if im.shape[1] >= tw:
            x0 = (im.shape[1] - tw) // 2
            im = im[:, x0:x0 + tw]
        else:
            im = cv2.copyMakeBorder(im, 0, 0, 0, tw - im.shape[1], cv2.BORDER_CONSTANT)
        label(im, "#%d %.0fs" % (sid, t_s), (5, 18), 0.5)
        label(im, guess[:9], (5, th - 8), 0.45, (120, 255, 255))
        tiles.append(im)
    if not tiles:
        return
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.concatenate(tiles[i:i + cols], axis=1) for i in range(0, len(tiles), cols)]
    cv2.imwrite(os.path.join(out, "overview.jpg"), np.concatenate(rows, axis=0), [cv2.IMWRITE_JPEG_QUALITY, 80])


def candidate_sheet(path, args, fps, times, out, cols=6, tw=320):
    """Motion-only helper: one thumbnail per candidate moment so the coach can pick the real swings by eye."""
    want = {int(round(t * fps)): t for t in times}
    cap, _, _ = open_video(path)
    tiles, i, last = [], -1, max(want) if want else -1
    while i < last:
        if not cap.grab():
            break
        i += 1
        if i in want:
            ok, frame = cap.retrieve()
            if ok:
                frame = apply_roi(frame, args.roi)
                h, w = frame.shape[:2]
                im = cv2.resize(frame, (tw, int(h * tw / w)), interpolation=cv2.INTER_AREA)
                label(im, "%.2fs" % want[i], (5, 18), 0.5, (120, 255, 255))
                tiles.append(im)
    cap.release()
    if not tiles:
        return None
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.concatenate(tiles[k:k + cols], axis=1) for k in range(0, len(tiles), cols)]
    fn = os.path.join(out, "candidates.jpg")
    cv2.imwrite(fn, np.concatenate(rows, axis=0), [cv2.IMWRITE_JPEG_QUALITY, 80])
    return fn


def aggregate(swings_out):
    """Per stroke-guess mean and spread of every metric (spread = consistency signal)."""
    groups = {}
    for s in swings_out:
        if s.get("metrics"):
            groups.setdefault(s["guess"], []).append(s["metrics"])
    agg = {}
    for g, ms in groups.items():
        a = {"count": len(ms)}
        for k in ms[0]:
            vals = [m[k] for m in ms if isinstance(m[k], (int, float)) and not isinstance(m[k], bool)]
            if vals:
                a[k] = {"mean": round(float(np.mean(vals)), 2), "sd": round(float(np.std(vals)), 2),
                        "min": round(float(min(vals)), 2), "max": round(float(max(vals)), 2)}
        agg[g] = a
    return agg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--out", required=True)
    ap.add_argument("--hand", default="auto", choices=["auto", "right", "left"], help="racket hand")
    ap.add_argument("--max-swings", type=int, default=24, help="swings analysed in detail")
    ap.add_argument("--scan-fps", type=float, default=15.0)
    ap.add_argument("--crop-size", type=int, default=640, help="long side of cached player crops")
    ap.add_argument("--strip-height", type=int, default=400)
    ap.add_argument("--pre", type=float, default=0.8, help="seconds kept before contact")
    ap.add_argument("--post", type=float, default=0.6, help="seconds kept after contact")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=0.0)
    ap.add_argument("--at", default="", help="comma-separated contact times in seconds: analyse exactly these swings")
    ap.add_argument("--no-pose", action="store_true", help="skip the pose model (motion-only mode)")
    ap.add_argument("--roi", default="", help="x1,y1,x2,y2 (0-1) region containing the player to rate")
    args = ap.parse_args()
    args.roi = [float(v) for v in args.roi.split(",")] if args.roi else None
    os.makedirs(args.out, exist_ok=True)

    # the pose library prints many harmless startup lines on stderr: hide them while it loads
    sys.stderr.flush()
    saved, devnull = os.dup(2), os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    try:
        backend = PoseBackend()
        if backend.kind:
            backend.detect(np.zeros((64, 64, 3), np.uint8))
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(devnull)
    if args.no_pose:
        backend.kind, backend.error = None, "disabled with --no-pose"
    mode = "pose" if backend.kind else "motion-only"
    if not backend.kind:
        print("NOTE: pose model unavailable (%s). Running motion-only fallback." % backend.error)
    t0 = time.time()
    print("[1/3] scanning video for swings (%s mode)..." % mode, flush=True)
    cache = os.path.join(args.out, "scan_cache.npz")
    key = "%s|%d|%s|%s|%s|%s" % (os.path.abspath(args.video), os.path.getsize(args.video), args.scan_fps, args.roi, args.start, args.end)
    recs = None
    if os.path.exists(cache) and backend.kind:
        z = np.load(cache, allow_pickle=False)
        if str(z["key"]) == key:
            fps, stride, size = float(z["fps"]), int(z["stride"]), tuple(int(v) for v in z["size"])
            recs = [{"f": int(f), "pose": (p if ok else None), "motion": 0.0} for f, p, ok in zip(z["f"], z["pose"], z["ok"])]
            print("      (reusing cached scan)")
    if recs is None:
        fps, stride, recs, size = scan(args.video, backend, args)
        if recs and backend.kind:
            np.savez_compressed(cache, key=key, fps=fps, stride=stride, size=np.array(size), f=np.array([r["f"] for r in recs]),
                                ok=np.array([r["pose"] is not None for r in recs]),
                                pose=np.stack([r["pose"] if r["pose"] is not None else np.zeros((33, 3), np.float32) for r in recs]))
    if not recs:
        sys.exit("ERROR: no frames decoded")
    onsets = audio_onsets(args.video)
    print("      audio: %s" % ("%d sharp sounds found" % len(onsets) if onsets else "not available (contact timing from hand speed only)"))
    if args.at:
        hand = args.hand if args.hand != "auto" else "right"
        swings = [{"f": int(round(float(t) * fps)), "speed": 0.0, "sound": True} for t in args.at.split(",") if t.strip()]
        if backend.kind and args.hand == "auto":
            hand, _ = detect_swings(fps, stride, recs, "auto", onsets)
    else:
        hand, swings = detect_swings(fps, stride, recs, args.hand, onsets)
    if not backend.kind and not args.at:
        # Without a pose model the script cannot tell a swing from a bounce: show every candidate and let the coach choose.
        lo, hi = args.start, (args.end or 1e9)
        times = [t for t in onsets if lo <= t <= hi] or [s_["f"] / fps for s_ in swings]
        if len(times) > 64:
            times = [times[int(k)] for k in np.linspace(0, len(times) - 1, 64)]
        fn = candidate_sheet(args.video, args, fps, times, args.out)
        print("\nMOTION-ONLY MODE: no pose model, so swings cannot be picked automatically.")
        print("Look at %s (%d candidate moments: impacts and bounces)." % (fn, len(times)))
        print("Pick the frames where the racket meets the ball, then rerun with e.g.  --at \"%s\"" % ",".join("%.2f" % t for t in times[:3]))
        return
    detected = sum(r["pose"] is not None for r in recs) / len(recs) if backend.kind else None
    print("      %d swings found, racket hand=%s (confidence: %s)" % (len(swings), hand, getattr(detect_swings, "hand_confidence", "given")), flush=True)
    detailed = pick_detailed(swings, args.max_swings)
    print("[2/3] detailed pose on %d swings..." % len(detailed), flush=True)
    jobs = detail_pass(args.video, backend, args, fps, swings, detailed, recs, stride, size, args.out)
    print("[3/3] writing filmstrips + metrics...", flush=True)
    import glob
    import shutil
    for old in glob.glob(os.path.join(args.out, "strip_s*.jpg")) + glob.glob(os.path.join(args.out, "peek_*.jpg")):
        os.remove(old)
    shutil.rmtree(os.path.join(args.out, "swings"), ignore_errors=True)
    swings_out, thumbs = [], []
    for sid in detailed:
        job = jobs[sid]
        if len(job["frames"]) < 6:
            continue
        cf = swings[sid]["f"] if swings[sid].get("sound") else None
        info = swing_metrics(job["frames"], fps, hand, cf) if backend.kind else None
        rec, cimg = write_swing(args.out, sid, job, info, fps, hand, args.strip_height)
        swings_out.append(rec)
        thumbs.append((sid, rec["time_s"], rec["guess"], cimg))
    overview(args.out, thumbs)
    dur = recs[-1]["f"] / fps
    times = [s["f"] / fps for s in swings]
    gaps = np.diff(times) if len(times) > 1 else np.array([])
    result = {
        "tool": "rate-my-tennis/analyze_video", "version": 1, "mode": mode,
        "video": {"file": os.path.basename(args.video), "fps": round(fps, 2), "duration_s": round(dur, 1),
                  "size": list(size)},
        "racket_hand": hand, "racket_hand_source": "user" if args.hand != "auto" else "auto-detected",
        "racket_hand_confidence": getattr(detect_swings, "hand_confidence", "given"),
        "pose_detection_rate": r1(detected, 2),
        "swings_detected": len(swings),
        "contact_timing": "impact sound" if onsets else "hand speed",
        "all_swing_times_s": [round(x, 1) for x in times],
        "median_gap_between_swings_s": r1(float(np.median(gaps)), 2) if len(gaps) else None,
        "swings": swings_out,
        "aggregate_by_guess": aggregate(swings_out),
        "notes": [
            "contact frame = the impact sound when audio is available (contact_from_sound), else peak racket-hand speed (+-2 frames).",
            "angles come from a monocular 3D pose estimate: trust elbow/knee to about +-10 deg, rotation to about +-20 deg.",
            "'guess' is a heuristic stroke label and is often wrong when the player stands side-on to the camera - label every swing by eye.",
            "left/right landmarks can swap when the player's back is to the camera; check the highlighted (orange) arm is the racket arm.",
        ],
    }
    with open(os.path.join(args.out, "analysis.json"), "w") as f:
        json.dump(result, f, indent=1)
    print("done in %.0fs -> %s" % (time.time() - t0, os.path.join(args.out, "analysis.json")))
    print("swings detected: %d | detailed: %s" % (len(swings), [s["id"] for s in swings_out]))
    for g, a in result["aggregate_by_guess"].items():
        print("  %-18s x%d" % (g, a["count"]))
    print("next: look at overview.jpg, then strip_sNN.jpg for each swing.")


if __name__ == "__main__":
    main()
