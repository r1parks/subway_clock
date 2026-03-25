#!/usr/bin/env python3

import logging
import json
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)
CONFIG_FILE = '/etc/subway-clock.json'


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        logging.info('received form: {request.form}')
        new_config = {
            "portal_ssid": request.form.get('portal_ssid', 'SubwayClock'),

            "stop_ids": request.form.getlist('stop_ids'),

            "routes": [
                r.strip() for r in request.form.get('routes', '').split(',')
            ],
            "day_brightness": int(request.form.get('day_brightness', 100)),
            "night_brightness": int(request.form.get('night_brightness', 2)),
            "night_start_time": request.form.get('night_start_time', "20:00"),
            "night_end_time": request.form.get('night_end_time', "8:00"),
            "weather_zip": int(request.form.get('weather_zip', 10025)),
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
