#!/usr/bin/env python3

import logging
import json
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)
CONFIG_FILE = '/etc/subway-clock.json'


def parse_int(value, default, min_val=None, max_val=None):
    try:
        result = int(value)
        if min_val is not None:
            result = max(min_val, result)
        if max_val is not None:
            result = min(max_val, result)
        return result
    except (TypeError, ValueError):
        return default


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        logging.info(f'received form: {request.form}')
        new_config = {
            "portal_ssid": request.form.get('portal_ssid', 'SubwayClock'),

            "stop_ids": request.form.getlist('stop_ids'),

            "routes": [
                r.strip() for r in request.form.get('routes', '').split(',')
            ],
            "day_brightness": parse_int(request.form.get('day_brightness'), 100, 0, 100),
            "night_brightness": parse_int(request.form.get('night_brightness'), 2, 0, 100),
            "night_start_time": request.form.get('night_start_time', "20:00"),
            "night_end_time": request.form.get('night_end_time', "8:00"),
            "weather_zip": parse_int(request.form.get('weather_zip'), 10025),
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
    try:
        with open('/home/robert/subway_clock/stops.json', 'r') as f:
            all_stops = json.load(f)
    except Exception as e:
        logging.error(f"Error loading stops.json: {e}")
        all_stops = {}

    return render_template('index.html', config=config, all_stops=all_stops)


if __name__ == '__main__':
    # Run on port 80 to avoid users needing to type :5000
    app.run(host='0.0.0.0', port=80)
