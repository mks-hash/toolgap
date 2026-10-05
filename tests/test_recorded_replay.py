"""Parser regression against retained actual model outputs; no inference."""

import hashlib
import json
import unittest
from research.agent_resume.replay import classifications, FIXTURES


class TestRecordedReplay(unittest.TestCase):
    def test_all_real_outputs_retain_declared_classification(self):
        result = classifications()
        self.assertEqual(result["cases"], 27)
        self.assertEqual(result["sources"], 3)
        self.assertEqual(result["original_useful_passes"], 0)

    def test_no_private_host_or_cloud_metadata_in_public_selection(self):
        # Join components so the privacy sentinel itself is not a local path.
        forbidden = [
            "/".join(["", "home", "m5"]) + "/",
            "sx-" + "project-501122",
            "Bearer ",
        ]
        for path in FIXTURES.glob("*.json"):
            raw = path.read_bytes()
            for value in forbidden:
                self.assertNotIn(value, raw.decode())
            record = json.loads(raw)
            self.assertEqual(record["schema_version"], 1)
            for source in record.get("sources", []):
                self.assertEqual(len(source["raw_sha256"]), 64)
                self.assertNotEqual(
                    source["raw_sha256"], hashlib.sha256(raw).hexdigest()
                )
