#!/usr/bin/env python3

from flask import Flask, render_template, request, redirect, url_for
import json

app = Flask(__name__)
CONFIG_FILE = '/etc/subway-clock.json'


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        new_config = {
            "portal_ssid": request.form.get('portal_ssid', 'SubwayClock'),

            "stop_ids": request.form.getlist('stop_ids'),

            "routes": [
                r.strip() for r in request.form.get('routes', '').split(',')
            ],
            "day_brightness": int(request.form.get('day_brightness', 100)),
            "night_brightness": int(request.form.get('night_brightness', 2)),
            "night_start_hour": int(request.form.get('night_start_hour', 20)),
            "night_end_hour": int(request.form.get('night_end_hour', 8)),
            "weather_lat": float(request.form.get('weather_lat', 41.50)),
            "weather_lon": float(request.form.get('weather_lon', -73.97))
        }

        with open(CONFIG_FILE, 'w') as f:
            json.dump(new_config, f, indent=2)

        return redirect(url_for('index'))

    # --- GET REQUEST (Load Page) ---
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    except Exception:
        config = {}

    # Load the human-readable stops mapping we just generated
    with open('/home/robert/subway_clock/stops.json', 'r') as f:
        all_stops = json.load(f)

    return render_template('index.html', config=config, all_stops=all_stops)


if __name__ == '__main__':
    # Run on port 80 to avoid users needing to type :5000
    app.run(host='0.0.0.0', port=80)
