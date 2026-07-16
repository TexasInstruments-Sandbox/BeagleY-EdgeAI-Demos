#!/usr/bin/python3

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

try:
    import cv2  # noqa: F401
    import onnxruntime  # noqa: F401
except ModuleNotFoundError as error:
    raise unittest.SkipTest(f"runtime dependency unavailable: {error.name}") from error

MODULE_PATH = Path(__file__).resolve().parents[1] / "sentinel.py"
SPEC = importlib.util.spec_from_file_location("ev_spot_sentinel", MODULE_PATH)
sentinel = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = sentinel
SPEC.loader.exec_module(sentinel)


class SentinelLogicTests(unittest.TestCase):
    def test_vehicle_lower_center_is_assigned_to_polygon(self):
        vehicle = sentinel.Vehicle((20, 10, 60, 80), 0.9, "car", 12.0)
        spot = sentinel.SpotRuntime("EV-A", "EV A", [[0.1, 0.5], [0.8, 0.5], [0.8, 0.9], [0.1, 0.9]])
        self.assertTrue(sentinel.Sentinel._point_in_spot(vehicle, spot, 100, 100))

    def test_nfs_safe_store_and_leaderboard(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = sentinel.SessionStore(Path(temporary) / "sessions.sqlite3", 30)
            spot = sentinel.SpotRuntime("EV-A", "EV A", [[0, 0], [1, 0], [1, 1], [0, 1]])
            spot.started_utc = sentinel.utc_now()
            vehicle = sentinel.Vehicle((0, 0, 10, 10), 0.9, "car", 10.0)
            spot.session_id = store.start(spot, vehicle)
            read = sentinel.PlateRead((1, 1, 5, 4), "5AU5341", 0.92, 0.94, "Czech Republic", 20.0)
            store.identify(spot.session_id, read)
            store.end(spot, 42.0, True)
            self.assertEqual(store.connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(store.leaderboard()[0]["plate"], "5AU5341")
            self.assertEqual(store.leaderboard()[0]["longest_seconds"], 42.0)

    def test_plate_decoder_removes_padding_only(self):
        import numpy as np

        alphabet = sentinel.PLATE_ALPHABET
        logits = np.zeros((10, len(alphabet)), dtype=np.float32)
        for position, character in enumerate("AB12______"):
            logits[position, alphabet.index(character)] = 1.0
        characters = [alphabet[int(index)] for index in np.argmax(logits, axis=-1)]
        self.assertEqual("".join(characters).rstrip("_"), "AB12")


if __name__ == "__main__":
    unittest.main()
