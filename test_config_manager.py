import unittest
import os
import json
import tempfile
from config_manager import Config


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        # Create a temporary file for testing
        self.test_fd, self.test_path = tempfile.mkstemp()

    def tearDown(self):
        # Clean up the temporary file
        os.close(self.test_fd)
        if os.path.exists(self.test_path):
            os.remove(self.test_path)

    def test_default_values(self):
        # Use a non-existent file to ensure defaults are used
        config = Config(config_file="non_existent_file.json")
        self.assertEqual(config.get("portal_ssid"), "SubwayClock")
        self.assertEqual(config.get("day_brightness"), 100)

    def test_load_config(self):
        test_data = {"portal_ssid": "TestSSID", "day_brightness": 50}
        with open(self.test_path, 'w') as f:
            json.dump(test_data, f)

        config = Config(config_file=self.test_path)
        self.assertEqual(config.get("portal_ssid"), "TestSSID")
        self.assertEqual(config.get("day_brightness"), 50)
        # Check default still exists for other fields
        self.assertEqual(config.get("night_brightness"), 2)

    def test_set_and_save(self):
        config = Config(config_file=self.test_path)
        config.set("weather_zip", 90210)

        # Verify it saved to disk
        with open(self.test_path, 'r') as f:
            saved_data = json.load(f)
            self.assertEqual(saved_data["weather_zip"], 90210)

    def test_update_bulk(self):
        config = Config(config_file=self.test_path)
        new_data = {"routes": ["Q", "N"], "night_brightness": 5}
        config.update_bulk(new_data)

        self.assertEqual(config.get("routes"), ["Q", "N"])
        self.assertEqual(config.get("night_brightness"), 5)

    def test_to_dict(self):
        config = Config(config_file=self.test_path)
        config_dict = config.to_dict()
        self.assertIsInstance(config_dict, dict)
        self.assertEqual(config_dict["portal_ssid"], "SubwayClock")


if __name__ == '__main__':
    unittest.main()
