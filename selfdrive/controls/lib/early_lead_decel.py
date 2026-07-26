"""Bounded early deceleration for a corroborated slowing lead.

This is intentionally not an emergency-braking system. It closes the short interval in
which radarless Dynamic Experimental Control is still using ACC even though the driving
model already requests a mild slowdown for a stable lead. It can only cap acceleration;
harder braking from the normal planner always passes through.
"""

import math


LEAD_PROB_ON = 0.8
LEAD_PROB_OFF = 0.5
LEAD_STABLE_TIME = 0.5
CORROBORATION_TIME = 0.3
MODEL_DECEL_ON = -0.1
MODEL_DECEL_OFF = -0.05
LEAD_DECEL_ON = -0.1
LEAD_CLOSING_ON = -0.5
MIN_V_EGO = 8.0
MIN_START_DISTANCE = 15.0
MAX_TIME_GAP = 4.0
MAX_START_DISTANCE = 120.0
# Vision-only range can jump several meters between 20 Hz model updates even
# while the same lead remains selected. Reject large association steps without
# resetting the debounce on observed model quantization/noise.
MAX_RANGE_RATE = 200.0
FEATURE_ACCEL_FLOOR = -1.5
DOWN_JERK = 1.0
UP_JERK = 0.5


class EarlyLeadDecel:
  def __init__(self, dt: float):
    self.dt = dt
    self.lead_age = 0.0
    self.corroboration_age = 0.0
    self.active = False
    self.cap = 0.0
    self.prev_d_rel = None

  def reset(self) -> None:
    self.lead_age = 0.0
    self.corroboration_age = 0.0
    self.active = False
    self.cap = 0.0
    self.prev_d_rel = None

  @staticmethod
  def _finite(*values) -> bool:
    return all(math.isfinite(value) for value in values)

  def _smooth_release(self, baseline: float) -> float:
    if not self.active:
      return baseline
    self.cap = min(baseline, self.cap + UP_JERK * self.dt)
    output = min(baseline, self.cap)
    if self.cap >= baseline:
      self.active = False
    return output

  def update(self, baseline: float, system_active: bool, dec_is_acc: bool,
             v_ego: float, lead_status: bool, lead_prob: float, d_rel: float,
             v_rel: float, a_lead: float, model_accel: float,
             driver_override: bool = False) -> float:
    values_valid = self._finite(baseline, v_ego, lead_prob, d_rel, v_rel, a_lead, model_accel)
    if not system_active or driver_override or not values_valid:
      self.reset()
      return baseline

    plausible_range = True
    if self.prev_d_rel is not None:
      plausible_range = abs(d_rel - self.prev_d_rel) / self.dt <= MAX_RANGE_RATE
    self.prev_d_rel = d_rel

    lead_valid = lead_status and lead_prob >= (LEAD_PROB_OFF if self.active else LEAD_PROB_ON) and plausible_range
    if lead_valid:
      self.lead_age += self.dt
    else:
      self.lead_age = 0.0

    lead_evidence = a_lead < LEAD_DECEL_ON or v_rel < LEAD_CLOSING_ON
    model_evidence = model_accel < MODEL_DECEL_ON
    if lead_valid and model_evidence and lead_evidence:
      self.corroboration_age += self.dt
    elif not self.active:
      # Vision aLead/vRel can miss the threshold for one model frame while the
      # model action remains consistently negative. Decay accumulated evidence
      # instead of allowing one noisy sample to erase the full debounce.
      self.corroboration_age = max(0.0, self.corroboration_age - self.dt)

    max_start_distance = min(MAX_START_DISTANCE, MAX_TIME_GAP * v_ego)
    start_distance_ok = max(MIN_START_DISTANCE, v_ego) <= d_rel <= max_start_distance
    target = max(model_accel, FEATURE_ACCEL_FLOOR)
    qualified = (dec_is_acc and v_ego > MIN_V_EGO and start_distance_ok and
                 self.lead_age >= LEAD_STABLE_TIME and
                 self.corroboration_age >= CORROBORATION_TIME and
                 (self.active or baseline > target))

    if qualified:
      if not self.active:
        self.cap = baseline
        self.active = True
      # The normal planner has caught up and is already braking at least as
      # hard as the corroborated model request. Hand authority back; retaining
      # a lower stale cap here would stack unnecessary braking.
      if baseline <= target:
        self.reset()
        return baseline
      if target < self.cap:
        self.cap = max(target, self.cap - DOWN_JERK * self.dt)
      else:
        self.cap = min(target, self.cap + UP_JERK * self.dt)
      return min(baseline, self.cap)

    # Once DEC has switched to blended, or corroboration/lead quality is lost,
    # hand back smoothly. A harder normal-planner command still wins immediately.
    # Releasing the cap is itself jerk-limited, so a one-frame disagreement
    # cannot cause a surge. Do not hold stale braking merely because the model
    # remains negative after DEC has taken over.
    return self._smooth_release(baseline)
