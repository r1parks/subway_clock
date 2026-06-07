#!/usr/bin/env python3

import fcntl
import logging
import os
import sys
import time
import signal
import subprocess
import threading
import qrcode
import schedule
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from api_clients import WeatherClient, TransitClient

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics
except ImportError:
    logging.warning("rgbmatrix module not found. Using a mock implementation.")
    from matrix_mock import RGBMatrix, RGBMatrixOptions, graphics

from config_manager import Config  # noqa: E402

# --- Configuration ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK_FILE = os.path.join(SCRIPT_DIR, ".live_clock.lock")
FONTS_DIR = os.path.join(SCRIPT_DIR, "fonts")


class NoWeatherException(Exception): ...


class WeatherCodes:
    CLEAR = ""
    CLOUDY = ""
    FOG = "Fog"
    RAIN = "Rain"
    SNOW = "Snow"
    STORM = "Storm"
    UNKNOWN = ""


class SubwayClock:
    # --- Display Constants ---
    MATRIX_WIDTH = 64
    CHAR_WIDTH = 4
    TRANSITION_DURATION = 30.0

    # --- Base Colors (Tuned for LED Matrices) ---
    COLORS = {
        "BLUE": graphics.Color(0, 50, 255),
        "ORANGE": graphics.Color(255, 100, 0),
        "LIGHT_GREEN": graphics.Color(100, 255, 50),
        "BROWN": graphics.Color(150, 100, 50),
        "LIGHT_GRAY": graphics.Color(100, 100, 100),
        "YELLOW": graphics.Color(125, 80, 0),
        "RED": graphics.Color(255, 0, 0),
        "DARK_GREEN": graphics.Color(0, 200, 50),
        "PURPLE": graphics.Color(200, 0, 200),
        "DARK_GRAY": graphics.Color(75, 75, 75),
        "DEFAULT": graphics.Color(50, 50, 50),
    }

    # --- MTA Route Map ---
    ROUTE_COLORS = {
        "A": COLORS["BLUE"],
        "C": COLORS["BLUE"],
        "E": COLORS["BLUE"],
        "B": COLORS["ORANGE"],
        "D": COLORS["ORANGE"],
        "F": COLORS["ORANGE"],
        "M": COLORS["ORANGE"],
        "G": COLORS["LIGHT_GREEN"],
        "J": COLORS["BROWN"],
        "Z": COLORS["BROWN"],
        "L": COLORS["LIGHT_GRAY"],
        "N": COLORS["YELLOW"],
        "Q": COLORS["YELLOW"],
        "R": COLORS["YELLOW"],
        "W": COLORS["YELLOW"],
        "1": COLORS["RED"],
        "2": COLORS["RED"],
        "3": COLORS["RED"],
        "4": COLORS["DARK_GREEN"],
        "5": COLORS["DARK_GREEN"],
        "6": COLORS["DARK_GREEN"],
        "7": COLORS["PURPLE"],
        "S": COLORS["DARK_GRAY"],
    }

    def __init__(self, matrix=None, weather_client=None, transit_client=None):
        self.config = Config()
        self.matrix = matrix
        self.weather_client = weather_client or WeatherClient()
        self.transit_client = transit_client or TransitClient()
        self.canvas = None
        self.font = None
        self.train_font = None
        self.time_font = None
        self.small_font = None
        self.current_brightness = None
        self.lat = None
        self.lon = None
        self.weather_zip = None

        # State data
        self.next_sunset = None
        self.next_sunrise = None
        self.dim_finish_time = None
        self.undim_finish_time = None
        self.trains = []
        self._trains_lock = threading.Lock()
        self.train_arrivals = []
        self.weather_text = ""
        self.weather_condition_text = ""
        self.display_tz = ZoneInfo("America/New_York")  # Default until zip resolves
        self.executor = ThreadPoolExecutor(max_workers=2)
        self._weather_future = None
        self._train_future = None
        self._sun_future = None

    def setup_matrix(self):
        # --- Matrix Setup ---
        if self.matrix is None:
            options = RGBMatrixOptions()
            options.rows = 32
            options.cols = 64
            options.hardware_mapping = "adafruit-hat"
            options.drop_privileges = False  # Required for Bookworm permissions
            self.matrix = RGBMatrix(options=options)

        self.canvas = self.matrix.CreateFrameCanvas()

        # Load fonts
        self.font = self.load_font("5x8.bdf")
        self.train_font = self.font
        self.time_font = self.load_font("4x6.bdf")
        self.small_font = self.time_font

        graphics.DrawText(
            self.canvas, self.font, 4, 16, graphics.Color(200, 200, 0), "starting..."
        )
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def load_font(self, font_name):
        font_path = os.path.join(FONTS_DIR, font_name)
        if not os.path.exists(font_path):
            logging.critical(f"Error: Font not found at {font_path}")
            sys.exit(1)
        font = graphics.Font()
        font.LoadFont(font_path)
        return font

    def clear(self):
        if self.matrix:
            self.matrix.Clear()

    def update_brightness(self, current_time=None):
        if self.matrix is None:
            return
        if not all(
            [
                self.next_sunset,
                self.next_sunrise,
                self.dim_finish_time,
                self.undim_finish_time,
            ]
        ):
            return

        day_b = self.config.get("day_brightness")
        night_b = self.config.get("night_brightness")

        now = current_time or datetime.now(self.display_tz)

        # Rollover check
        if now > self.dim_finish_time:
            self.next_sunset += timedelta(days=1)
            self.dim_finish_time += timedelta(days=1)
        if now > self.undim_finish_time:
            self.next_sunrise += timedelta(days=1)
            self.undim_finish_time += timedelta(days=1)

        dim_start = self.dim_finish_time - timedelta(minutes=self.TRANSITION_DURATION)
        undim_start = self.undim_finish_time - timedelta(
            minutes=self.TRANSITION_DURATION
        )

        if dim_start <= now <= self.dim_finish_time:
            mins_elapsed = (now - dim_start).total_seconds() / 60.0
            fraction = mins_elapsed / self.TRANSITION_DURATION
            target_brightness = int(day_b + (night_b - day_b) * fraction)
        elif undim_start <= now <= self.undim_finish_time:
            mins_elapsed = (now - undim_start).total_seconds() / 60.0
            fraction = mins_elapsed / self.TRANSITION_DURATION
            target_brightness = int(night_b + (day_b - night_b) * fraction)
        else:
            if self.undim_finish_time < self.dim_finish_time:
                target_brightness = night_b
            else:
                target_brightness = day_b

        if self.current_brightness != target_brightness:
            self.matrix.brightness = target_brightness
            self.current_brightness = target_brightness

    def _fetch_weather_impl(self):
        zip_code = self.config.get("weather_zip")
        data = self.weather_client.get_current_weather(zip_code)
        if data:
            cond = self.map_weather_code(data["weathercode"])
            self.weather_text = f"{data['temperature']}°"
            self.weather_condition_text = cond
        else:
            logging.error("Weather fetch returned no data.")

    def fetch_weather_task(self):
        if self._weather_future is None or self._weather_future.done():
            self._weather_future = self.executor.submit(self._fetch_weather_impl)

    def _fetch_sun_times_impl(self, current_time=None):
        zip_code = self.config.get("weather_zip")
        daily = self.weather_client.get_sun_forecast(zip_code)
        if daily:
            # Update timezone first so sunrise/sunset are interpreted in local time
            tz_name = daily.get("timezone")
            if tz_name:
                try:
                    self.display_tz = ZoneInfo(tz_name)
                    logging.info(f"Timezone updated to {tz_name} for zip {zip_code}")
                except ZoneInfoNotFoundError:
                    logging.error(f"Unknown timezone name returned: {tz_name}")

            now = current_time or datetime.now(self.display_tz)

            for sr_iso in daily["sunrise"]:
                sr = datetime.fromisoformat(sr_iso).replace(tzinfo=self.display_tz)
                finish_time = sr + timedelta(minutes=self.TRANSITION_DURATION / 2)
                if finish_time > now:
                    self.next_sunrise = sr
                    self.undim_finish_time = finish_time
                    break

            for ss_iso in daily["sunset"]:
                ss = datetime.fromisoformat(ss_iso).replace(tzinfo=self.display_tz)
                finish_time = ss + timedelta(minutes=self.TRANSITION_DURATION / 2)
                if finish_time > now:
                    self.next_sunset = ss
                    self.dim_finish_time = finish_time
                    break
        else:
            logging.error("Failed to populate sun times from API.")

    def fetch_sun_times_task(self):
        if self._sun_future is None or self._sun_future.done():
            self._sun_future = self.executor.submit(self._fetch_sun_times_impl)

    def map_weather_code(self, code):
        if code == 0:
            return WeatherCodes.CLEAR
        elif code in [1, 2, 3]:
            return WeatherCodes.CLOUDY
        elif code in [45, 48]:
            return WeatherCodes.FOG
        elif code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]:
            return WeatherCodes.RAIN
        elif code in [71, 73, 75, 77, 85, 86]:
            return WeatherCodes.SNOW
        elif code in [95, 96, 99]:
            return WeatherCodes.STORM
        return WeatherCodes.UNKNOWN

    def _fetch_trains_impl(self):
        stop_ids = self.config.get("stop_ids")
        active_routes = self.config.get("routes")
        new_trains = self.transit_client.fetch_upcoming_trains(stop_ids, active_routes)
        with self._trains_lock:
            self.trains = new_trains

    def fetch_trains_task(self):
        if self._train_future is None or self._train_future.done():
            self._train_future = self.executor.submit(self._fetch_trains_impl)

    def check_config_task(self):
        if self.config.is_modified():
            old_zip = self.config.get("weather_zip")
            logging.info("Config file changed, reloading...")
            self.config.load()
            # If config changed, trigger immediate data refresh
            self.fetch_trains_task()
            self.fetch_weather_task()
            if old_zip != self.config.get("weather_zip"):
                self.fetch_sun_times_task()

    def draw_route_bullet(self, x, y, route_id):
        route = self.route_name(route_id)
        bg_color = self.ROUTE_COLORS.get(route, self.COLORS["DEFAULT"])
        center_x = x + 3
        center_y = y - 3
        row_widths = [1, 2, 3, 3, 3, 3, 2, 1]

        for i, width in enumerate(row_widths):
            y_offset = i - 4
            graphics.DrawLine(
                self.canvas,
                center_x - width,
                center_y + y_offset,
                center_x + width + 1,
                center_y + y_offset,
                bg_color,
            )

        white = graphics.Color(255, 255, 255)
        graphics.DrawText(self.canvas, self.train_font, x + 2, y, white, route)

    def route_name(self, route_id):
        return {"GS": "S", "FS": "S", "H": "S", "SI": "S", "SIR": "S"}.get(
            route_id, route_id
        )

    def draw_right_aligned_text(self, y_pos, font, color, text):
        x_pos = self.MATRIX_WIDTH - (len(text) * self.CHAR_WIDTH) + 1
        graphics.DrawText(self.canvas, font, x_pos, y_pos, color, text)

    def draw_time(self):
        now = datetime.now(self.display_tz)
        time_text = now.strftime("%-I:%M").rjust(5)
        time_color = graphics.Color(255, 215, 0)
        self.draw_right_aligned_text(5, self.time_font, time_color, time_text)

    def update_arrival_times(self, current_timestamp=None):
        now = current_timestamp if current_timestamp is not None else int(time.time())
        new_arrivals = []
        with self._trains_lock:
            for train in self.trains:
                minutes = int((train["time"] - now) / 60)
                if minutes < 0:
                    continue
                new_arrivals.append((train["route"], minutes))
            if self.trains and not new_arrivals:
                logging.info(
                    "Train list was not empty initially, but became empty after filtering."
                )
        self.train_arrivals = new_arrivals

    def draw_upcoming_trains(self):
        y_pos = 7
        for route, minutes in self.train_arrivals[:4]:
            self.draw_route_bullet(0, y_pos, route)
            if minutes == 0:
                text = "Now"
            elif minutes >= 60:
                h = minutes // 60
                m = minutes % 60
                text = f"{h}h {m}m"
            else:
                text = f"{minutes} min"
            color = graphics.Color(200, 200, 200)
            graphics.DrawText(self.canvas, self.font, 11, y_pos, color, text)
            y_pos += 8

    def draw_weather(self):
        weather_color = graphics.Color(255, 215, 0)
        self.draw_right_aligned_text(
            11, self.small_font, weather_color, self.weather_text
        )
        if self.weather_condition_text:
            self.draw_right_aligned_text(
                17, self.small_font, weather_color, self.weather_condition_text
            )

    def captive_portal_running(self):
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "wifi-connect.service"],
                stdout=subprocess.PIPE,
                text=True,
            )
            return result.stdout.strip() == "active"
        except Exception:
            return False

    def display_wifi_qr(self):
        ssid = self.config.get("portal_ssid", "SubwayClock")
        wifi_string = f"WIFI:S:{ssid};T:nopass;;"
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=1,
        )
        qr.add_data(wifi_string)
        qr.make(fit=True)
        qr_matrix = qr.get_matrix()
        qr_size = len(qr_matrix)

        self.canvas.Clear()
        color = graphics.Color(200, 200, 0)
        graphics.DrawText(self.canvas, self.small_font, 0, 10, color, "scan to")
        graphics.DrawText(self.canvas, self.small_font, 0, 18, color, "connect")

        x_offset = 64 - qr_size
        y_offset = (32 - qr_size) // 2
        for y, row in enumerate(qr_matrix):
            for x, cell in enumerate(row):
                if cell:
                    self.canvas.SetPixel(x + x_offset, y + y_offset, 255, 255, 255)
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def render(self):
        self.update_brightness()
        self.canvas.Clear()
        self.draw_upcoming_trains()
        self.draw_weather()
        self.draw_time()
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def tick(self):
        schedule.run_pending()
        self.render()

    def run(self):
        logging.info("Starting Subway Clock (Scheduled Mode)...")

        # High-priority check for captive portal on startup
        if self.captive_portal_running():
            # The captive portal always starts on boot up, and then stops if an
            # internet connection is detected. Give it a few seconds to shut
            # down so we don't display the QR code prematurely.
            time.sleep(3)
        while self.captive_portal_running():
            self.display_wifi_qr()
            time.sleep(5)

        # Initial data fetch
        self.fetch_trains_task()
        self.fetch_weather_task()
        self.fetch_sun_times_task()

        # Wait for the initial data fetches to finish so we don't clear the
        # "starting..." screen prematurely.
        if self._train_future:
            try:
                self._train_future.result(timeout=15)
            except Exception as e:
                logging.error(f"Initial train fetch failed: {e}")

        if self._weather_future:
            try:
                self._weather_future.result(timeout=15)
            except Exception as e:
                logging.error(f"Initial weather fetch failed: {e}")

        if self._sun_future:
            try:
                self._sun_future.result(timeout=15)
            except Exception as e:
                logging.error(f"Initial sun times fetch failed: {e}")

        self.update_arrival_times()

        # Set up schedules
        schedule.every(30).seconds.do(self.fetch_trains_task)
        schedule.every(15).seconds.do(self.update_arrival_times)
        schedule.every(5).minutes.do(self.fetch_weather_task)
        schedule.every(5).seconds.do(self.check_config_task)
        schedule.every(6).hours.do(self.fetch_sun_times_task)

        while True:
            self.tick()
            time.sleep(1)


def acquire_lock():
    try:
        lock_file = open(LOCK_FILE, "w")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file
    except BlockingIOError:
        logging.critical("Already running. Exiting.")
        sys.exit(1)
    except PermissionError:
        logging.critical(f"Permission denied to access {LOCK_FILE}.")
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _LOCK = acquire_lock()
    clock = SubwayClock()

    def handle_exit(signum, frame):
        logging.info("Stopping...")
        clock.executor.shutdown(wait=False)
        clock.clear()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)

    clock.setup_matrix()
    clock.run()
