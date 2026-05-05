import unittest
from datetime import datetime, time as dt_time, timedelta
import time
from unittest.mock import MagicMock, patch
import sys
import logging

# Disable logging during tests to keep console clean
logging.disable(logging.CRITICAL)

# Mock non-standard packages
sys.modules["google"] = MagicMock()
sys.modules["google.transit"] = MagicMock()
sys.modules["google.transit.gtfs_realtime_pb2"] = MagicMock()
sys.modules["qrcode"] = MagicMock()

import live_clock


class TestLiveClock(unittest.TestCase):
    def setUp(self):
        self.mock_matrix = MagicMock()
        self.mock_matrix.brightness = 100
        
        self.mock_weather = MagicMock()
        self.mock_transit = MagicMock()
        
        self.clock = live_clock.SubwayClock(
            matrix=self.mock_matrix,
            weather_client=self.mock_weather,
            transit_client=self.mock_transit
        )

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

    def test_update_brightness(self):
        self.clock.current_brightness = 100
        
        # Sunset 20:00, dim_finish = 20:15
        self.clock.next_sunset = datetime(2024, 1, 1, 20, 0)
        self.clock.dim_finish_time = datetime(2024, 1, 1, 20, 15)
        # Sunrise 08:00, undim_finish = 08:15 (Next day)
        self.clock.next_sunrise = datetime(2024, 1, 2, 8, 0)
        self.clock.undim_finish_time = datetime(2024, 1, 2, 8, 15)

        self.clock.config.get = MagicMock(
            side_effect=lambda k: {
                "day_brightness": 100,
                "night_brightness": 10,
            }.get(k)
        )

        # Test night mode (21:00)
        self.clock.update_brightness(current_time=datetime(2024, 1, 1, 21, 0))
        self.assertEqual(self.clock.current_brightness, 10)
        self.assertEqual(self.clock.matrix.brightness, 10)

        # Test day mode (12:00)
        self.clock.next_sunset = datetime(2024, 1, 1, 20, 0)
        self.clock.dim_finish_time = datetime(2024, 1, 1, 20, 15)
        self.clock.next_sunrise = datetime(2024, 1, 2, 8, 0)
        self.clock.undim_finish_time = datetime(2024, 1, 2, 8, 15)
        self.clock.matrix.brightness = 100
        self.clock.current_brightness = 100
        self.clock.update_brightness(current_time=datetime(2024, 1, 1, 12, 0))
        self.assertEqual(self.clock.current_brightness, 100)
        self.assertEqual(self.clock.matrix.brightness, 100)

        # Test transitioning to night mode (19:50) - 5 mins into 30 min transition
        self.clock.next_sunset = datetime(2024, 1, 1, 20, 0)
        self.clock.dim_finish_time = datetime(2024, 1, 1, 20, 15)
        self.clock.next_sunrise = datetime(2024, 1, 2, 8, 0)
        self.clock.undim_finish_time = datetime(2024, 1, 2, 8, 15)
        self.clock.matrix.brightness = 100
        self.clock.current_brightness = 100
        self.clock.update_brightness(current_time=datetime(2024, 1, 1, 19, 50))
        self.assertEqual(self.clock.current_brightness, 85)
        self.assertEqual(self.clock.matrix.brightness, 85)

        # Test transitioning to day mode (07:51) - 6 mins into 30 min transition
        self.clock.next_sunset = datetime(2024, 1, 1, 20, 0)
        self.clock.dim_finish_time = datetime(2024, 1, 1, 20, 15)
        self.clock.next_sunrise = datetime(2024, 1, 2, 8, 0)
        self.clock.undim_finish_time = datetime(2024, 1, 2, 8, 15)
        self.clock.matrix.brightness = 10
        self.clock.current_brightness = 10
        self.clock.update_brightness(current_time=datetime(2024, 1, 2, 7, 51))
        self.assertEqual(self.clock.current_brightness, 28)
        self.assertEqual(self.clock.matrix.brightness, 28)

    def test_update_brightness_rollover(self):
        self.clock.current_brightness = 100
        
        self.clock.next_sunset = datetime(2024, 1, 1, 20, 0)
        self.clock.dim_finish_time = datetime(2024, 1, 1, 20, 15)
        self.clock.next_sunrise = datetime(2024, 1, 2, 8, 0)
        self.clock.undim_finish_time = datetime(2024, 1, 2, 8, 15)

        self.clock.config.get = MagicMock(
            side_effect=lambda k: {
                "day_brightness": 100,
                "night_brightness": 10,
            }.get(k)
        )

        # Cross the dim finish threshold to trigger rollover
        self.clock.update_brightness(current_time=datetime(2024, 1, 1, 20, 16))
        
        # Should have rolled over sunset by 1 day
        self.assertEqual(self.clock.next_sunset, datetime(2024, 1, 2, 20, 0))
        self.assertEqual(self.clock.dim_finish_time, datetime(2024, 1, 2, 20, 15))
        
        # Sunrise hasn't crossed yet, stays the same
        self.assertEqual(self.clock.next_sunrise, datetime(2024, 1, 2, 8, 0))

    def test_fetch_weather_task_success(self):
        self.clock.config.get = MagicMock(return_value=10001)
        self.mock_weather.get_current_weather.return_value = {
            "temperature": 72,
            "weathercode": 51
        }

        self.clock.fetch_weather_task()
        if self.clock._weather_future:
            self.clock._weather_future.result()

        self.assertEqual(self.clock.weather_text, "72°")
        self.assertEqual(
            self.clock.weather_condition_text, live_clock.WeatherCodes.RAIN
        )
        self.mock_weather.get_current_weather.assert_called_once_with(10001)

    def test_fetch_weather_task_no_data(self):
        self.clock.config.get = MagicMock(return_value=10001)
        self.mock_weather.get_current_weather.return_value = None

        self.clock.fetch_weather_task()
        if self.clock._weather_future:
            self.clock._weather_future.result()

        self.assertEqual(self.clock.weather_text, "")

    def test_fetch_trains_task_mock(self):
        self.clock.config.get = MagicMock(
            side_effect=lambda k: {"stop_ids": ["A19S"], "routes": ["A"]}.get(k)
        )
        self.mock_transit.fetch_upcoming_trains.return_value = [
            {"route": "A", "time": int(time.time()) + 300}
        ]

        self.clock.fetch_trains_task()
        if self.clock._train_future:
            self.clock._train_future.result()

        self.assertEqual(len(self.clock.trains), 1)
        self.assertEqual(self.clock.trains[0]["route"], "A")
        self.mock_transit.fetch_upcoming_trains.assert_called_once_with(["A19S"], ["A"])

    def test_fetch_sun_times_impl_success(self):
        self.clock.config.get = MagicMock(return_value=10001)
        self.mock_weather.get_sun_forecast.return_value = {
            "sunrise": ["2026-04-21T06:07"],
            "sunset": ["2026-04-21T19:41"]
        }

        self.clock._fetch_sun_times_impl(current_time=datetime(2026, 4, 21, 0, 0))
        
        self.assertEqual(self.clock.next_sunrise, datetime(2026, 4, 21, 6, 7))
        self.assertEqual(self.clock.next_sunset, datetime(2026, 4, 21, 19, 41))
        self.mock_weather.get_sun_forecast.assert_called_once_with(10001)

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

    def test_update_arrival_times(self):
        self.clock.trains = [
            {"route": "C", "time": 10000 + 300},  # 5 mins
            {"route": "A", "time": 10000 + 120},  # 2 mins
            {"route": "E", "time": 10000 - 60},  # past (should be 0)
            {"route": "F", "time": 10000},  # exact now (0 mins)
            {"route": "R", "time": 10000 + 600},  # 5th train, ignored
        ]

        self.clock.update_arrival_times(current_timestamp=10000)

        self.assertEqual(len(self.clock.train_arrivals), 4)
        self.assertEqual(self.clock.train_arrivals[0], ("C", 5))
        self.assertEqual(self.clock.train_arrivals[1], ("A", 2))
        self.assertEqual(self.clock.train_arrivals[2], ("E", 0))
        self.assertEqual(self.clock.train_arrivals[3], ("F", 0))

    def test_clear(self):
        self.clock.clear()
        self.clock.matrix.Clear.assert_called_once()
        
    def test_draw_time(self):
        self.clock.canvas = MagicMock()
        self.clock.time_font = MagicMock()
        self.clock.draw_time()
        self.clock.canvas.SetPixel = MagicMock()

    def test_update_brightness_invalid(self):
        self.clock.next_sunset = None
        self.clock.next_sunrise = None
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


    def test_tick(self):
        with patch("live_clock.schedule.run_pending") as mock_run_pending:
            self.clock.render = MagicMock()
            self.clock.tick()
            mock_run_pending.assert_called_once()
            self.clock.render.assert_called_once()

    @patch("live_clock.RGBMatrixOptions")
    @patch("live_clock.RGBMatrix")
    @patch("live_clock.graphics")
    def test_setup_matrix_no_matrix(self, mock_graphics, mock_rgbmatrix, mock_options):
        # Set matrix to None to trigger initialization
        self.clock.matrix = None
        
        # We need a mock font returned from load_font
        self.clock.load_font = MagicMock()
        
        self.clock.setup_matrix()
        
        # Verify matrix was created
        mock_options.assert_called_once()
        mock_rgbmatrix.assert_called_once()
        
        # Verify canvas swap
        self.clock.matrix.SwapOnVSync.assert_called_once()

    @patch("live_clock.os.path.exists")
    @patch("live_clock.graphics")
    def test_load_font_success(self, mock_graphics, mock_exists):
        mock_exists.return_value = True
        mock_font_class = MagicMock()
        mock_graphics.Font.return_value = mock_font_class
        
        font = self.clock.load_font("test.bdf")
        self.assertEqual(font, mock_font_class)
        font.LoadFont.assert_called_once()

    @patch("live_clock.os.path.exists")
    @patch("live_clock.logging.critical")
    @patch("live_clock.sys.exit")
    def test_load_font_failure(self, mock_exit, mock_logging, mock_exists):
        mock_exists.return_value = False
        self.clock.load_font("test.bdf")
        mock_logging.assert_called_once()
        mock_exit.assert_called_once_with(1)

    @patch("live_clock.graphics")
    def test_draw_route_bullet(self, mock_graphics):
        self.clock.canvas = MagicMock()
        self.clock.train_font = MagicMock()
        
        # Test normal route
        self.clock.draw_route_bullet(0, 0, "A")
        
        # Test mapped route
        self.clock.draw_route_bullet(0, 0, "GS")

    @patch("live_clock.graphics")
    def test_draw_upcoming_trains(self, mock_graphics):
        self.clock.canvas = MagicMock()
        self.clock.font = MagicMock()
        self.clock.draw_route_bullet = MagicMock()
        
        self.clock.train_arrivals = [
            ("A", 0),
            ("C", 45),
            ("E", 65),
        ]
        
        self.clock.draw_upcoming_trains()
        
        # Check that it drew 3 bullets
        self.assertEqual(self.clock.draw_route_bullet.call_count, 3)

    @patch("live_clock.graphics")
    def test_draw_weather_full(self, mock_graphics):
        self.clock.canvas = MagicMock()
        self.clock.small_font = MagicMock()
        self.clock.weather_text = "50°"
        self.clock.weather_condition_text = "Cloudy"
        self.clock.draw_right_aligned_text = MagicMock()
        
        self.clock.draw_weather()
        self.assertEqual(self.clock.draw_right_aligned_text.call_count, 2)

    @patch("live_clock.subprocess.run")
    def test_captive_portal_running_exception(self, mock_run):
        mock_run.side_effect = Exception("Not found")
        self.assertFalse(self.clock.captive_portal_running())

    @patch("live_clock.qrcode")
    def test_display_wifi_qr_full(self, mock_qrcode):
        mock_qr = MagicMock()
        # Create a simple 2x2 matrix mock
        mock_qr.get_matrix.return_value = [[True, False], [False, True]]
        mock_qrcode.QRCode.return_value = mock_qr
        
        self.clock.canvas = MagicMock()
        original_canvas = self.clock.canvas
        self.clock.small_font = MagicMock()
        self.clock.config.get = MagicMock(return_value="MySSID")
        
        self.clock.display_wifi_qr()
        
        # Should set pixels for the "True" elements
        original_canvas.SetPixel.assert_called()
        self.clock.matrix.SwapOnVSync.assert_called_once()

    @patch("live_clock.time.sleep")
    @patch("live_clock.schedule")
    def test_run_loop(self, mock_schedule, mock_sleep):
        # We need to simulate the run loop cleanly exiting so it doesn't infinite loop.
        # We can do this by raising an exception from self.tick() after 1 iteration
        self.clock.captive_portal_running = MagicMock(side_effect=[True, True, False])
        self.clock.display_wifi_qr = MagicMock()
        
        self.clock.fetch_trains_task = MagicMock()
        self.clock.fetch_weather_task = MagicMock()
        self.clock.fetch_sun_times_task = MagicMock()
        self.clock.update_arrival_times = MagicMock()
        
        self.clock.tick = MagicMock(side_effect=StopIteration("Exit Loop"))
        
        with self.assertRaises(StopIteration):
            self.clock.run()
            
        self.clock.display_wifi_qr.assert_called_once()
        self.clock.fetch_trains_task.assert_called_once()
        self.clock.fetch_weather_task.assert_called_once()
        self.clock.fetch_sun_times_task.assert_called_once()
        self.clock.update_arrival_times.assert_called_once()
        
        # Test futures handling
        self.clock._train_future = MagicMock()
        self.clock._weather_future = MagicMock()
        self.clock._sun_future = MagicMock()
        
        self.clock._train_future.result.side_effect = Exception("Train fail")
        self.clock._weather_future.result.side_effect = Exception("Weather fail")
        self.clock._sun_future.result.side_effect = Exception("Sun fail")
        
        self.clock.captive_portal_running.side_effect = [False, False]
        self.clock.tick.side_effect = StopIteration("Exit Loop")
        
        with patch("live_clock.logging") as mock_logging:
            with self.assertRaises(StopIteration):
                self.clock.run()
            self.assertEqual(mock_logging.error.call_count, 3)

if __name__ == "__main__":
    unittest.main()
