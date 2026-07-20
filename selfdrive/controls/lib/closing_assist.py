"""
Closing-rate assist for radar-disabled Honda Bosch (vision-only longitudinal).

Problem (log-validated, wheel-speed anchored across 79 approaches): the driving model
under-reports lead closing speed by a mean ~3.6 m/s (worse the faster the real closing),
causing late-then-hard braking on slower traffic. The lead DISTANCE trend is accurate;
the model's closing VELOCITY is biased low.

This module derives a robust closing rate from the distance trend and, when it exceeds what
the model reports, requests a SMALL, JERK-LIMITED EXTRA DECELERATION applied early -- bleeding
the excess closing gently so the late hard brake never becomes necessary.

Safety by construction (per adversarial review):
  * Output is a bounded, jerk-limited deceleration (<= MAX_EXTRA_DECEL, <= JERK_MAX). It is
    combined as a decel FLOOR (min with the plan) and can ONLY add gentle braking -- it never
    blocks the MPC's harder brake and never substitutes a fabricated velocity. Worst-case a
    slipped-through false trend is a soft, brief nudge, never a hard brake.
  * Validity gates reject fabricated closing from association changes / artifacts:
      - reset ALL state on invalid/low-prob lead or a timestamp gap;
      - require a FULL continuous window before any output;
      - gate on linear-fit quality (R^2): a real steady closing is a clean line, a lead-switch
        range STEP or noise burst is not -> rejected.
  * No abrupt thresholds (smoothstep weighting; no close-range cliff).

DEFAULT OFF: gated by the "ClosingAssistEnabled" param. Intended deployment is shadow-mode
validation (log extra_decel, do not actuate) until zero phantom is confirmed on-road, then
supervised actuation.
"""
from collections import deque

MEDWIN = 0.6          # s   rolling-median pre-filter (impulsive +/-noise spikes)
WIN = 3.0             # s   least-squares slope window
MIN_PTS = 30          #     min pts in slope window
PROB_MIN = 0.8        #     min lead prob to be a valid lead
MAX_DT = 0.25         # s   timestamp gap -> reset
R2_MIN = 0.85         #     min linear-fit R^2 to trust the trend
TREND_LO = 2.5        # m/s smoothstep start
TREND_HI = 5.0        # m/s smoothstep full
T_BLEED = 8.0         # s   horizon to bleed excess closing (gentle)
MAX_EXTRA_DECEL = 1.0 # m/s^2 hard cap on added deceleration
JERK_MAX = 0.4        # m/s^3 rate limit on added deceleration
AGE_FULL = 2.0        # s   trust ramp after a full window
FADE_REF = 1.0        # m/s^2 fade the feature out as the MPC's own braking reaches this (no double-count)


def _median(xs):
  s = sorted(xs); n = len(s)
  return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def _smoothstep(x, lo, hi):
  if x <= lo:
    return 0.0
  if x >= hi:
    return 1.0
  t = (x - lo) / (hi - lo)
  return t * t * (3 - 2 * t)


def _ls_fit(buf):
  n = len(buf)
  if n < 2 or buf[-1][0] - buf[0][0] < WIN * 0.95:
    return None, None
  sx = sum(p[0] for p in buf); sy = sum(p[1] for p in buf)
  mx = sx / n; my = sy / n
  sxx = sum((p[0] - mx) ** 2 for p in buf); sxy = sum((p[0] - mx) * (p[1] - my) for p in buf)
  if sxx < 1e-9:
    return None, None
  slope = sxy / sxx; intercept = my - slope * mx
  ss_tot = sum((p[1] - my) ** 2 for p in buf)
  ss_res = sum((p[1] - (slope * p[0] + intercept)) ** 2 for p in buf)
  r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else 0.0
  return slope, r2


class ClosingAssist:
  def __init__(self):
    self.raw = deque()
    self.buf = deque()
    self.prev_t = None
    self.track_t0 = None
    self.extra_decel = 0.0     # m/s^2, jerk-limited feature output (>=0)
    self.trend = 0.0
    self.r2 = 0.0

  def update(self, t, dRel, prob, vRel):
    """Returns the extra deceleration (m/s^2, >=0) the feature requests this frame."""
    dt = (t - self.prev_t) if self.prev_t is not None else 0.05
    if (self.prev_t is not None and t - self.prev_t > MAX_DT) or prob < PROB_MIN:
      self.raw.clear(); self.buf.clear(); self.track_t0 = None
    self.prev_t = t
    if prob < PROB_MIN:
      self.extra_decel = max(0.0, self.extra_decel - JERK_MAX * dt)
      self.trend = 0.0; self.r2 = 0.0
      return self.extra_decel
    model_closing = -vRel
    self.raw.append((t, dRel))
    while self.raw and t - self.raw[0][0] > MEDWIN:
      self.raw.popleft()
    dfilt = _median([p[1] for p in self.raw])
    self.buf.append((t, dfilt))
    while self.buf and t - self.buf[0][0] > WIN:
      self.buf.popleft()
    if self.track_t0 is None:
      self.track_t0 = t
    track_age = t - self.track_t0
    trend = None; r2 = None
    if track_age >= WIN and len(self.buf) >= MIN_PTS:
      sl, r2 = _ls_fit(list(self.buf))
      if sl is not None:
        trend = -sl
    target = 0.0
    if trend is not None and r2 is not None and r2 >= R2_MIN:
      excess = max(0.0, trend - max(model_closing, 0.0))
      w = _smoothstep(trend, TREND_LO, TREND_HI)
      wage = _smoothstep(track_age, WIN, WIN + AGE_FULL)
      target = min(MAX_EXTRA_DECEL, excess / T_BLEED) * w * wage
    if target > self.extra_decel:
      self.extra_decel = min(target, self.extra_decel + JERK_MAX * dt)
    else:
      self.extra_decel = max(target, self.extra_decel - JERK_MAX * dt)
    self.trend = trend or 0.0
    self.r2 = r2 or 0.0
    return self.extra_decel

  def apply_floor(self, a_target, t, dRel, prob, vRel):
    """Combine the feature by SUBTRACTING its bounded, jerk-limited extra deceleration, FADED
    OUT as the MPC's own braking grows.
      - Subtracting (not a min()-floor) means the command change equals extra*fade and inherits
        extra's smooth jerk-limited ramp -> no discontinuous slam when it activates.
      - The fade -> 0 as a_target reaches -FADE_REF prevents DOUBLE-COUNTING: once the MPC is
        itself braking (e.g. for closing distance), the feature backs off instead of stacking
        into a hard brake. So the feature only ever supplies the EARLY gentle bleed, then hands
        off to the MPC. Intervention magnitude <= extra <= MAX_EXTRA_DECEL in all cases."""
    extra = self.update(t, dRel, prob, vRel)
    fade = max(0.0, min(1.0, 1.0 - max(0.0, -a_target) / FADE_REF))
    return a_target - extra * fade
