# `report.json` schema

`build_report.py` turns this file into the HTML report. All text fields accept `**bold**`. Every field not marked
required may be omitted; its section is then left out.

```jsonc
{
  "lang": "en",                      // required. "en" / "zh" have built-in labels; others: add "labels"
  "title": "Tennis Technique Report",// optional override
  "date": "2026-01-31",              // default: today
  "session": "Wall practice · left-handed",   // one line describing the footage
  "summary": "2-3 sentences: what is good, the main limiter, what to do first.",   // required
  "overall_score": 58,               // required, 0-100
  "level": {"value": "NTRP 3.0", "note": "range 2.5-3.0 · medium confidence (wall practice)"},

  "dimensions": [                    // required; keys from references/scoring.md, keep them stable across reports
    {"key": "preparation", "name": "Preparation", "score": 6.5, "comment": "one sentence of evidence"}
  ],

  "strokes": [                       // one per stroke type seen
    {"type": "forehand", "name": "Forehand", "score": 62, "count": 9,
     "summary": "one or two sentences",
     "good": ["short bullet"], "work_on": ["short bullet"]}
  ],

  "strengths": [                     // 2-3
    {"title": "Contact in front on the backhand", "detail": "why this is good and worth keeping",
     "evidence": { /* evidence object, see below */ }}
  ],

  "issues": [                        // 3-5, most important first
    {"id": "bend-knees",             // stable slug, reused in later reports
     "title": "Bending at the waist on low balls",
     "severity": "high",             // high | med | low
     "stroke": "Forehand / backhand",
     "metric": {"name": "Trunk lean on low balls", "value": "25-33°", "target": "under 15°"},
     "what": "what the picture shows",
     "why": "what it costs on court",
     "fix": "one physical instruction",
     "cue": "Sit, don't bow.",
     "evidence": [ /* 1-2 evidence objects */ ],
     "drills": [{"name": "Wall-sit shadow swings", "how": "one or two sentences", "dose": "3 x 10 daily"}]}
  ],

  "flipbooks": [                     // slow-motion scrubbers, 2-3
    {"swing": 4, "caption": "Forehand - watch where the racket goes after contact.",
     "from": -0.55, "to": 0.45, "skeleton": true}      // seconds relative to the detected contact; all optional.
                                                       // Shift the window (e.g. -0.3 .. 0.7) if the true contact is later
  ],

  "plan": [{"when": "Weeks 1-2", "focus": "Get lower", "tasks": ["...", "..."]}],

  "metrics_table": [{"name": "Forehand elbow at contact", "value": "84-146°", "reference": "consistent 100-130° or 150-175°", "note": "large spread = spacing varies"}],

  "next_recording_tips": ["..."],
  "progress_note": "Only with --previous: what improved, what did not.",
  "labels": {"issues": "..."}        // optional: override any built-in section label (needed for other languages)
}
```

Label keys you can override: `title overall level dims strokes strengths issues what why fix cue drills now target
flip plan metrics progress tips swings play pause legend_now legend_target metric you ref prev disclaimer high med
low shots first_report`.

## Evidence object

One still frame of the player with drawings on top.

```jsonc
{"swing": 57,                 // swing id from analysis.json
 "frame": "contact",          // ready | backswing | forward | contact | extension | finish, or a frame number
 "offset": 0,                 // optional: step N cached frames earlier (-) / later (+)
 "caption": "Red is now, green is where the back should be.",
 "marks": [ ... ],
 "skeleton": false,           // draw the faint full skeleton underneath
 "zoom": [0.1, 0.0, 0.9, 1.0] // optional manual crop (fractions). Default: auto-zoom on the player. false = full frame
}
```

### Points

Wherever a mark needs a point you can give:
- a landmark name: `nose, left_shoulder, right_shoulder, left_elbow, right_elbow, left_wrist, right_wrist,
  left_hip, right_hip, left_knee, right_knee, left_ankle, right_ankle, left_heel, right_heel, left_foot, right_foot`
  (left/right are the **player's** left and right)
- `mid_hip`, `mid_shoulder`, `head`
- `[x, y]` as fractions of that swing's cached frame (the player crop that `peek.py` shows, not the full video),
  read off the grid from `python scripts/peek.py OUT SWING FRAME`.
  Use this for the ball, the racket head, or when a landmark is misplaced.

Distances (`dx`, `dy`, `r`) are in **torso lengths** (shoulder-to-hip distance of the player in that frame);
+x is right in the picture, +y is down.

### Mark types

| type | fields | draws |
|---|---|---|
| `angle` | `joint` (`left_elbow`, `right_knee`, `left_shoulder`, `right_hip`, ...), `text`, `color` | The two limb segments and an arc at the joint. Default colour red; use `"color": "good"` to praise |
| `target_angle` | `joint`, `target` (degrees, as seen in the picture), `move` (`distal` default = the far segment moves, e.g. forearm; `proximal` = the near one), `text`, `target_text` | The joint now (red) and a green ghost segment that **animates** to the target angle |
| `rotate` | `pivot` (point), `chain` (list of points from the pivot outward, e.g. `["left_elbow","left_wrist"]`), `deg` (how far), `toward` (`up`/`down`/`left`/`right` or a point), `text`, `target_text` | The chain now (red) and a green ghost of the whole chain **swinging** about the pivot. Use for "raise the arm", "straighten the back" (`pivot: mid_hip, chain: [mid_shoulder, head]`) |
| `move` | `point`, `dx`, `dy`, `text` | A green ghost dot that **slides** from the point to where it should be ("hips lower", "contact further forward") |
| `circle` | `at`, `r` (default 0.18), `text`, `color` | A ring to highlight something |
| `arrow` | `from`, and `to` (point) or `dx`,`dy`; `text`, `color` | An arrow (default green) |
| `line` | `from`, `to`, `extend` (fraction to lengthen both ends), `dash`, `text`, `color` | A line, e.g. the shoulder line |
| `plumb` | `at`, `text` | A dashed vertical line through a point (balance: is the head over the feet?) |
| `label` | `at`, `dx`, `dy`, `text`, `color` | Text only |

Colours: `bad` (red), `good` (green), `info` (yellow), `white`, or any `#rrggbb`.

Guidelines
- 1-3 marks per picture. One idea per picture.
- Exported stills (`--export-images`) show ghosts at their green end position; the HTML animates them.
- `target` in `target_angle` and `deg` in `rotate` are what looks right **in the picture**, not the 3D metric.
  Aim for a believable posture, check the exported still, adjust.
- Keep on-picture text to 2-5 plain words; no emoji or symbols (they may not render in exported stills).
- Use a swing where the body part is clearly visible; a hidden arm has a guessed landmark.

## Minimal complete example

```json
{
  "lang": "en",
  "session": "Wall practice, camera behind, right-handed",
  "summary": "Steady rhythm and a full shoulder turn on the forehand. The main limiter is **straight legs on low balls**; fix that first, then the low serve contact.",
  "overall_score": 56,
  "level": {"value": "NTRP 3.0", "note": "range 2.5-3.0 · medium confidence"},
  "dimensions": [
    {"key": "preparation", "name": "Preparation", "score": 6.5, "comment": "Turns early on the forehand; backhand take-back is sometimes late."},
    {"key": "footwork", "name": "Footwork & balance", "score": 5, "comment": "Few adjusting steps; reaches for low balls by bowing."},
    {"key": "contact", "name": "Contact point", "score": 6, "comment": "In front on the backhand; forehand spacing varies."},
    {"key": "swing", "name": "Swing path & finish", "score": 5.5, "comment": "Mostly level swings that stop at chest height."},
    {"key": "kinetic", "name": "Legs & rotation", "score": 5, "comment": "Good turn, but the legs stay straight."},
    {"key": "consistency", "name": "Consistency", "score": 6.5, "comment": "Even rhythm, still head."}
  ],
  "strokes": [
    {"type": "forehand", "name": "Forehand", "score": 60, "count": 9, "summary": "Good turn; finish is low.",
     "good": ["Non-hitting arm points at the ball"], "work_on": ["Finish over the shoulder"]}
  ],
  "strengths": [
    {"title": "Full shoulder turn", "detail": "Your shoulders are sideways before the ball bounces - keep it.",
     "evidence": {"swing": 12, "frame": "backswing", "caption": "Turned and set early.",
                  "marks": [{"type": "line", "from": "left_shoulder", "to": "right_shoulder", "color": "good", "text": "shoulders turned"}]}}
  ],
  "issues": [
    {"id": "bend-knees", "title": "Bowing at the waist on low balls", "severity": "high", "stroke": "Forehand",
     "metric": {"name": "Trunk lean on low balls", "value": "about 30°", "target": "under 15°"},
     "what": "On balls below the waist your **legs stay straight** and you bow to reach the ball.",
     "why": "Your eyes drop with your head and the racket head hangs - low balls go into the net or fly long.",
     "fix": "Keep your back tall and sit down to the ball; then push up through the shot.",
     "cue": "Sit, don't bow.",
     "evidence": [{"swing": 12, "frame": "contact", "caption": "Red: now. Green: back upright, hips lower.",
                   "marks": [{"type": "rotate", "pivot": "mid_hip", "chain": ["mid_shoulder", "head"], "deg": 20, "toward": "up", "text": "bowing", "target_text": "back tall"},
                             {"type": "move", "point": "mid_hip", "dx": 0, "dy": 0.4, "text": "hips down"}]}],
     "drills": [{"name": "Wall-sit shadow swings", "how": "Back against a wall, thighs at 45°, ten slow swings keeping the back flat.", "dose": "3 x 10 daily"}]}
  ],
  "flipbooks": [{"swing": 12, "caption": "Forehand in slow motion - watch the knees."}],
  "plan": [{"when": "Weeks 1-2", "focus": "Get lower", "tasks": ["Wall-sit shadow swings daily", "5 minutes of low-ball feeds each session"]}],
  "next_recording_tips": ["Add a side-on clip so contact depth and knee bend are visible."]
}
```
