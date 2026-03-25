#!/usr/bin/env python3

import fcntl
import json
import logging
import os
import sys
import time
import requests
import signal
import subprocess
import qrcode
from datetime import datetime
from google.transit import gtfs_realtime_pb2
from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics

# --- Configuration ---
STOP_ID = "A19S"                   # 96th St Station (Downtown / Southbound)

FEED_URLS = [
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw",
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l",
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g",
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz",
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si",
]

# --- Matrix Setup ---
options = RGBMatrixOptions()
options.rows = 32
options.cols = 64
options.hardware_mapping = 'adafruit-hat'
options.drop_privileges = False  # Required for Bookworm permissions
matrix = RGBMatrix(options=options)
canvas = matrix.CreateFrameCanvas()

CONFIG_FILE = '/etc/subway-clock.json'


def acquire_lock():
    lock_file_path = '/tmp/live_clock.lock'
    try:
        lock_file = open(lock_file_path, 'w')
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file

    except (BlockingIOError, IOError):
        print("Failed to acquire lock. Exiting...")
        sys.exit(1)


_LOCK = acquire_lock()


def load_config():
    """Reads the SSOT config, supplying safe defaults if missing."""
    default_config = {
        "portal_ssid": "SubwayClock",
        "stop_ids": ["A19S"],
        "routes": ["A", "C", "B"],
        "day_brightness": 100,
        "night_brightness": 2,
        "night_start_time": "20:00",
        "night_end_time": "8:00",
        "weather_zip": 10025,
    }
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                user_config = json.load(f)
                # Overwrites defaults with whatever is actually in the file
                default_config.update(user_config)
    except Exception as e:
        logging.error(f"Error reading JSON config: {e}")

    return default_config


def clear_matrix_and_exit(signum, frame):
    logging.info("Stopping service and clearing matrix...")
    matrix.Clear()  # This physically turns off all LEDs
    sys.exit(0)


# Listen for systemd stop (SIGTERM) and Ctrl+C (SIGINT)
signal.signal(signal.SIGTERM, clear_matrix_and_exit)
signal.signal(signal.SIGINT, clear_matrix_and_exit)

# Load a smaller font to fit 4 lines of text (8px per line)
font_path = "/home/robert/rpi-rgb-led-matrix/fonts/5x8.bdf"
if not os.path.exists(font_path):
    logging.critical(f"Error: Font not found at {font_path}")
    sys.exit(1)

font = graphics.Font()
font.LoadFont(font_path)

train_font_path = "/home/robert/rpi-rgb-led-matrix/fonts/5x8.bdf"
if not os.path.exists(train_font_path):
    logging.critical(f"Error: Font not found at {train_font_path}")
    sys.exit(1)

train_font = graphics.Font()
train_font.LoadFont(train_font_path)

time_font_path = "/home/robert/rpi-rgb-led-matrix/fonts/4x6.bdf"
if not os.path.exists(time_font_path):
    logging.critical(f"Error: Font not found at {time_font_path}")
    sys.exit(1)

time_font = graphics.Font()
time_font.LoadFont(time_font_path)

graphics.DrawText(canvas,
                  font,
                  4,
                  16,
                  graphics.Color(200, 200, 0),
                  'starting...')
canvas = matrix.SwapOnVSync(canvas)

# --- Base Colors (Tuned for LED Matrices) ---
mta_blue = graphics.Color(0, 50, 255)
mta_orange = graphics.Color(255, 100, 0)
mta_light_green = graphics.Color(100, 255, 50)
mta_brown = graphics.Color(150, 100, 50)
mta_light_gray = graphics.Color(100, 100, 100)
mta_yellow = graphics.Color(200, 150, 0)
mta_red = graphics.Color(255, 0, 0)
mta_dark_green = graphics.Color(0, 200, 50)
mta_purple = graphics.Color(200, 0, 200)
mta_dark_gray = graphics.Color(75, 75, 75)
mta_default = graphics.Color(50, 50, 50)

# --- MTA Route Map ---
colors = {
    'A': mta_blue, 'C': mta_blue, 'E': mta_blue,
    'B': mta_orange, 'D': mta_orange, 'F': mta_orange, 'M': mta_orange,
    'G': mta_light_green,
    'J': mta_brown, 'Z': mta_brown,
    'L': mta_light_gray,
    'N': mta_yellow, 'Q': mta_yellow, 'R': mta_yellow, 'W': mta_yellow,
    '1': mta_red, '2': mta_red, '3': mta_red,
    '4': mta_dark_green, '5': mta_dark_green, '6': mta_dark_green,
    '7': mta_purple,
    'S': mta_dark_gray,
}

# Darker fallback gray so white text is readable if a route goes rogue
default_color = mta_default


def get_portal_ssid():
    """Reads the SSID from the system JSON configuration file."""
    try:
        with open('/etc/subway-clock.json', 'r') as f:
            config = json.load(f)
            return config.get('portal_ssid', 'setup-wifi')
    except Exception as e:
        logging.error(f"Error reading JSON config: {e}")

    return "SubwayClock"  # Fallback


def get_portal_ip():
    """Gets the live IP address of the Pi's Access Point."""
    try:
        # 'hostname -I' returns a space-separated list of active IPs
        result = subprocess.run(['hostname', '-I'],
                                stdout=subprocess.PIPE, text=True)
        ips = result.stdout.strip().split()
        if ips:
            return ips[0]
    except Exception as e:
        logging.error(f"Error reading IP: {e}")

    return "- 192.168.42.1"  # Balena's standard default fallback


class NoWeatherException(Exception):
    ...


def time_text():
    return time.strftime("%-I:%M").rjust(5)


def draw_time(canvas):
    time_color = graphics.Color(255, 215, 0)
    x_pos = 45
    y_pos = 5
    graphics.DrawText(canvas, time_font, x_pos, y_pos, time_color, time_text())


def draw_route_bullet(canvas, font, x, y, route, bg_color):
    center_x = x + 3
    center_y = y - 3

    # Hardcode the pixel widths for each row to create a perfect 7x7 circle.
    # A width of '1' draws 3 pixels (center - 1 to center + 1).
    # A width of '3' draws 7 pixels (center - 3 to center + 3).
    row_widths = [1, 2, 3, 3, 3, 3, 2, 1]

    for i, width in enumerate(row_widths):
        y_offset = i - 4  # Maps the 0-6 index to the -3 to +3 vertical offset
        graphics.DrawLine(canvas,
                          center_x - width,
                          center_y + y_offset,
                          center_x + width + 1,
                          center_y + y_offset,
                          bg_color)

    # Draw the white letter
    white = graphics.Color(255, 255, 255)
    graphics.DrawText(canvas, train_font, x + 2, y, white, route)


def fetch_weather(zip_code):
    weather_endpoint = "https://api.open-meteo.com/v1/forecast"
    lat, lon = get_lat_lon_from_zip(zip_code)
    weather_query_params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": "true",
        "temperature_unit": "fahrenheit"
    }
    try:
        # Pings Open-Meteo for local Beacon, NY forecast
        response = requests.get(weather_endpoint,
                                params=weather_query_params,
                                timeout=5)
        data = response.json()['current_weather']

        temp = int(data['temperature'])
        code = data['weathercode']

        # Map WMO weather codes to simple text that fits on the screen
        if code == 0:
            cond = "Clear"
        elif code in [1, 2, 3]:
            cond = "Cloudy"
        elif code in [45, 48]:
            cond = "Fog"
        elif code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]:
            cond = "Rain"
        elif code in [71, 73, 75, 77, 85, 86]:
            cond = "Snow"
        elif code in [95, 96, 99]:
            cond = "Storm"
        else:
            cond = ""

        return f"{temp}° {cond}"
    except Exception as e:
        logging.error(f"Weather fetch error: {e}")
        raise NoWeatherException from e


def fetch_trains(stop_ids, active_routes):
    arrivals = []

    for url in FEED_URLS:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            continue

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)

        for entity in feed.entity:
            if not entity.HasField('trip_update'):
                continue
            route_id = entity.trip_update.trip.route_id

            # We only care about A, C, and B trains
            if '*' not in active_routes and route_id not in active_routes:
                continue

            for stop_time in entity.trip_update.stop_time_update:
                if stop_time.stop_id not in stop_ids:
                    continue
                arrival_time = stop_time.arrival.time
                if arrival_time - int(time.time()) > 60:
                    arrivals.append({
                        'route': route_id,
                        'time': arrival_time
                    })
    # Sort by arrival time (soonest first)
    arrivals.sort(key=lambda x: x['time'])
    return arrivals


logging.info("Starting Subway Clock... Press Ctrl+C to exit.")


def is_night_mode(night_start, night_end):
    now = datetime.now().time()

    start_time = datetime.strptime(night_start, "%H:%M").time()
    end_time = datetime.strptime(night_end, "%H:%M").time()

    # Check if current time falls in the window (handling midnight rollover)
    if start_time < end_time:
        return start_time <= now <= end_time
    else:
        # The window crosses midnight (e.g., 20:00 to 08:00)
        return now >= start_time or now <= end_time


def update_brightness(matrix, current_brightness, day_b,
                      night_b, night_start, night_end):
    if is_night_mode(night_start, night_end):
        target_brightness = night_b
    else:
        target_brightness = day_b

    if current_brightness != target_brightness:
        matrix.brightness = current_brightness = target_brightness

    return current_brightness


def captive_portal_running():
    """Returns True if the wifi-connect service is actively running."""
    try:
        # Ask systemd if the service is active
        result = subprocess.run(
            ['systemctl', 'is-active', 'wifi-connect.service'],
            stdout=subprocess.PIPE,
            text=True
        )
        # If it's running, systemd returns the word 'active'
        return result.stdout.strip() == 'active'
    except Exception as e:
        logging.exception(e)
        return False


def display_wifi_qr(matrix, canvas):
    ssid = get_portal_ssid()
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

    canvas.Clear()

    x_offset = (64 - qr_size) // 2
    y_offset = (32 - qr_size) // 2

    for y, row in enumerate(qr_matrix):
        for x, cell in enumerate(row):
            if cell:
                canvas.SetPixel(x + x_offset, y + y_offset, 255, 255, 255)

    return matrix.SwapOnVSync(canvas)


def route_name(route_id):
    route_id_translation = {
        "GS": "S",
        "FS": "S",
        "H":  "S",
        "SI": "S",
        "SIR": "S",
    }
    return route_id_translation.get(route_id, route_id)


LAT = None
LON = None
WEATHER_ZIP = None


def get_lat_lon_from_zip(zip_code):
    """Translates a US Zip Code to Latitude and Longitude using a free API."""
    global LAT, LON, WEATHER_ZIP
    if WEATHER_ZIP == zip_code and LAT is not None and LON is not None:
        return LAT, LON

    WEATHER_ZIP = zip_code
    url = f"http://api.zippopotam.us/us/{zip_code}"

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        LAT = float(data['places'][0]['latitude'])
        LON = float(data['places'][0]['longitude'])

        return LAT, LON

    except requests.exceptions.RequestException as e:
        print(f"Failed to translate Zip Code {zip_code}: {e}")
        return 41.50, -73.97


weather_text = ''
new_weather_text = ''
current_brightness = None
while True:
    config = load_config()

    if captive_portal_running():
        logging.info("Detected captive portal running, updating display")
        canvas = display_wifi_qr(matrix, canvas)
        time.sleep(10)
        continue
    try:
        trains = []
        trains = fetch_trains(config['stop_ids'], config['routes'])
    except Exception as e:
        logging.error("failed to fetch train info")
        logging.exception(e)
    try:
        new_weather_text = ''
        new_weather_text = fetch_weather(config['weather_zip'])
        weather_text = new_weather_text
    except Exception as e:
        logging.error("failed to fetch weather info")
        logging.exception(e)

    if not trains and not new_weather_text:
        time.sleep(10)
        continue

    current_brightness = update_brightness(
        matrix,
        current_brightness,
        config['day_brightness'],
        config['night_brightness'],
        config['night_start_time'],
        config['night_end_time']
    )
    canvas.Clear()

    y_pos = 7
    now = int(time.time())

    # 1. Display the next 3 trains
    for train in trains[:3]:
        route_id = train['route']
        route = route_name(route_id)
        minutes = max(0, int((train['time'] - now) / 60))

        bg_color = colors.get(route, default_color)
        draw_route_bullet(canvas, font, 0, y_pos, route, bg_color)

        if minutes == 0:
            text = "Now"
        else:
            text = f"{minutes} min"

        text_color = graphics.Color(200, 200, 200)
        graphics.DrawText(canvas, font, 11, y_pos, text_color, text)

        # Move down exactly 8 pixels for the next row
        y_pos += 8

    # 2. Display the weather on Line 4 (y_pos is now exactly 32)
    # Using a bright yellow/gold to separate it visually from the transit times
    weather_color = graphics.Color(255, 215, 0)
    graphics.DrawText(canvas, time_font, 2, 31, weather_color, weather_text)

    draw_time(canvas)
    canvas = matrix.SwapOnVSync(canvas)

    # Wait 30 seconds before polling the APIs again
    time.sleep(30)
