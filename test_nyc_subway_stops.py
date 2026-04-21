import unittest
from unittest.mock import patch, MagicMock
import os
import json
import tempfile
import nyc_subway_stops


class TestNycSubwayStops(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for STOPS_FILE
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_stops_file = os.path.join(self.test_dir.name, "stops.json")
        # Patch the STOPS_FILE in the module
        self.patcher = patch("nyc_subway_stops.STOPS_FILE", self.test_stops_file)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.test_dir.cleanup()

    @patch("nyc_subway_stops.requests.get")
    def test_download_stops_success(self, mock_get):
        # Mock successful CSV response
        csv_content = (
            "GTFS Stop ID,Stop Name,Daytime Routes\n"
            "A19,103 St,A C\n"
            "B12,Canal St,B D\n"
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = csv_content
        mock_get.return_value = mock_response

        result = nyc_subway_stops.download_stops()
        self.assertTrue(result)

        # Verify the file was created and contains expected data
        self.assertTrue(os.path.exists(self.test_stops_file))
        with open(self.test_stops_file, "r") as f:
            data = json.load(f)
            self.assertIn("A19N", data)
            self.assertEqual(data["A19N"], "103 St [A C] (Uptown / Northbound)")
            self.assertIn("B12S", data)
            self.assertEqual(data["B12S"], "Canal St [B D] (Downtown / Southbound)")

    @patch("nyc_subway_stops.requests.get")
    def test_download_stops_failure(self, mock_get):
        # Mock failed response
        mock_get.side_effect = Exception("Network error")

        result = nyc_subway_stops.download_stops()
        self.assertFalse(result)

    @patch("nyc_subway_stops.requests.get")
    def test_download_stops_empty_id(self, mock_get):
        # Mock CSV with an empty Stop ID row
        csv_content = (
            "GTFS Stop ID,Stop Name,Daytime Routes\n"
            ",Invalid Stop,A\n"
            "A19,103 St,A C\n"
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = csv_content
        mock_get.return_value = mock_response

        result = nyc_subway_stops.download_stops()
        self.assertTrue(result)

        with open(self.test_stops_file, "r") as f:
            data = json.load(f)
            self.assertEqual(len(data), 2)  # A19N and A19S only


if __name__ == "__main__":
    unittest.main()
