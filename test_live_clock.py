import unittest
from datetime import datetime, time as dt_time
import time
from unittest.mock import MagicMock, patch
import sys

# Mock hardware and transit libraries before importing live_clock
mock_matrix_lib = MagicMock()
mock_transit = MagicMock()
sys.modules["rgbmatrix"] = mock_matrix_lib
sys.modules["google.transit"] = mock_transit
sys.modules["google.transit.gtfs_realtime_pb2"] = MagicMock()
sys.modules["qrcode"] = MagicMock()

import live_clock  # noqa: E402


class TestLiveClock(unittest.TestCase):
    def setUp(self):
        self.clock = live_clock.SubwayClock()

    def test_is_night_mode(self):
        # Case 1: Start < End (e.g., 20:00 to 22:00)
        start = "20:00"
        end = "22:00"

        # Inside window
        with patch("live_clock.datetime") as mock_datetime:
            mock_datetime.now.return_value.time.return_value = dt_time(21, 0)
            mock_datetime.strptime = datetime.strptime
            self.assertTrue(self.clock.is_night_mode(start, end))

        # Outside window
        with patch("live_clock.datetime") as mock_datetime:
            mock_datetime.now.return_value.time.return_value = dt_time(19, 0)
            mock_datetime.strptime = datetime.strptime
            self.assertFalse(self.clock.is_night_mode(start, end))

        # Case 2: Start > End (Over midnight, e.g., 20:00 to 08:00)
        start = "20:00"
        end = "08:00"

        # Before midnight
        with patch("live_clock.datetime") as mock_datetime:
            mock_datetime.now.return_value.time.return_value = dt_time(23, 0)
            mock_datetime.strptime = datetime.strptime
            self.assertTrue(self.clock.is_night_mode(start, end))

        # After midnight
        with patch("live_clock.datetime") as mock_datetime:
            mock_datetime.now.return_value.time.return_value = dt_time(1, 0)
            mock_datetime.strptime = datetime.strptime
            self.assertTrue(self.clock.is_night_mode(start, end))

        # During day
        with patch("live_clock.datetime") as mock_datetime:
            mock_datetime.now.return_value.time.return_value = dt_time(12, 0)
            mock_datetime.strptime = datetime.strptime
            self.assertFalse(self.clock.is_night_mode(start, end))

    def test_route_name(self):
        self.assertEqual(self.clock.route_name("GS"), "S")
        self.assertEqual(self.clock.route_name("FS"), "S")
        self.assertEqual(self.clock.route_name("A"), "A")
        self.assertEqual(self.clock.route_name("SIR"), "S")

    def test_map_weather_code(self):
        self.assertEqual(self.clock.map_weather_code(0), live_clock.WeatherCodes.CLEAR)
        self.assertEqual(self.clock.map_weather_code(1), live_clock.WeatherCodes.CLOUDY)
        self.assertEqual(self.clock.map_weather_code(45), live_clock.WeatherCodes.FOG)
        self.assertEqual(self.clock.map_weather_code(51), live_clock.WeatherCodes.RAIN)
        self.assertEqual(self.clock.map_weather_code(71), live_clock.WeatherCodes.SNOW)
        self.assertEqual(self.clock.map_weather_code(95), live_clock.WeatherCodes.STORM)
        self.assertEqual(
            self.clock.map_weather_code(999), live_clock.WeatherCodes.UNKNOWN
        )

    @patch("live_clock.requests.get")
    def test_get_lat_lon_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "places": [{"latitude": "40.71", "longitude": "-74.00"}]
        }
        mock_get.return_value = mock_response

        lat, lon = self.clock.get_lat_lon(10001)
        self.assertEqual(lat, 40.71)
        self.assertEqual(lon, -74.00)
        # Check cache
        self.assertEqual(self.clock.weather_zip, 10001)

        # Second call should use cache (mock_get.call_count should still be 1)
        lat, lon = self.clock.get_lat_lon(10001)
        self.assertEqual(mock_get.call_count, 1)

    @patch("live_clock.requests.get")
    def test_get_lat_lon_failure(self, mock_get):
        mock_get.side_effect = Exception("API Down")
        lat, lon = self.clock.get_lat_lon(10001)
        # Fallback values
        self.assertEqual(lat, 41.50)
        self.assertEqual(lon, -73.97)

    def test_update_brightness(self):
        self.clock.matrix = MagicMock()
        self.clock.matrix.brightness = 100
        self.clock.current_brightness = 100
        self.clock.sunset_time = "20:00"
        self.clock.sunrise_time = "08:00"

        self.clock.config.get = MagicMock(
            side_effect=lambda k: {
                "day_brightness": 100,
                "night_brightness": 10,
            }.get(k)
        )

        # Test night mode (21:00)
        with patch("live_clock.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 21, 0)
            mock_datetime.strptime = datetime.strptime
            mock_datetime.combine = datetime.combine
            self.clock.update_brightness()
            self.assertEqual(self.clock.current_brightness, 10)
            self.assertEqual(self.clock.matrix.brightness, 10)

        # Test day mode (12:00)
        self.clock.matrix.brightness = 100
        self.clock.current_brightness = 100
        with patch("live_clock.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 12, 0)
            mock_datetime.strptime = datetime.strptime
            mock_datetime.combine = datetime.combine
            self.clock.update_brightness()
            self.assertEqual(self.clock.current_brightness, 100)
            self.assertEqual(self.clock.matrix.brightness, 100)

        # Test transitioning to night mode (19:50 - 10 mins before start)
        self.clock.matrix.brightness = 100
        self.clock.current_brightness = 100
        with patch("live_clock.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 19, 50)
            mock_datetime.strptime = datetime.strptime
            mock_datetime.combine = datetime.combine
            self.clock.update_brightness()
            self.assertEqual(self.clock.current_brightness, 85)
            self.assertEqual(self.clock.matrix.brightness, 85)

        # Test transitioning to day mode (07:51 - 9 mins before end)
        self.clock.matrix.brightness = 10
        self.clock.current_brightness = 10
        with patch("live_clock.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 7, 51)
            mock_datetime.strptime = datetime.strptime
            mock_datetime.combine = datetime.combine
            self.clock.update_brightness()
            self.assertEqual(self.clock.current_brightness, 28)
            self.assertEqual(self.clock.matrix.brightness, 28)

    def test_update_brightness_short_night(self):
        self.clock.matrix = MagicMock()
        self.clock.matrix.brightness = 100
        self.clock.current_brightness = 100
        self.clock.sunset_time = "20:00"
        self.clock.sunrise_time = "20:15"

        self.clock.config.get = MagicMock(
            side_effect=lambda k: {
                "day_brightness": 100,
                "night_brightness": 10,
            }.get(k)
        )

        # Test at 19:50 (10 mins before start). mins_to_start = 10, mins_to_end = 25.
        # Should transition to night mode. fraction = (10+15)/30 = 0.833. target = 85.
        with patch("live_clock.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 19, 50)
            mock_datetime.strptime = datetime.strptime
            mock_datetime.combine = datetime.combine
            self.clock.update_brightness()
            self.assertEqual(self.clock.current_brightness, 85)
            self.assertEqual(self.clock.matrix.brightness, 85)

        # Test at 20:00 (Exactly at start, 15 mins before end). mins_to_start = 0, mins_to_end = 15.
        # Should transition to day mode. fraction = (0+15)/30 = 0.5. target = 55.
        self.clock.matrix.brightness = 10
        self.clock.current_brightness = 10
        with patch("live_clock.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 1, 20, 0)
            mock_datetime.strptime = datetime.strptime
            mock_datetime.combine = datetime.combine
            self.clock.update_brightness()
            self.assertEqual(self.clock.current_brightness, 55)
            self.assertEqual(self.clock.matrix.brightness, 55)

    @patch("live_clock.requests.get")
    def test_fetch_weather_task_success(self, mock_get):
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "current_weather": {"temperature": 72, "weathercode": 51},
            "daily": {"sunrise": ["2026-04-21T06:07"], "sunset": ["2026-04-21T19:41"]}
        }
        mock_get.return_value = mock_response

        self.clock.config.get = MagicMock(return_value=10001)

        # Mock get_lat_lon to avoid another network call
        with patch.object(
            live_clock.SubwayClock, "get_lat_lon", return_value=(40.71, -74.00)
        ):
            self.clock.fetch_weather_task()
            self.assertEqual(self.clock.weather_text, "72°")
            self.assertEqual(
                self.clock.weather_condition_text, live_clock.WeatherCodes.RAIN
            )

    @patch("live_clock.requests.get")
    def test_fetch_trains_task_mock(self, mock_get):
        # Mock a minimal GTFS response for the first call, empty for others
        mock_response = MagicMock()
        mock_response.status_code = 200

        # We only want one response to succeed with data
        mock_empty = MagicMock()
        mock_empty.status_code = 404  # Skip others

        mock_get.side_effect = [mock_response] + [mock_empty] * 7

        self.clock.config.get = MagicMock(
            side_effect=lambda k: {"stop_ids": ["A19S"], "routes": ["A"]}.get(k)
        )

        with patch("live_clock.gtfs_realtime_pb2.FeedMessage") as mock_feed_class:
            mock_feed = mock_feed_class.return_value
            # Create a mock entity
            entity = MagicMock()
            entity.HasField.side_effect = lambda x: x == "trip_update"
            entity.trip_update.trip.route_id = "A"

            stop_time = MagicMock()
            stop_time.stop_id = "A19S"
            stop_time.HasField.side_effect = lambda x: x == "arrival"
            stop_time.arrival.HasField.side_effect = lambda x: x == "time"
            stop_time.arrival.time = int(time.time()) + 300  # 5 mins from now

            entity.trip_update.stop_time_update = [stop_time]
            mock_feed.entity = [entity]

            self.clock.fetch_trains_task()
            self.assertEqual(len(self.clock.trains), 1)
            self.assertEqual(self.clock.trains[0]["route"], "A")

    @patch("builtins.open")
    @patch("live_clock.fcntl.flock")
    def test_acquire_lock_success(self, mock_flock, mock_open):
        mock_file = MagicMock()
        mock_open.return_value = mock_file

        result = live_clock.acquire_lock()

        self.assertEqual(result, mock_file)
        mock_open.assert_called_once_with(live_clock.LOCK_FILE, "w")
        mock_flock.assert_called_once_with(
            mock_file, live_clock.fcntl.LOCK_EX | live_clock.fcntl.LOCK_NB
        )

    @patch("builtins.open")
    @patch("live_clock.fcntl.flock")
    @patch("live_clock.sys.exit")
    @patch("live_clock.logging.critical")
    def test_acquire_lock_blocking_io_error(
        self, mock_logging, mock_exit, mock_flock, mock_open
    ):
        mock_file = MagicMock()
        mock_open.return_value = mock_file
        mock_flock.side_effect = BlockingIOError()

        live_clock.acquire_lock()

        mock_logging.assert_called_once_with("Already running. Exiting.")
        mock_exit.assert_called_once_with(1)

    @patch("builtins.open")
    @patch("live_clock.fcntl.flock")
    @patch("live_clock.sys.exit")
    @patch("live_clock.logging.critical")
    def test_acquire_lock_permission_error(
        self, mock_logging, mock_exit, mock_flock, mock_open
    ):
        mock_open.side_effect = PermissionError()

        live_clock.acquire_lock()

        mock_logging.assert_called_once_with(
            f"Permission denied to access {live_clock.LOCK_FILE}."
        )
        mock_exit.assert_called_once_with(1)

    @patch("live_clock.time.time")
    def test_update_arrival_times(self, mock_time):
        mock_time.return_value = 10000

        self.clock.trains = [
            {"route": "C", "time": 10000 + 300},  # 5 mins
            {"route": "A", "time": 10000 + 120},  # 2 mins
            {"route": "E", "time": 10000 - 60},  # past (should be 0)
            {"route": "F", "time": 10000},  # exact now (0 mins)
            {"route": "R", "time": 10000 + 600},  # 5th train, ignored
        ]

        self.clock.update_arrival_times()

        self.assertEqual(len(self.clock.train_arrivals), 4)
        self.assertEqual(self.clock.train_arrivals[0], ("C", 5))
        self.assertEqual(self.clock.train_arrivals[1], ("A", 2))
        self.assertEqual(self.clock.train_arrivals[2], ("E", 0))
        self.assertEqual(self.clock.train_arrivals[3], ("F", 0))

    @patch("live_clock.requests.get")
    def test_fetch_weather_task_no_data(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_get.return_value = mock_response

        self.clock.config.get = MagicMock(return_value=10001)

        with patch.object(live_clock.SubwayClock, "get_lat_lon", return_value=(40.71, -74.00)):
            self.clock.fetch_weather_task()
            # wait for future
            if self.clock._weather_future:
                self.clock._weather_future.result()
            self.assertEqual(self.clock.weather_text, "")

    @patch("live_clock.requests.get")
    def test_fetch_sun_times_impl_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "daily": {"sunrise": ["2026-04-21T06:07"], "sunset": ["2026-04-21T19:41"]}
        }
        mock_get.return_value = mock_response

        self.clock.config.get = MagicMock(return_value=10001)

        with patch.object(live_clock.SubwayClock, "get_lat_lon", return_value=(40.71, -74.00)):
            self.clock._fetch_sun_times_impl()
            self.assertEqual(self.clock.sunrise_time, "06:07")
            self.assertEqual(self.clock.sunset_time, "19:41")

    def test_clear(self):
        self.clock.matrix = MagicMock()
        self.clock.clear()
        self.clock.matrix.Clear.assert_called_once()
        
    def test_draw_time(self):
        self.clock.canvas = MagicMock()
        self.clock.time_font = MagicMock()
        self.clock.draw_time()
        self.clock.canvas.SetPixel = MagicMock()

    def test_is_night_mode_invalid(self):
        self.assertFalse(self.clock.is_night_mode("invalid", "invalid"))
        
    def test_update_brightness_invalid(self):
        self.clock.sunset_time = "invalid"
        self.clock.sunrise_time = "invalid"
        self.clock.update_brightness() # Should return early

    @patch("live_clock.subprocess.run")
    def test_captive_portal_running(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = "active\n"
        mock_run.return_value = mock_result
        self.assertTrue(self.clock.captive_portal_running())
        
        mock_result.stdout = "inactive\n"
        self.assertFalse(self.clock.captive_portal_running())

    def test_display_wifi_qr(self):
        canvas_mock = MagicMock()
        self.clock.canvas = canvas_mock
        self.clock.small_font = MagicMock()
        self.clock.matrix = MagicMock()
        self.clock.config.get = MagicMock(return_value="TestSSID")
        self.clock.display_wifi_qr()
        canvas_mock.Clear.assert_called_once()
        
    def test_draw_weather_missing_condition(self):
        self.clock.canvas = MagicMock()
        self.clock.small_font = MagicMock()
        self.clock.weather_text = "50"
        self.clock.weather_condition_text = ""
        self.clock.draw_weather()
        
    def test_render(self):
        canvas_mock = MagicMock()
        self.clock.canvas = canvas_mock
        self.clock.matrix = MagicMock()
        self.clock.update_brightness = MagicMock()
        self.clock.draw_upcoming_trains = MagicMock()
        self.clock.draw_weather = MagicMock()
        self.clock.draw_time = MagicMock()
        self.clock.render()
        self.clock.update_brightness.assert_called_once()
        canvas_mock.Clear.assert_called_once()

    def test_check_config_task(self):
        self.clock.config.is_modified = MagicMock(return_value=True)
        self.clock.config.load = MagicMock()
        self.clock.config.get = MagicMock(side_effect=["old", "new"])
        self.clock.fetch_trains_task = MagicMock()
        self.clock.fetch_weather_task = MagicMock()
        self.clock.fetch_sun_times_task = MagicMock()
        self.clock.check_config_task()
        self.clock.fetch_sun_times_task.assert_called_once()

        self.clock.config.is_modified = MagicMock(return_value=False)
        self.clock.check_config_task() # No exception

if __name__ == "__main__":
    unittest.main()
