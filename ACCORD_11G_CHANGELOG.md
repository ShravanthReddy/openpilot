# Accord 11G Fork — Change Log

Running record of every change we made on top of MVL's fork: the **problem**, the **root cause**,
and the **fix**. Newest first. Keep this updated whenever a new commit lands (template at bottom).

## ⚡ BASE MIGRATION (Aug 09) — `accord-11g-202607`

Old base (`sp-honda-dev-202606`) went EOL upstream; the on-car stack had accumulated three
unreviewed layers (our features + MVL sync + codex commits) while braking-at-stops complaints
persisted. **Reset to MVL's maintained release `sp-honda-202607`** (sunnypilot 2026.0002; includes
MVL's stopping tuning: `stoppingDecelRate` 0.1, `vEgoStopping` 0.5, stronger speed-invariant
brake PID <3 m/s) carrying ONLY two validated opendbc patches (`13921c86`): Accord slow pedal
learner (300) + factor sanity band. Everything else (ClosingAssist, lead-loss coast, SLA
coast-down, map camera-gate, e2e shaping, codex early-decel/radar-handoff) is retired from the
car; each may return one-at-a-time only with measured evidence on the new base. Old stack
preserved: branch `accord-11g-smooth` + device snapshot branches. Model: popv2 (unchanged).
Entries below this line predate the migration and describe the OLD base.

- **Fork:** `ShravanthReddy/openpilot` @ branch `accord-11g-202607` (+ submodule `ShravanthReddy/opendbc` @ `accord-11g-202607`)
- **Old fork (archived):** branch `accord-11g-smooth`
- **Base:** MVL `sp-honda-202607` @ `6bb75739e9` (opendbc base @ `2b81a4ad`)
- **Car:** 2025 Honda Accord 11G (HONDA_ACCORD_11G, Bosch CAN-FD) · Comma device · driving model popv2
- **Install:** `installer.comma.ai/ShravanthReddy/accord-11g-smooth`
- **Verification:** all changed modules pass their real test suites; car boots+runs clean (last checked commit `64d2805`).

---

## Summary table

| Commit | Date | Area | Problem → Fix |
|---|---|---|---|
| `8d80d2d`* | 07-20 | Car control (upstream) | Merged MVL's 4 Bosch CAN-FD longitudinal commits: **actuator delay 0.5→0.05 s** (CAN-FD has stock feedforward — big responsiveness fix), brake_pid limited to <3 m/s, radarless brake actuator faster. *(opendbc; openpilot submodule repointed)* |
| `fae75b5` | 07-20 | Tooling | (no car change) added `tools/accord/drive_report.py` — post-drive feature-behavior report |
| `d2b4af6` | 07-20 | Longitudinal | Surge/rear-end risk when a lead cuts out → coast gently back to speed (cap reaccel 0.6 m/s² for 2.5 s) |
| `64d2805` | 07-20 | Speed Limit | SLA could get stranded off → don't release the `pending` state on an unusable limit |
| `a4a4fb0` | 07-20 | Speed Limit | Hard braking on a limit *drop* (rear-end risk) → coast down gently (0.5 m/s²) instead |
| `583b63d` | 07-20 | Curve (map) | Phantom highway slowdowns from OSM overpass/interchange artifacts → require camera to confirm the bend |
| `6db9511` | 07-20 | Longitudinal | Late-then-hard braking on slower leads (model under-reports closing) → bounded gentle early decel (ClosingAssist, default OFF) |
| `ca8bc76` | 07-17 | Longitudinal | Hard e2e brake for a far, slow-closing lead (brake w/ space ahead) → soften onset only in that case |
| `89f7588` | 07-16 | Curve (vision) | Curve control entered too late → restore early-entry anticipation |
| `224da8a` | 07-15 | Longitudinal | Abrupt model-authored decel onset (blended mode) → shape/ramp the onset |
| `1e9c66e` | 07-15 | Curve (map) | Low-speed phantom slowdowns from map artifacts → engage map curve control only above 20 m/s (~45 mph) |
| `c8a00d9` | 07-15 | Longitudinal | Aggressive personality micro-braked (low jerk penalty) → "close but calm": keep 1.25 s gap, standard jerk |
| `3eaf176` | 07-15 | Longitudinal | Weak low-speed acceleration → raise low-speed cruise accel toward driver preference |
| `af2a391` | 07-15 | Curve (vision) | Curve control too conservative (slowed too much) → relax conservatism |
| `46e6484` | 07-14 | Curve (vision) | Uniform curve budget ignored EPS limit/speed → speed-aware lateral accel budget |
| `d1d4c02` | 07-14 | Speed Limit | Phantom braking toward stale/zeroed limit; unbounded pull-down → validity gate + bounded pull-down (⚠️ introduced the `64d2805` bug) |
| `ea6ef2f` | 07-14 | Build | Need the car-control fixes → point `opendbc_repo` submodule at our opendbc fork |
| `a9f12aa` | 07-14 | Speed Limit / Curve | Abrupt SLA braking; curve speed saturated EPS torque → smooth SLA + regulate curve under the ~2.4 m/s² EPS ceiling |
| **opendbc** | | | |
| `01858b1` | 07-14 | Car control | Brake-then-creep at stops; factors drifting non-physical; overstated torque → brake-release jerk limit + PID deadband, sanity-band factor persistence, honest torque factor |
| `7de5f16` | 07-13 | Car control | Acceleration surges (fast learner chasing powertrain lag); wild factors; gasmax typo → slow the pedal learner, reset factors at boot, fix typo |

---

## Detailed entries

### `8d80d2d` (opendbc) — Merge MVL's Bosch CAN-FD longitudinal update  *(upstream sync)*
- **What:** first upstream sync since we forked (June base). MVL's `sp-honda-dev-202606` advanced only by an opendbc submodule bump = 4 Honda Bosch CAN-FD commits, cherry-picked onto our opendbc branch:
  - `3d64171` **longitudinalActuatorDelay 0.5 → 0.05 s for HONDA_BOSCH_CANFD** — MVL found CAN-FD Accords have near-zero real actuator lag (stock feedforward correction). Our car had been planning around a 0.5 s delay that isn't there → over-anticipation/overshoot; likely root cause behind late-then-hard braking and the follow-distance oscillation.
  - `ea99d17` limit brake_pid augmentation to below 3 m/s (Bosch) — reduces extra braking at speed.
  - `3dadfb3` radarless brake actuator treated as faster.
  - `6303fd8` whitespace.
- **Conflict resolved:** `ea99d17` touched the same brake_pid block as our PID-deadband edit (`01858b1`). Kept MVL's `1e-3 < vEgo < 3.0` gate wrapping our deadband; our brake-release jerk-limit below is unchanged.
- **Files:** `opendbc/car/honda/interface.py`, `opendbc/car/honda/carcontroller.py`; openpilot `opendbc_repo` submodule repointed `01858b1 → 8d80d2d`.
- **Verified:** py_compile OK; on-device `test_car_interfaces` for ACCORD_11G after rebuild. **Live controller change — road-test supervised** (feel for smoother, better-timed braking).

### `d2b4af6` — Lead-loss coast
- **Problem:** when the car ahead changes lanes / disappears, the MPC re-accelerates toward cruise and can surge — surprising following traffic (rear-end risk).
- **Fix:** after a *sustained* lead cuts out, cap re-acceleration to **0.6 m/s²** for 2.5 s so it eases back to speed. Only caps acceleration (never braking); ignores detection flicker (lead must have been present ≥0.7 s); disabled below ~18 mph (normal stop-and-go launches); a new lead cancels it immediately.
- **Files:** `selfdrive/controls/lib/longitudinal_planner.py`
- **Verified:** logic tested across sustained-loss / flicker / stop-and-go / new-lead / braking cases (all pass). Always-on (no param). Logic-verified, not road-tested.

### `fae75b5` — drive_report.py tool  *(no car behavior change)*
- **Problem:** we validated features offline; needed a quick real-drive feedback loop.
- **Fix:** `tools/accord/drive_report.py` — run parked after a drive to summarize braking-by-cause, closing-assist activations, map-curve / speed-limit braking, lead cut-outs, and learned factors for a route.
- **Files:** `tools/accord/drive_report.py`

### `64d2805` — SLA: don't release the `pending` state on an unusable limit  *(bug fix)*
- **Problem:** Speed Limit Assist could quietly get stuck in the OFF (`inactive`) state and not recover.
- **Root cause:** the unusable-limit guard from `d1d4c02` also kicked the `pending` state (enabled, *waiting* for a speed limit — steers toward nothing) to `inactive` after ~1 s. On configs where `inactive` doesn't auto-recover, SLA stayed off.
- **Fix:** exclude `pending` from the guard — only release states that actively steer toward a limit (`active`/`adapting`/`preActive`). `pending` can't phantom-brake (no limit to steer toward).
- **Files:** `sunnypilot/.../speed_limit/speed_limit_assist.py`
- **Verified:** found by running the SLA test suite (1 failing → now **44/44 pass**).

### `a4a4fb0` — Speed Limit Assist: coast down gently on a limit DROP
- **Problem:** when the speed limit dropped, the car braked to reach the new (lower) limit quickly — dangerous on the highway (following traffic doesn't expect it).
- **Root cause:** SLA set the new lower limit as the target and the MPC braked as hard as needed toward it; the old `v_ego + LIMIT_MIN_ACC*4` clamp still permitted a hard brake.
- **Fix:** rate-limit the descent of the speed-limit target to a coast-like **0.5 m/s²** (`SLA_COAST_DECEL`) so the car eases off the gas instead of braking. Limit *increases* pass through unchanged.
- **Files:** `sunnypilot/.../longitudinal_planner.py`
- **Verified:** logic tested (70→55 mph now eases at 0.5 m/s² over ~13 s). Not yet road-tested.

### `583b63d` — Map curve control: require camera corroboration
- **Problem:** dangerous phantom mid-highway slowdowns (Atlanta drive) where the car braked −1.3 m/s² at 60–70 mph on **straight** road.
- **Root cause:** OSM map curvature mislabels overpass/interchange geometry on straight highway as curves; map curve control braked for them.
- **Fix:** a mapped curve now only slows the car when the driving model *also* predicts lateral acceleration ahead (camera sees a real bend): vision runs first, feeds its predicted max lat-accel to the map controller; turning state requires ≥0.8 m/s² (aborts <0.5, hysteresis).
- **Files:** `map_controller.py`, `smart_cruise_control.py`, `vision_controller.py`, `+ test`
- **Verified:** 12/12 curve tests pass (incl. new gate test). Validated on route 21: the 8:19 PM overpass phantom had camera signal 0.05 → suppressed; real curves 1.0–1.6 → kept.

### `6db9511` — ClosingAssist (default OFF)
- **Problem:** late-then-hard braking when catching up to a slower car; unsafe in low traction.
- **Root cause:** the vision model under-reports lead **closing speed** (wheel-anchored: mean ~3.6 m/s, worse the faster the real closing); the MPC therefore reacts late.
- **Fix:** derive a robust closing rate from the accurate distance *trend* and apply a bounded, jerk-limited early deceleration (≤1.0 m/s², ≤0.4 m/s³), faded out as the MPC brakes (no double-count). Rejects lead-switch/cut-in fabrication via an R²≥0.85 fit gate + state resets. Gated by `ClosingAssistEnabled` param.
- **Files:** `selfdrive/controls/lib/closing_assist.py` (new), `longitudinal_planner.py`, `common/params_keys.h`
- **Verified:** wheel-anchor study (79 approaches), real-MPC A/B (prevents the under-report crash, no over-brake, jerk ≤0.8), 12.5 h + 7.5 h frozen held-out corpora (383 interventions, 0 phantom), exhaustive merge-invariant proof (140,901 states, 0 violations). 5 rounds of adversarial (codex) review. **Enabled** on device (user opted to skip shadow).

### `ca8bc76` — Soften hard e2e brake onset only for far, slow-closing leads
- **Problem:** the car hard-braked for a distant, barely-slower lead even with lots of space ahead.
- **Fix:** in the e2e path, when radar confirms "ample room" (far + slow closing), ramp the decel onset instead of the instant hard-brake passthrough; otherwise keep the instant passthrough.
- **Files:** `selfdrive/controls/lib/longitudinal_planner.py`

### `89f7588` — Vision curve control: restore early-entry anticipation
- **Problem:** curve speed control reacted too late into curves.
- **Fix:** restore early-entry anticipation thresholds so it starts trimming speed before the bend.
- **Files:** `sunnypilot/.../smart_cruise_control/vision_controller.py`

### `224da8a` — Shape model-authored decel onset in blended mode
- **Problem:** abrupt braking when the model authored a hard decel in blended (DEC) mode.
- **Fix:** shape/ramp the model-authored decel onset instead of applying it instantly.
- **Files:** `selfdrive/controls/lib/longitudinal_planner.py`

### `1e9c66e` — Map curve control: engage only above 20 m/s
- **Problem:** phantom slowdowns at low/city speed from map intersection-geometry artifacts.
- **Fix:** gate map curve control to > 20 m/s (~45 mph) — highway only. (Later hardened by the camera-corroboration fix `583b63d`.)
- **Files:** `map_controller.py`

### `c8a00d9` — Aggressive personality: standard jerk, keep 1.25 s gap
- **Problem:** on the "aggressive" follow personality, stock's low jerk penalty (0.5) let decel spike and caused busy micro-braking while following.
- **Fix:** "close but calm" — keep aggressive's 1.25 s follow gap but use standard's jerk penalty (1.0). Gap is `T_FOLLOW`'s job, not jerk's.
- **Files:** `selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py`

### `3eaf176` — Raise low-speed cruise accel
- **Problem:** low-speed acceleration felt weak vs the driver's preference.
- **Fix:** raised the low-speed end of `A_CRUISE_MAX`.
- **Files:** `selfdrive/controls/lib/longitudinal_planner.py`

### `af2a391` — Vision curve control: relax conservatism
- **Problem:** curve control shed too much speed on gentle curves.
- **Fix:** relaxed the curve entering/turning thresholds per driver feedback.
- **Files:** `vision_controller.py`

### `46e6484` — Vision curve control: speed-aware lateral accel budget
- **Problem:** a single lateral-accel budget was wrong across the speed range (too tight at highway, near the EPS limit at speed).
- **Fix:** speed-aware budget `_A_LAT_REG_V=[1.9, 2.25]` over `_A_LAT_REG_BP=[11.2, 24.6]` m/s — comfort margin in the city, more cornering allowed on the highway (Honda EPS delivers ~2.4 m/s² max).
- **Files:** `vision_controller.py`

### `d1d4c02` — SLA: don't steer toward invalid/stale limits; bound pull-down
- **Problem:** phantom braking when SLA steered toward a stale/zeroed speed-limit value; unbounded target pull-down.
- **Fix:** `limit_usable` gate (require a valid limit above `LIMIT_MIN_SPEED`), release control after ~1 s of unusable limit, and bound the target pull-down. ⚠️ **This introduced a bug** (released the `pending` state too) — fixed in `64d2805`.
- **Files:** `speed_limit_assist.py`

### `ea6ef2f` — Point opendbc_repo at our fork
- **Problem:** needed the Accord 11G car-control fixes (below) which live in opendbc.
- **Fix:** repointed the `opendbc_repo` submodule to `ShravanthReddy/opendbc`.
- **Files:** `.gitmodules`, `opendbc_repo`

### `a9f12aa` — Smooth SLA braking; regulate curve speed under EPS ceiling
- **Problem:** abrupt SLA braking; vision curve speed control demanded more lateral accel than the Honda EPS can deliver (~2.4 m/s²), saturating steering in curves.
- **Fix:** smoothed SLA braking and lowered the curve-speed lateral-accel targets to stay under the measured EPS torque ceiling.
- **Files:** `speed_limit_assist.py`, `vision_controller.py`

---

## opendbc (car control) commits

### `01858b1` — Accord 11G round 2: smooth brake release, factor persistence, honest torque
- **Problem:** (a) brake-then-creep at stops (brake released abruptly then re-applied); (b) learned gas/wind factors drifting to non-physical values; (c) torque `LAT_ACCEL_FACTOR` overstated → steering saturation.
- **Fix:** brake-release jerk limit + brake-PID deadband (don't wind up on noise-level tracking error); **sanity-band factor persistence** (trust stored `HondaGasFactorParams` only in 0.6–1.6, `HondaWindFactorParams` in 0.5–2.0, else reset to 1.0); torque `LAT_ACCEL_FACTOR` 3.0 → 2.45.
- **Files:** `opendbc/car/honda/carcontroller.py`, `values.py`
- **Verified:** `test_car_interfaces` (Accord 11G) passes; persisted values load correctly on device (gas 0.705, wind 0.992 — in-band, in use).

### `7de5f16` — Accord 11G: slow pedal learning, reset factors at boot, gasmax typo
- **Problem:** acceleration surges — the fast pedal-force learner was chasing powertrain lag, not physics; wild factors persisted; a `gasmax` attribute typo.
- **Fix:** slowed the pedal learner (learn rate ~300), reset factors at boot, fixed the gasmax typo.
- **Files:** `opendbc/car/honda/carcontroller.py`

---

## How to add a new entry (template)
```
### `<hash>` — <short title>
- **Problem:** <what the driver/logs showed>
- **Root cause:** <why it happened>
- **Fix:** <what the change does>
- **Files:** <paths>
- **Verified:** <tests/data, or "logic-verified, not road-tested">
```
Then add a row to the Summary table above. Commit both this doc and the change together.
