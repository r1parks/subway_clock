#!/usr/bin/env python3

import fcntl
import logging
import os
import sys
import time
import requests
import signal
import subprocess
import qrcode
import schedule
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from google.transit import gtfs_realtime_pb2

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
    CLEAR = "Clear"
    CLOUDY = "Cloudy"
    FOG = "Fog"
    RAIN = "Rain"
    SNOW = "Snow"
    STORM = "Storm"
    UNKNOWN = ""


class SubwayClock:
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

    FEED_URLS = [
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/" "nyct%2Fgtfs-ace",
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/" "nyct%2Fgtfs-bdfm",
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/" "nyct%2Fgtfs-nqrw",
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/" "nyct%2Fgtfs-l",
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/" "nyct%2Fgtfs-g",
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/" "nyct%2Fgtfs-jz",
        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/" "nyct%2Fgtfs-si",
    ]

    def __init__(self):
        self.config = Config()
        self.matrix = None
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
        self.trains = []
        self.weather_text = ""
        self.weather_condition_text = ""
        self.executor = ThreadPoolExecutor(max_workers=2)
        self._weather_future = None
        self._train_future = None

    def setup_matrix(self):
        # --- Matrix Setup ---
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

    def update_brightness(self):
        day_b = self.config.get("day_brightness")
        night_b = self.config.get("night_brightness")
        night_start = self.config.get("night_start_time")
        night_end = self.config.get("night_end_time")

        if self.is_night_mode(night_start, night_end):
            target_brightness = night_b
        else:
            target_brightness = day_b

        if self.current_brightness != target_brightness:
            self.matrix.brightness = target_brightness
            self.current_brightness = target_brightness

    def is_night_mode(self, night_start, night_end):
        now = datetime.now().time()
        try:
            start_time = datetime.strptime(night_start, "%H:%M").time()
            end_time = datetime.strptime(night_end, "%H:%M").time()
        except (ValueError, TypeError):
            return False

        if start_time < end_time:
            return start_time <= now <= end_time
        else:
            return now >= start_time or now <= end_time

    def get_lat_lon(self, zip_code):
        if (
            self.weather_zip == zip_code
            and self.lat is not None
            and self.lon is not None
        ):
            return self.lat, self.lon

        self.weather_zip = zip_code
        url = f"http://api.zippopotam.us/us/{zip_code}"
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            self.lat = float(data["places"][0]["latitude"])
            self.lon = float(data["places"][0]["longitude"])
            return self.lat, self.lon
        except Exception as e:
            logging.error(f"Failed to translate Zip Code {zip_code}: {e}")
            return 41.50, -73.97

    def _fetch_weather_impl(self):
        zip_code = self.config.get("weather_zip")
        endpoint = "https://api.open-meteo.com/v1/forecast"
        try:
            lat, lon = self.get_lat_lon(zip_code)
            params = {
                "latitude": lat,
                "longitude": lon,
                "current_weather": "true",
                "temperature_unit": "fahrenheit",
            }
            response = requests.get(endpoint, params=params, timeout=5)
            response.raise_for_status()
            data = response.json().get("current_weather")
            if not data:
                raise NoWeatherException("No weather data")

            temp = int(data["temperature"])
            code = data["weathercode"]
            cond = self.map_weather_code(code)
            self.weather_text = f"{temp}°"
            self.weather_condition_text = cond
        except Exception as e:
            logging.error(f"Weather fetch error: {e}")
            # We don't clear weather_text on error to keep showing old data

    def fetch_weather_task(self):
        if self._weather_future is None or self._weather_future.done():
            self._weather_future = self.executor.submit(self._fetch_weather_impl)

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
        new_arrivals = []
        now = int(time.time())

        for url in self.FEED_URLS:
            try:
                response = requests.get(url, timeout=5)
                if response.status_code != 200:
                    continue
                feed = gtfs_realtime_pb2.FeedMessage()
                feed.ParseFromString(response.content)
                for entity in feed.entity:
                    if not entity.HasField("trip_update"):
                        continue
                    trip = entity.trip_update.trip
                    route_id = trip.route_id
                    if "*" not in active_routes and route_id not in active_routes:
                        continue
                    for stop_time in entity.trip_update.stop_time_update:
                        if stop_time.stop_id not in stop_ids:
                            continue
                        if not stop_time.HasField(
                            "arrival"
                        ) or not stop_time.arrival.HasField("time"):
                            continue
                        arrival_time = stop_time.arrival.time
                        if arrival_time - now > 60:
                            new_arrivals.append(
                                {"route": route_id, "time": arrival_time}
                            )
            except Exception as e:
                logging.error(f"Error fetching feed {url}: {e}")
        new_arrivals.sort(key=lambda x: x["time"])
        self.trains = new_arrivals

    def fetch_trains_task(self):
        if self._train_future is None or self._train_future.done():
            self._train_future = self.executor.submit(self._fetch_trains_impl)

    def check_config_task(self):
        if self.config.is_modified():
            logging.info("Config file changed, reloading...")
            self.config.load()
            # If config changed, trigger immediate data refresh
            self.fetch_trains_task()
            self.fetch_weather_task()

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

    def draw_time(self):
        time_text = time.strftime("%-I:%M").rjust(5)
        time_color = graphics.Color(255, 215, 0)
        x_pos = 64 - (len(time_text) * 4)
        y_pos = 5
        graphics.DrawText(
            self.canvas, self.time_font, x_pos, y_pos, time_color, time_text
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
        now = int(time.time())
        y_pos = 7
        for train in self.trains[:4]:
            self.draw_route_bullet(0, y_pos, train["route"])
            minutes = max(0, int((train["time"] - now) / 60))
            text = "Now" if minutes == 0 else f"{minutes} min"
            color = graphics.Color(200, 200, 200)
            graphics.DrawText(self.canvas, self.font, 11, y_pos, color, text)
            y_pos += 8

        weather_color = graphics.Color(255, 215, 0)
        x_pos = 64 - (len(self.weather_text) * 4)
        y_pos = 11
        graphics.DrawText(
            self.canvas, self.small_font, x_pos, y_pos, weather_color, self.weather_text
        )
        if self.weather_condition_text:
            x_pos = 64 - (len(self.weather_condition_text) * 4)
            y_pos = 17
            graphics.DrawText(
                self.canvas,
                self.small_font,
                x_pos,
                y_pos,
                weather_color,
                self.weather_condition_text,
            )
        self.draw_time()
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

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

        # Wait for the initial train fetch to finish so we don't clear the
        # "starting..." screen prematurely.
        if self._train_future:
            try:
                self._train_future.result()
            except Exception as e:
                logging.error(f"Initial train fetch failed: {e}")

        # Set up schedules
        schedule.every(30).seconds.do(self.fetch_trains_task)
        schedule.every(5).minutes.do(self.fetch_weather_task)
        schedule.every(5).seconds.do(self.check_config_task)

        while True:
            schedule.run_pending()
            self.render()
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
        clock.clear()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)

    clock.setup_matrix()
    clock.run()
