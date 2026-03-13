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
font_path = "/home/robert/rpi-rgb-led-matrix/fonts/6x10.bdf"
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
                if entity.HasField('trip_update'):
                    route_id = entity.trip_update.trip.route_id
                    
                    # We only care about A, C, and B trains
                    if route_id not in ['A', 'C', 'B']:
                        continue
                        
                    for stop_time in entity.trip_update.stop_time_update:
                        if stop_time.stop_id == STOP_ID:
                            arrival_time = stop_time.arrival.time
                            # Only add trains that haven't arrived yet
                            if arrival_time > 0:
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
        
        y_pos = 10
        now = int(time.time())
        
        # Display the next 3 trains
        for train in trains[:3]:
            route = train['route']
            
            # Calculate minutes away
            minutes = max(0, int((train['time'] - now) / 60))
            
            # Format text
            if minutes == 0:
                text = f"{route} Train: Due"
            else:
                text = f"{route} Train: {minutes} min"
                
            color = colors.get(route, default_color)
            
            # Draw to the hidden canvas
            graphics.DrawText(canvas, font, 2, y_pos, color, text)
            
            # Move down 10 pixels for the next line
            y_pos += 10
            
        # Push the hidden canvas to the actual LED matrix
        canvas = matrix.SwapOnVSync(canvas)
        
        # Wait 30 seconds before polling the API again
        time.sleep(30)
        
except KeyboardInterrupt:
    sys.exit(0)
