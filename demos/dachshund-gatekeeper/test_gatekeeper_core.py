#!/usr/bin/python3
"""Host-safe tests for Gatekeeper tracking and authorization policy."""

import ast
from pathlib import Path
import types
import unittest


SOURCE = Path(__file__).with_name("gatekeeper.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
NAMES = {"Detection", "BreedResult", "DecisionEngine", "box_iou", "clamp"}
selected = [
    node for node in TREE.body
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in NAMES
]
module = types.ModuleType("gatekeeper_core")
module.__dict__["dataclass"] = __import__("dataclasses").dataclass
module.__dict__["Any"] = object
exec(compile(ast.Module(body=selected, type_ignores=[]), "gatekeeper.py", "exec"), module.__dict__)


class PolicyTests(unittest.TestCase):
    def test_iou(self):
        self.assertEqual(module.box_iou((0, 0, 10, 10), (20, 20, 30, 30)), 0)
        self.assertAlmostEqual(module.box_iou((0, 0, 10, 10), (0, 0, 10, 10)), 1)

    def test_three_stable_matches_authorize(self):
        policy = module.DecisionEngine("Dachshund", 0.72, 3)
        detection = module.Detection((10, 10, 100, 100), 0.9, 12.0)
        breed = module.BreedResult("Dachshund", 0.95, [], 7, 6, 10, 10)
        self.assertEqual(policy.update(detection, breed)[0], "VERIFYING")
        self.assertEqual(policy.update(detection, breed)[0], "VERIFYING")
        self.assertEqual(policy.update(detection, breed)[0], "AUTHORIZED")
        self.assertEqual(policy.track_frames, 3)

    def test_wrong_breed_is_held(self):
        policy = module.DecisionEngine("Dachshund", 0.72, 3)
        detection = module.Detection((10, 10, 100, 100), 0.9, 12.0)
        breed = module.BreedResult("Beagle", 0.91, [], 7, 6, 10, 10)
        self.assertEqual(policy.update(detection, breed)[0], "HELD")

    def test_three_misses_reset_tracker(self):
        policy = module.DecisionEngine("Dachshund", 0.72, 2)
        detection = module.Detection((10, 10, 100, 100), 0.9, 12.0)
        breed = module.BreedResult("Dachshund", 0.95, [], 7, 6, 10, 10)
        policy.update(detection, breed)
        policy.update(detection, breed)
        policy.update(None, None)
        policy.update(None, None)
        self.assertEqual(policy.update(None, None)[0], "WATCHING")
        self.assertEqual(policy.track_frames, 0)


if __name__ == "__main__":
    unittest.main()
