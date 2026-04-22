import unittest
import json
import os
import tempfile
from unittest.mock import patch

from config_manager import Config


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        # Create a temporary file to act as the config file
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.temp_file.close()
        self.config_file = self.temp_file.name

        self.valid_json = {
            "portal_ssid": "TestSSID",
            "day_brightness": 80,
            "weather_zip": 90210
        }
        with open(self.config_file, "w") as f:
            json.dump(self.valid_json, f)

    def tearDown(self):
        # Clean up the temporary file
        if os.path.exists(self.config_file):
            os.remove(self.config_file)

    def test_load_existing_config(self):
        config = Config(config_file=self.config_file)
        self.assertEqual(config.get("portal_ssid"), "TestSSID")
        self.assertEqual(config.get("day_brightness"), 80)
        self.assertEqual(config.get("weather_zip"), 90210)
        # Check default fallback
        self.assertEqual(config.get("stop_ids"), ["A19S"])

    def test_load_non_existing_config(self):
        config = Config(config_file="non_existent_file.json")
        self.assertEqual(config.get("portal_ssid"), "SubwayClock")
        self.assertEqual(config.get("day_brightness"), 100)

    @patch("config_manager.logging.error")
    def test_load_invalid_json(self, mock_logging_error):
        with open(self.config_file, "w") as f:
            f.write("INVALID JSON")
        config = Config(config_file=self.config_file)
        self.assertEqual(config.get("portal_ssid"), "SubwayClock")
        mock_logging_error.assert_called_once()

    def test_is_modified(self):
        config = Config(config_file=self.config_file)
        self.assertFalse(config.is_modified())

        # Modify the file
        with open(self.config_file, "w") as f:
            json.dump({"portal_ssid": "NewSSID"}, f)
        
        # We need to simulate time passing for mtime to definitely update on some filesystems
        # Or just mock os.path.getmtime
        with patch("os.path.getmtime", return_value=config._last_mtime + 10):
            self.assertTrue(config.is_modified())

    def test_is_modified_non_existent(self):
        config = Config(config_file="non_existent_file.json")
        self.assertFalse(config.is_modified())

    def test_is_modified_os_error(self):
        config = Config(config_file=self.config_file)
        with patch("os.path.getmtime", side_effect=OSError):
            self.assertFalse(config.is_modified())

    def test_save(self):
        config = Config(config_file=self.config_file)
        config.config["portal_ssid"] = "SavedSSID"
        config.save()
        
        with open(self.config_file, "r") as f:
            data = json.load(f)
        self.assertEqual(data["portal_ssid"], "SavedSSID")

    @patch("config_manager.logging.error")
    def test_save_io_error(self, mock_logging_error):
        config = Config(config_file=self.config_file)
        with patch("builtins.open", side_effect=IOError("Test Error")):
            config.save()
        mock_logging_error.assert_called_once()
        self.assertIn("Error writing config file", mock_logging_error.call_args[0][0])

    @patch("config_manager.logging.error")
    def test_save_unexpected_error(self, mock_logging_error):
        config = Config(config_file=self.config_file)
        with patch("builtins.open", side_effect=Exception("Test Exception")):
            config.save()
        mock_logging_error.assert_called_once()
        self.assertIn("An unexpected error occurred", mock_logging_error.call_args[0][0])

    def test_get_with_default(self):
        config = Config(config_file=self.config_file)
        self.assertEqual(config.get("non_existent_field", "default_val"), "default_val")

    def test_set(self):
        config = Config(config_file=self.config_file)
        config.set("weather_zip", 10001)
        self.assertEqual(config.get("weather_zip"), 10001)
        
        with open(self.config_file, "r") as f:
            data = json.load(f)
        self.assertEqual(data["weather_zip"], 10001)

    def test_update_bulk(self):
        config = Config(config_file=self.config_file)
        config.update_bulk({"portal_ssid": "BulkSSID", "day_brightness": 50})
        self.assertEqual(config.get("portal_ssid"), "BulkSSID")
        self.assertEqual(config.get("day_brightness"), 50)
        
        with open(self.config_file, "r") as f:
            data = json.load(f)
        self.assertEqual(data["portal_ssid"], "BulkSSID")
        self.assertEqual(data["day_brightness"], 50)

    def test_to_dict(self):
        config = Config(config_file=self.config_file)
        d = config.to_dict()
        self.assertEqual(d["portal_ssid"], "TestSSID")
        self.assertIsNot(d, config.config)

if __name__ == "__main__":
    unittest.main()
