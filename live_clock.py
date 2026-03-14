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
options.drop_privileges = False # Required for Bookworm permissions
matrix = RGBMatrix(options=options)
canvas = matrix.CreateFrameCanvas()

# Load a smaller font to fit 3 lines of text
font_path = "/home/robert/rpi-rgb-led-matrix/fonts/5x8.bdf"
if not os.path.exists(font_path):
    print(f"Error: Font not found at {font_path}")
    sys.exit(1)

font = graphics.Font()
font.LoadFont(font_path)

# --- MTA Colors ---
# Tweaked slightly so they glow brightly on an LED matrix
colors = {
    'A': graphics.Color(50, 100, 255),   # Blue
    'C': graphics.Color(50, 100, 255),   # Blue
    'B': graphics.Color(255, 100, 0),    # Orange
}
default_color = graphics.Color(200, 200, 200)


def draw_route_bullet(canvas, font, x, y, route, bg_color):
    # 'y' is the text baseline. For an 8px font, center is ~3 pixels up.
    center_x = x + 4
    center_y = y - 3 
    
    # Draw a smaller filled circle (radius 4)
    for r in range(4, -1, -1):
        graphics.DrawCircle(canvas, center_x, center_y, r, bg_color)
        
    # Draw the white letter (tweaked offsets to center in the smaller bullet)
    white = graphics.Color(255, 255, 255)
    graphics.DrawText(canvas, font, x + 2, y, white, route)


def fetch_trains():
    arrivals = []
    
    for url in FEED_URLS:
        try:
            # Look ma, no API keys!
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

try:
    while True:
        trains = fetch_trains()
        canvas.Clear()

        # Start the first line's baseline at exactly pixel 8
        y_pos = 8
        now = int(time.time())

        # Display the next 3 trains (leaving room for line 4)
        for train in trains[:3]:
            route = train['route']
            minutes = max(0, int((train['time'] - now) / 60))

            bg_color = colors.get(route, default_color)
            draw_route_bullet(canvas, font, 2, y_pos, route, bg_color)

            if minutes == 0:
                text = "Arriving"
            else:
                text = f"{minutes} min"

            text_color = graphics.Color(200, 200, 200)
            graphics.DrawText(canvas, font, 14, y_pos, text_color, text)

            # Move down exactly 8 pixels for the next row
            y_pos += 8

        # [Line 4 will go here later, y_pos is now 32]

        canvas = matrix.SwapOnVSync(canvas)
        
        # Wait 30 seconds before polling the API again
        time.sleep(30)
        
except KeyboardInterrupt:
    sys.exit(0)
