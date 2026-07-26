import pytest

from openpilot.selfdrive.controls.lib.early_lead_decel import (
  CORROBORATION_TIME,
  DOWN_JERK,
  FEATURE_ACCEL_FLOOR,
  LEAD_STABLE_TIME,
  UP_JERK,
  EarlyLeadDecel,
)


DT = 0.05


def update(guard, baseline=0.5, **kwargs):
  defaults = {
    "system_active": True,
    "dec_is_acc": True,
    "v_ego": 20.0,
    "lead_status": True,
    "lead_prob": 0.95,
    "d_rel": 50.0,
    "v_rel": -1.0,
    "a_lead": -0.2,
    "model_accel": -0.3,
  }
  defaults.update(kwargs)
  return guard.update(baseline=baseline, **defaults)


def qualify(guard, baseline=0.5):
  frames = int(max(LEAD_STABLE_TIME, CORROBORATION_TIME) / DT) + 1
  return [update(guard, baseline=baseline) for _ in range(frames)]


def test_debounces_before_capping_acceleration():
  guard = EarlyLeadDecel(DT)
  outputs = [update(guard) for _ in range(int(LEAD_STABLE_TIME / DT) - 1)]
  assert outputs == [0.5] * len(outputs)
  assert not guard.active


def test_cap_begins_with_bounded_downward_jerk():
  guard = EarlyLeadDecel(DT)
  outputs = qualify(guard)
  first_changed = next(i for i, value in enumerate(outputs) if value < 0.5)
  assert outputs[first_changed] == pytest.approx(0.5 - DOWN_JERK * DT)
  assert guard.active


def test_never_weakens_harder_planner_braking():
  guard = EarlyLeadDecel(DT)
  qualify(guard)
  assert update(guard, baseline=-2.3) == -2.3


def test_does_not_activate_when_planner_already_brakes_harder_than_model():
  guard = EarlyLeadDecel(DT)
  for _ in range(30):
    assert update(guard, baseline=-1.0, model_accel=-0.3) == -1.0
  assert not guard.active


def test_feature_acceleration_floor_is_absolute():
  guard = EarlyLeadDecel(DT)
  outputs = []
  for _ in range(100):
    outputs.append(update(guard, model_accel=-3.0))
  assert min(outputs) == pytest.approx(FEATURE_ACCEL_FLOOR)


def test_probability_chatter_does_not_activate():
  guard = EarlyLeadDecel(DT)
  for probability in [0.81, 0.79] * 20:
    output = update(guard, lead_prob=probability)
    assert output == 0.5
  assert not guard.active


def test_single_frame_vision_spike_does_not_activate():
  guard = EarlyLeadDecel(DT)
  for _ in range(30):
    update(guard, v_rel=1.0, a_lead=0.1, model_accel=0.1)
  update(guard, v_rel=-10.0, a_lead=-3.0, model_accel=-2.0)
  assert not guard.active


def test_single_frame_evidence_dropout_does_not_erase_debounce():
  guard = EarlyLeadDecel(DT)
  for _ in range(5):
    update(guard)
  update(guard, v_rel=0.1, a_lead=0.1)
  for _ in range(3):
    update(guard)
  assert guard.corroboration_age > 0.0


def test_pulling_away_lead_does_not_activate():
  guard = EarlyLeadDecel(DT)
  for _ in range(30):
    assert update(guard, v_rel=1.0, a_lead=0.1) == 0.5
  assert not guard.active


def test_abrupt_range_handoff_resets_debounce():
  guard = EarlyLeadDecel(DT)
  for _ in range(8):
    update(guard)
  assert update(guard, d_rel=80.0) == 0.5
  assert not guard.active


def test_lead_loss_releases_smoothly():
  guard = EarlyLeadDecel(DT)
  qualify(guard)
  for _ in range(20):
    update(guard)
  before = guard.cap
  after = update(guard, lead_status=False, lead_prob=0.0)
  assert after == pytest.approx(before + UP_JERK * DT)


def test_driver_override_is_immediate_passthrough():
  guard = EarlyLeadDecel(DT)
  qualify(guard)
  assert update(guard, baseline=0.7, driver_override=True) == 0.7
  assert not guard.active


def test_outside_speed_scaled_start_range_does_not_activate():
  guard = EarlyLeadDecel(DT)
  for _ in range(30):
    assert update(guard, d_rel=100.0) == 0.5
  assert not guard.active
