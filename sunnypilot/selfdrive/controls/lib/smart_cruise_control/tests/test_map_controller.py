"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import platform

from cereal import custom
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.car.cruise import V_CRUISE_UNSET
from openpilot.sunnypilot.selfdrive.controls.lib.smart_cruise_control.map_controller import SmartCruiseControlMap

MapState = VisionState = custom.LongitudinalPlanSP.SmartCruiseControl.MapState


class TestSmartCruiseControlMap:

  def setup_method(self):
    self.params = Params()
    self.mem_params = Params("/dev/shm/params") if platform.system() != "Darwin" else self.params
    self.reset_params()
    self.scc_m = SmartCruiseControlMap()

  def reset_params(self):
    self.params.put_bool("SmartCruiseControlMap", True, block=True)

    # TODO-SP: mock data from gpsLocation
    self.params.put("LastGPSPosition", "{}", block=True)
    self.params.put("MapTargetVelocities", "{}", block=True)

  def test_initial_state(self):
    assert self.scc_m.state == VisionState.disabled
    assert not self.scc_m.is_active
    assert self.scc_m.output_v_target == V_CRUISE_UNSET
    assert self.scc_m.output_a_target == 0.

  def test_system_disabled(self):
    self.params.put_bool("SmartCruiseControlMap", False, block=True)
    self.scc_m.enabled = self.params.get_bool("SmartCruiseControlMap")

    for _ in range(int(10. / DT_MDL)):
      self.scc_m.update(True, False, 0., 0., 0.)
    assert self.scc_m.state == VisionState.disabled
    assert not self.scc_m.is_active

  def test_disabled(self):
    for _ in range(int(10. / DT_MDL)):
      self.scc_m.update(False, False, 0., 0., 0.)
    assert self.scc_m.state == VisionState.disabled

  def test_transition_disabled_to_enabled(self):
    for _ in range(int(10. / DT_MDL)):
      self.scc_m.update(True, False, 0., 0., 0.)
    assert self.scc_m.state == VisionState.enabled

  def test_vision_corroboration_gates_map_curve(self):
    # A mapped curve requiring a highway-speed slowdown is only acted on when the camera (model)
    # also predicts a real bend -- this rejects OSM interchange/overpass artifacts that caused
    # phantom mid-highway slowdowns.
    self.scc_m.enabled = True
    self.scc_m.long_enabled = True
    self.scc_m.long_override = False
    self.scc_m.v_ego = 30.0
    self.scc_m.v_cruise = 30.0
    self.scc_m.v_target = 20.0
    self.scc_m.state = MapState.enabled

    # camera sees STRAIGHT road (phantom mapped curve) -> do NOT slow
    self.scc_m.vision_lat_acc = 0.1
    self.scc_m._update_state_machine()
    assert self.scc_m.state == MapState.enabled

    # camera CONFIRMS a real bend -> slow for the curve
    self.scc_m.vision_lat_acc = 1.2
    self.scc_m._update_state_machine()
    assert self.scc_m.state == MapState.turning

    # camera stops seeing the bend mid-slowdown -> abort the slowdown
    self.scc_m.vision_lat_acc = 0.3
    self.scc_m._update_state_machine()
    assert self.scc_m.state == MapState.enabled

  # TODO-SP: mock data from modelV2 to test other states
