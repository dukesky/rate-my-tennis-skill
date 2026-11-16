# Technique checkpoints, common faults, and how to read the metrics

Contents: 1. Reading the metrics · 2. Forehand · 3. Two-handed backhand · 4. One-handed backhand ·
5. Serve · 6. Volley · 7. Overhead · 8. Slice · 9. Footwork and movement · 10. Drill library

Sides: "hitting side" = racket-hand side. For a left-hander mirror everything (their forehand finishes over
the right shoulder; their front foot on the forehand is the right foot and on the backhand the left foot).

## 1. Reading the metrics in `analysis.json`

All angles come from a single-camera 3D pose estimate. Treat them as "about", and always confirm on the frame.

| Metric | Meaning | Typical good range | Reliability |
|---|---|---|---|
| `elbow_angle_contact` | Hitting-arm elbow at contact (180 = straight) | Forehand: 100-130 double-bend, 150-175 straight-arm style - both fine if **consistent**; under ~95 is cramped. 2H backhand: front arm 150-175. 1H backhand: 165-180. Serve: 165-180 | Fair from side/front; poor from behind when the arm points at or away from the camera |
| `elbow_angle_backswing` | Same, at the end of the take-back | Forehand 80-130 | Fair |
| `knee_min_hitting_side`, `knee_min_other_side` | Deepest knee bend in the 0.6 s before contact (180 = straight leg) | Groundstrokes 110-145; serve 100-135; above ~155 = legs not used | Fair from side; from behind bends look smaller than they are - confirm by eye |
| `knee_at_contact_avg` | Knees at contact | 140-170 (legs extending up into the ball). If equal to the minimum, the legs never loaded | Fair |
| `hip_shoulder_separation_max` | How far the shoulders turn beyond the hips while loading | 15-40 degrees | Poor (+-20) - use only as a hint |
| `shoulder_rotation_range` | Shoulder-line turn from backswing to finish | Groundstrokes 90-180; under ~60 = arm-only swing | Poor to fair - compare swings with each other rather than with the range |
| `contact_height` | Hand height at contact: 0 = hip, 1 = shoulder | Groundstrokes 0.1-0.9 (waist to chest ideal). Serve: 1.9+ means a fully extended reach; under ~1.6 is a low contact | Good |
| `contact_side_reach` | Sideways distance of the hand from the chest midline, in shoulder widths | Forehand 0.9-1.6; under ~0.6 = jammed. Spread across swings = spacing consistency | Good from behind/front, poor from the side |
| `stance_width` | Feet apart at contact, in shoulder widths | 1.2-2.0 for groundstrokes; under 1.0 = narrow, upright base | Fair |
| `trunk_lean_deg` | Trunk tilt from vertical at contact (in the image plane) | Under 15 on groundstrokes; 20+ on low balls with straight knees = bending at the waist | Good when the lean is across the image |
| `head_movement` | Head travel around contact, in torso lengths | Under 0.25 | Good |
| `finish_height` | Highest hand position after contact relative to the hitting shoulder, in torso lengths (0 = shoulder height) | Topspin forehand/2H backhand: 0 to 0.5 (hand finishes at or above the shoulder). Well below 0 = flat, short finish | Good |
| `peak_hand_speed` | Hand speed near contact, torso lengths per second | Relative only: compare strokes and sessions | Fair |
| `backswing_to_contact_s` | Time from racket-back to contact | 0.35-0.7. Under ~0.25 = rushed / late preparation | Fair |
| `two_hands_at_contact` | Both hands close together at contact | - | Fair |

**Camera geometry matters.** "From behind" in the table means the player's back is square to the camera. In
wall practice and rallies the player often stands **side-on to a camera behind them**; then sideways measures
(`contact_side_reach`, `stance_width`) lie along the depth axis and are unreliable, while `trunk_lean_deg`, knee
bend and contact front/back become easier to see. Left/right landmarks can also swap on back views. Decide what
the camera can actually see for each swing before quoting a number.

The **spread** (sd) of a metric across swings of one stroke is itself a finding: a contact height or reach that
varies a lot means the player is not positioning consistently.

## 2. Forehand

| Phase | What good looks like | Common faults -> what you see |
|---|---|---|
| Ready / split | Balanced, knees soft, racket in front, small hop as the opponent (or wall) contacts | Flat-footed, standing tall -> first move is late |
| Unit turn | Shoulders and hips turn together as soon as the ball's side is read; non-hitting hand stays on the racket throat then extends across, pointing at the ball | Arm-only take-back: racket goes back but chest still faces the net. Non-hitting arm hangs dead |
| Take-back | Racket head up, compact loop, set before the bounce | Huge loop or racket far behind the body -> late contact. Racket still going back when the ball bounces |
| Load | Weight on the outside leg, knee bent, hips coiled | Straight legs; for low balls bends at the waist instead of the knees |
| Forward swing | Racket drops below the ball, hips then shoulders unwind, racket lags then releases | Starts from above the ball -> flat/down swing. Arm starts before the hips |
| Contact | In front of the front hip, comfortable arm's length away, waist-to-chest height, head still, eyes at the ball | Late (beside or behind the body), jammed (elbow tucked into the ribs), reaching (falling toward the ball), head pulling away early |
| Extension / finish | Racket travels through and up; finishes over the opposite shoulder or wrapped around the upper arm; chest faces the target; balanced | Stops at the waist or chest (push); falls backward; no rotation |
| Recovery | Split and move back toward centre | Watching the shot |

Cues that work: "turn first", "point at the ball", "below the ball, then brush up", "hit in front of your hip",
"finish with the hand by your ear / racket over the shoulder", "sit, don't bow" (for low balls).

## 3. Two-handed backhand

| Phase | Good | Faults |
|---|---|---|
| Unit turn | Both hands take the racket back with the shoulder turn; front shoulder under the chin; back to the net slightly | Arms pull back without a turn; late start |
| Load | Knees bent, weight shifts to the back foot then forward; racket head drops below the hands | Upright, straight legs; bending at the waist for low balls |
| Contact | In front of the front hip; both arms comfortably extended (front arm nearly straight); top hand drives - "a forehand with the non-dominant hand" | Contact too close or too far back; arms folded (chicken wings); bottom hand pulling instead of top hand pushing |
| Finish | Hands finish high by the opposite ear or over the shoulder, elbows up, hips and chest facing the target | Short poke; finish at chest height; no hip rotation |

Cues: "turn the shoulders, the racket comes along", "push with the top hand", "both arms long at contact",
"finish with the hands by the ear".

## 4. One-handed backhand

Good: full shoulder turn with the non-hitting hand cradling the throat; contact well in front with a straight
arm; shoulder stays sideways through contact while the non-hitting arm goes back for balance; high finish.
Faults: opening the chest too early; leading with the elbow (bent arm at contact); contact late; wrist flick.
Cues: "stay sideways", "arm straight before contact", "spread the wings".

## 5. Serve

| Phase | Good | Faults |
|---|---|---|
| Stance / start | Sideways, weight calm, continental grip | Facing the net; forehand (frying-pan) grip -> pushed serve, racket face open at the trophy position |
| Toss | Arm lifts straight and releases at about eye level; ball goes to full reach height or a bit above, slightly in front and to the hitting side | Low toss -> cramped, bent-arm contact. Toss behind or too far left/right -> arched back or side-arm swing |
| Trophy | Tossing arm up, hitting elbow at shoulder height, racket tip up, knees bent, hips forward | No knee bend; elbow low; no pause/rhythm; tossing arm drops early |
| Drop and drive | Racket drops behind the back as the legs drive up | No racket drop ("waiter's tray": racket face to the sky) |
| Contact | Arm and racket fully extended at the highest reach, slightly in front; body stretched upward; head up | Contact low or beside the head; elbow bent; arm swinging out to the side at an angle; eyes drop early |
| Finish | Pronation, racket finishes across the body; lands on the front foot inside the court | Stops at contact; falls sideways or backward |

Cues: "toss higher, reach up", "elbow up, tip up", "up and out", "land on the front foot".
From behind you can judge toss left/right, reach height, arm angle, knee bend and landing; toss depth
(in front/behind) needs a side view.

## 6. Volley

Good: split step; continental grip; racket set in front with a short turn of the shoulders and almost no
backswing; step forward with the opposite foot; contact in front with a firm wrist, racket head above the wrist;
short punch that stops soon after contact.
Faults: swinging; racket taken behind the shoulder; contact beside the body; dropping the racket head; no step.
Cues: "catch it in front", "punch, don't swing", "racket head up".

## 7. Overhead

Like a serve without the toss: turn sideways at once, racket up early, non-hitting hand points at the ball,
move with side or cross steps, contact at full reach in front. Faults: backpedalling facing the net, letting the
ball drop, bent-arm contact.

## 8. Slice

Good: continental grip, shoulder turn, racket starts above the ball, high-to-low path with a slightly open face,
contact in front, long follow-through toward the target, stays sideways. Faults: chopping steeply down, face too
open (floaters), opening the chest.

## 9. Footwork and movement

- Split step timed to the opponent's (or the wall's) contact.
- Many small adjusting steps just before the hit; the last step sets the distance.
- Low balls: bend the knees and keep the back upright. Bowing at the waist with straight legs is one of the most
  common recreational faults and shows clearly from any angle (`trunk_lean_deg` high, knees ~160+).
- Recovery steps after every shot; in wall practice, returning to a ready position between hits.
- Balance: head over the base of support at contact; no falling away.

## 10. Drill library (pick what fits, adapt the dose)

| Goal | Drill |
|---|---|
| Earlier preparation | "Bounce-hit": say "turn" when the ball leaves the wall/opponent, "bounce" on the bounce, "hit" at contact; the turn must be finished by "bounce" |
| Spacing / jammed contact | Catch the ball on the strings with a straight arm without swinging (20 balls); cone or line marking the ideal distance |
| Contact in front | Shadow swings freezing at contact, checking the racket is ahead of the front hip; mini-tennis from the service line |
| Topspin / low-to-high / high finish | "Touch the shoulder" finish check; hitting over a line 1.5 m high on a wall; drop-feed and brush up |
| Using the legs / low balls | Wall-sit shadow swings; low-ball feeds with the rule "hands below knees, back straight" |
| Rotation / kinetic chain | Medicine-ball or two-hand racket-throws sideways; hitting with the feet planted, focusing on hips then shoulders |
| Serve reach and toss | Toss-only practice landing on a racket laid in front of the front foot; "touch the mark" - reach a mark at full racket height before each serve; kneeling serves |
| Serve rhythm / trophy | Pause in the trophy position for one second, then drive up |
| Volley | Catch-and-drop with the racket; wall volleys from 2-3 m, 20 in a row without a backswing |
| Consistency | Wall rallies with a target count (10, 20, 30 in a row) above a line; rally at 60 % pace counting clean contacts |
| Split step | Hop every time the ball hits the wall / the opponent hits |

Doses that work for recreational players: 5-10 minutes of one drill at the start of each session, 2-3 sessions
a week, for two weeks, before moving to the next priority.
