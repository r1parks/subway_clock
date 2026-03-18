#!/usr/bin/env python3

import os
import sys
import time
import requests
from google.transit import gtfs_realtime_pb2
from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics

# --- Configuration ---
STOP_ID = "A19S"                   # 96th St Station (Downtown / Southbound)

FEED_URLS = [
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",
    "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm"
]

# --- Matrix Setup ---
options = RGBMatrixOptions()
options.rows = 32
options.cols = 64
options.hardware_mapping = 'adafruit-hat'
options.drop_privileges = False  # Required for Bookworm permissions
matrix = RGBMatrix(options=options)
canvas = matrix.CreateFrameCanvas()

# Load a smaller font to fit 4 lines of text (8px per line)
font_path = "/home/robert/rpi-rgb-led-matrix/fonts/5x8.bdf"
if not os.path.exists(font_path):
    print(f"Error: Font not found at {font_path}")
    sys.exit(1)

font = graphics.Font()
font.LoadFont(font_path)

time_font_path = "/home/robert/rpi-rgb-led-matrix/fonts/4x6.bdf"
if not os.path.exists(time_font_path):
    print(f"Error: Font not found at {time_font_path}")
    sys.exit(1)

time_font = graphics.Font()
time_font.LoadFont(time_font_path)

graphics.DrawText(canvas,
                  font,
                  4,
                  16,
                  graphics.Color(200, 200, 200),
                  'starting...')
canvas = matrix.SwapOnVSync(canvas)

# --- MTA Colors ---
colors = {
    'A': graphics.Color(0, 0, 255),   # Blue
    'C': graphics.Color(0, 0, 255),   # Blue
    'B': graphics.Color(255, 100, 0),    # Orange
}
default_color = graphics.Color(200, 200, 200)


class NoWeatherException(Exception):
    ...


def draw_time(canvas):
    time_color = graphics.Color(255, 215, 0)
    hh_mm_time = time.strftime("%-I:%M")
    x_pos = 45
    y_pos = 5
    graphics.DrawText(canvas, time_font, x_pos, y_pos, time_color, hh_mm_time)


def draw_route_bullet(canvas, font, x, y, route, bg_color):
    center_x = x + 3
    center_y = y - 3

    # Hardcode the pixel widths for each row to create a perfect 7x7 circle.
    # A width of '1' draws 3 pixels (center - 1 to center + 1).
    # A width of '3' draws 7 pixels (center - 3 to center + 3).
    row_widths = [1, 2, 3, 3, 3, 2, 1]

    for i, width in enumerate(row_widths):
        y_offset = i - 3  # Maps the 0-6 index to the -3 to +3 vertical offset
        graphics.DrawLine(canvas,
                          center_x - width,
                          center_y + y_offset,
                          center_x + width,
                          center_y + y_offset,
                          bg_color)

    # Draw the white letter
    white = graphics.Color(255, 255, 255)
    graphics.DrawText(canvas, font, x + 1, y, white, route)


def fetch_weather():
    # Define the base endpoint
    weather_endpoint = "https://api.open-meteo.com/v1/forecast"

    # Build the dictionary of parameters
    weather_query_params = {
        "latitude": 41.50,
        "longitude": -73.97,
        "current_weather": "true",
        "temperature_unit": "fahrenheit"
    }

    # Pass the dictionary to the 'params' argument
    try:
        # Pings Open-Meteo for local Beacon, NY forecast
        response = requests.get(weather_endpoint, params=weather_query_params, timeout=5)
        data = response.json()['current_weather']

        temp = int(data['temperature'])
        code = data['weathercode']

        # Map WMO weather codes to simple text that fits on the screen
        if code == 0: cond = "Clear"
        elif code in [1, 2, 3]: cond = "Cloudy"
        elif code in [45, 48]: cond = "Fog"
        elif code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]: cond = "Rain"
        elif code in [71, 73, 75, 77, 85, 86]: cond = "Snow"
        elif code in [95, 96, 99]: cond = "Storm"
        else: cond = ""

        return f"{temp}° {cond}"
    except Exception as e:
        print(f"Weather fetch error: {e}")
        raise NoWeatherException(e.message)


def fetch_trains():
    arrivals = []

    for url in FEED_URLS:
        try:
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
                if route_id not in ['A', 'C', 'B']:
                    continue

                for stop_time in entity.trip_update.stop_time_update:
                    if stop_time.stop_id != STOP_ID:
                        continue
                    arrival_time = stop_time.arrival.time
                    arrivals.append({
                        'route': route_id,
                        'time': arrival_time
                    })
        except Exception as e:
            print(f"Feed error: {e}")

    # Sort by arrival time (soonest first)
    arrivals.sort(key=lambda x: x['time'])
    return arrivals


print("Starting Subway Clock... Press Ctrl+C to exit.")


weather_text = "weather..."
try:
    while True:
        # Fetch data
        trains = fetch_trains()
        try:
            weather_text = fetch_weather()
        except:
            pass


        canvas.Clear()

        # Start the first line's baseline at exactly pixel 8
        y_pos = 7
        now = int(time.time())

        # 1. Display the next 3 trains
        for train in trains[:3]:
            route = train['route']
            minutes = max(0, int((train['time'] - now) / 60))

            bg_color = colors.get(route, default_color)
            draw_route_bullet(canvas, font, 2, y_pos, route, bg_color)

            if minutes == 0:
                text = "Now"
            else:
                text = f"{minutes} min"

            text_color = graphics.Color(200, 200, 200)
            graphics.DrawText(canvas, font, 13, y_pos, text_color, text)

            # Move down exactly 8 pixels for the next row
            y_pos += 8

        # 2. Display the weather on Line 4 (y_pos is now exactly 32)
        # Using a bright yellow/gold to separate it visually from the transit times
        weather_color = graphics.Color(255, 215, 0)
        graphics.DrawText(canvas, font, 2, y_pos, weather_color, weather_text)

        draw_time(canvas)
        canvas = matrix.SwapOnVSync(canvas)

        # Wait 30 seconds before polling the APIs again
        time.sleep(30)
except KeyboardInterrupt:
    print("Bye")
    sys.exit(0)
