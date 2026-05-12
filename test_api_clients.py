import unittest
from unittest.mock import patch, MagicMock
import time
import logging
import requests

# Disable logging during tests to keep console clean
logging.disable(logging.CRITICAL)

# We must mock google.transit if we run this in an environment without the proto files
import sys

sys.modules["google"] = MagicMock()
sys.modules["google.transit"] = MagicMock()
sys.modules["google.transit.gtfs_realtime_pb2"] = MagicMock()

from api_clients import WeatherClient, TransitClient


class TestWeatherClient(unittest.TestCase):
    def setUp(self):
        self.client = WeatherClient()

    @patch("api_clients.requests.Session.get")
    def test_get_lat_lon_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "places": [{"latitude": "40.7128", "longitude": "-74.0060"}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        lat, lon = self.client.get_lat_lon("10001")

        self.assertEqual(lat, 40.7128)
        self.assertEqual(lon, -74.0060)
        self.assertEqual(self.client.weather_zip, "10001")
        mock_get.assert_called_once()

        # Test caching mechanism (should not call requests.get again)
        lat2, lon2 = self.client.get_lat_lon("10001")
        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(lat2, 40.7128)

    @patch("api_clients.requests.Session.get")
    def test_get_lat_lon_failure(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("API Down")

        lat, lon = self.client.get_lat_lon("00000")

        # Fallback values
        self.assertEqual(lat, 41.50)
        self.assertEqual(lon, -73.97)

    @patch("api_clients.WeatherClient.get_lat_lon")
    @patch("api_clients.requests.Session.get")
    def test_get_current_weather_success(self, mock_get, mock_get_lat_lon):
        mock_get_lat_lon.return_value = (40.7128, -74.0060)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "current_weather": {"temperature": 72.5, "weathercode": 51}
        }
        mock_get.return_value = mock_response

        result = self.client.get_current_weather("10001")

        self.assertIsNotNone(result)
        self.assertEqual(result["temperature"], 72)  # Expects int casting
        self.assertEqual(result["weathercode"], 51)

    @patch("api_clients.WeatherClient.get_lat_lon")
    @patch("api_clients.requests.Session.get")
    def test_get_current_weather_missing_data(self, mock_get, mock_get_lat_lon):
        mock_get_lat_lon.return_value = (40.7128, -74.0060)
        mock_response = MagicMock()
        mock_response.json.return_value = {}  # Empty JSON
        mock_get.return_value = mock_response

        result = self.client.get_current_weather("10001")
        self.assertIsNone(result)

    @patch("api_clients.WeatherClient.get_lat_lon")
    @patch("api_clients.requests.Session.get")
    def test_get_current_weather_exception(self, mock_get, mock_get_lat_lon):
        mock_get_lat_lon.return_value = (40.7128, -74.0060)
        mock_get.side_effect = requests.exceptions.RequestException(
            "Connection Refused"
        )

        result = self.client.get_current_weather("10001")
        self.assertIsNone(result)

    @patch("api_clients.WeatherClient.get_lat_lon")
    @patch("api_clients.requests.Session.get")
    def test_get_sun_forecast_success(self, mock_get, mock_get_lat_lon):
        mock_get_lat_lon.return_value = (40.7128, -74.0060)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "timezone": "America/New_York",
            "daily": {"sunrise": ["2026-04-21T06:07"], "sunset": ["2026-04-21T19:41"]},
        }
        mock_get.return_value = mock_response

        result = self.client.get_sun_forecast("10001")

        self.assertIsNotNone(result)
        self.assertEqual(result["sunrise"][0], "2026-04-21T06:07")
        self.assertEqual(result["sunset"][0], "2026-04-21T19:41")
        self.assertEqual(result["timezone"], "America/New_York")

    @patch("api_clients.WeatherClient.get_lat_lon")
    @patch("api_clients.requests.Session.get")
    def test_get_sun_forecast_missing_data(self, mock_get, mock_get_lat_lon):
        mock_get_lat_lon.return_value = (40.7128, -74.0060)
        mock_response = MagicMock()
        mock_response.json.return_value = {"daily": {}}  # Missing keys
        mock_get.return_value = mock_response

        result = self.client.get_sun_forecast("10001")
        self.assertIsNone(result)

    @patch("api_clients.WeatherClient.get_sun_forecast")
    def test_get_timezone_success(self, mock_get_sun_forecast):
        """Returns the timezone field from the sun-forecast response."""
        mock_get_sun_forecast.return_value = {
            "sunrise": ["2026-04-21T06:07"],
            "sunset": ["2026-04-21T19:41"],
            "timezone": "America/New_York",
        }

        result = self.client.get_timezone("10001")

        self.assertEqual(result, "America/New_York")
        mock_get_sun_forecast.assert_called_once_with("10001")

    @patch("api_clients.WeatherClient.get_sun_forecast")
    def test_get_timezone_api_failure(self, mock_get_sun_forecast):
        """Returns None when the sun-forecast call fails."""
        mock_get_sun_forecast.return_value = None

        result = self.client.get_timezone("00000")

        self.assertIsNone(result)


class TestTransitClient(unittest.TestCase):
    def setUp(self):
        self.client = TransitClient()
        # To avoid making requests to 8 URLs, we trim the FEED_URLS down
        self.client.FEED_URLS = ["http://fake-mta-url"]

    @patch("api_clients.gtfs_realtime_pb2.FeedMessage")
    @patch("api_clients.requests.Session.get")
    def test_fetch_upcoming_trains_success(self, mock_get, mock_feed_msg_class):
        # Mock requests.get response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"fake protobuf binary"
        mock_get.return_value = mock_response

        # Mock the protobuf FeedMessage
        mock_feed = MagicMock()
        mock_feed_msg_class.return_value = mock_feed

        # Mock a valid Train entity
        mock_entity = MagicMock()
        mock_entity.HasField.return_value = True
        mock_entity.trip_update.trip.route_id = "A"

        mock_stop_time = MagicMock()
        mock_stop_time.stop_id = "A19S"
        mock_stop_time.HasField.side_effect = lambda field: True  # "arrival" and "time"
        mock_stop_time.arrival.time = 10120  # 10000 + 120 (2 mins out)

        mock_entity.trip_update.stop_time_update = [mock_stop_time]
        mock_feed.entity = [mock_entity]

        arrivals = self.client.fetch_upcoming_trains(
            ["A19S"], ["A", "C"], current_timestamp=10000
        )

        self.assertEqual(len(arrivals), 1)
        self.assertEqual(arrivals[0]["route"], "A")

    @patch("api_clients.requests.Session.get")
    def test_fetch_upcoming_trains_http_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        arrivals = self.client.fetch_upcoming_trains(["A19S"], ["A"])

        # Should gracefully continue and return empty
        self.assertEqual(len(arrivals), 0)

    @patch("api_clients.requests.Session.get")
    def test_fetch_upcoming_trains_network_exception(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException(
            "DNS Resolution failed"
        )

        arrivals = self.client.fetch_upcoming_trains(["A19S"], ["A"])

        # Should gracefully catch error and return empty
        self.assertEqual(len(arrivals), 0)


if __name__ == "__main__":
    unittest.main()
