# Scoring

Scores exist so a player can see where they stand today and whether they improved next month. Consistency
matters more than precision: apply the same anchors every time.

## Dimensions (each 0-10, half points allowed)

Use these keys so reports line up over time. Drop a dimension only if the video gives no evidence for it
(e.g. no serves) - never guess.

| key | What to look at |
|---|---|
| `preparation` | Ready position, split step, early unit turn (shoulders and hips turn together), racket back before the ball bounces, non-hitting arm doing its job |
| `footwork` | Small adjusting steps, distance to the ball, stance suited to the ball, balance at contact, recovery after the shot |
| `contact` | Contact in front of the body, at a comfortable height and distance, arm structure stable, head still, eyes at contact |
| `swing` | Swing path (low-to-high for topspin), racket-head control, smooth acceleration, full follow-through |
| `kinetic` | Legs load and drive, hips lead shoulders, trunk rotation, force flows ground -> legs -> hips -> trunk -> arm instead of arm only |
| `serve` | Toss, trophy position, leg drive, upward extension to a high contact, pronation and follow-through (only if serves are shown) |
| `consistency` | The same swing shape every time: spread of contact height / distance / timing across swings, rhythm |

Optional extra keys when shown: `net_play` (volleys, overheads), `movement` (court coverage in match play),
`tactics` (shot selection in match play).

### Anchors

| Score | Meaning |
|---|---|
| 1-2 | Not yet a recognisable version of the skill |
| 3-4 | Recognisable but with major faults in most swings; works only on easy balls |
| 5-6 | Fundamentally there; clear faults that limit power or control; breaks down under pressure |
| 7-8 | Solid and repeatable; faults are refinements; holds up at pace |
| 9-10 | Advanced tournament / college / professional quality (rare - do not give this to club players) |

Most adult recreational players sit between 3 and 7. If every dimension comes out 7+, look again.

## Per-stroke score (0-100)

For each stroke type shown (forehand, backhand, serve, volley, overhead, slice): judge the phases - preparation,
loading, forward swing, contact, follow-through - plus repeatability, using the same anchors x10. Need at least
3 readable swings. With 1-2, still list the stroke with a score but say plainly that it rests on very little
evidence, and leave its dimension (e.g. `serve`) out of the radar and the overall score.
Use `type` values `forehand`, `backhand`, `serve`, `volley`, `overhead`, `slice` (one- or two-handed goes in the
display `name`), so strokes line up between reports.

## Overall score (0-100)

Average of the dimension scores x10, then adjust by at most +-5 for things the dimensions miss (e.g. clear
athleticism, or a single fault so severe it undermines everything). State the number without false precision in
the text ("around 60").

## Level estimate (NTRP)

Give a single value plus an honest range and confidence. Video of technique can only estimate level: NTRP is
defined by match results. Wall or feeding practice shows less than rally or match play - widen the range.

| NTRP | What the video typically shows | Overall score |
|---|---|---|
| 1.5-2.0 | Learning to make contact; no consistent swing shape; rallies of 1-3 balls | < 35 |
| 2.5 | Recognisable strokes at slow pace; short, pushing swings; little footwork; serve is a tap | 35-45 |
| 3.0 | Consistent on medium-paced balls; visible swing shape but arm-dominated; limited topspin; breaks down when stretched or rushed | 45-58 |
| 3.5 | Dependable strokes with some direction control and topspin; uses the legs and turn on most balls; a serve with a real motion | 58-68 |
| 4.0 | Repeatable technique with pace and spin on both wings; good preparation and recovery; serve is a weapon at times | 68-78 |
| 4.5 | Full kinetic chain, varied spins, handles pace; clean footwork patterns | 78-86 |
| 5.0+ | Tournament-trained technique throughout | 86+ |

If strokes differ a lot (e.g. 3.5 forehand, 2.5 serve), say so - the level follows the weakest shot a match
would expose. Other rating systems on request: UTR is roughly NTRP 3.0 = UTR 3-4, 3.5 = 4-5.5, 4.0 = 5.5-7,
4.5 = 7-9; ITN runs the other way, ITN 7 = NTRP 3.0, ITN 6 = 3.5, ITN 5 = 4.0.

## Severity of issues

- `high` - a root cause that limits several things, or an injury risk. At most two.
- `med` - clearly costs power or consistency.
- `low` - refinement worth doing once the above are in place.
