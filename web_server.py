#!/usr/bin/env python3

import logging
import os
import subprocess
import flask
from config_manager import Config

app = flask.Flask(__name__)
# Use absolute path relative to this script for the project's stops.json
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STOPS_FILE = os.path.join(SCRIPT_DIR, 'stops.json')

# Initialize global config
config_obj = Config()

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
    if flask.request.method == 'POST':
        logging.info(f'received form: {flask.request.form}')
        new_config = {
            "portal_ssid": flask.request.form.get('portal_ssid', 'SubwayClock'),
            "stop_ids": flask.request.form.getlist('stop_ids'),
            "routes": [
                r.strip() for r in flask.request.form.get('routes', '').split(',') if r.strip()
            ],
            "day_brightness": parse_int(flask.request.form.get('day_brightness'), 100, 0, 100),
            "night_brightness": parse_int(flask.request.form.get('night_brightness'), 2, 0, 100),
            "night_start_time": flask.request.form.get('night_start_time', "20:00"),
            "night_end_time": flask.request.form.get('night_end_time', "08:00"),
            "weather_zip": parse_int(flask.request.form.get('weather_zip'), 10025),
        }

        config_obj.update_bulk(new_config)
        return flask.redirect(flask.url_for('index'))

    # --- GET REQUEST (Load Page) ---
    config_obj.load()
    config = config_obj.to_dict()

    # Load the human-readable stops mapping
    try:
        if os.path.exists(STOPS_FILE):
            with open(STOPS_FILE, 'r') as f:
                import json
                all_stops = json.load(f)
        else:
            logging.warning(f"{STOPS_FILE} not found. Run nyc_subway_stops.py first.")
            all_stops = {}
    except Exception as e:
        logging.error(f"Error loading stops.json: {e}")
        all_stops = {}

    return flask.render_template('index.html', config=config, all_stops=all_stops)


@app.route('/debug')
def debug():
    services = ['subway-clock.service', 'subway-web.service', 'wifi-connect.service']
    logs = {}
    for service in services:
        try:
            # -n 200 for last 200 lines, --no-pager to avoid hanging
            result = subprocess.run(
                ['journalctl', '-u', service, '-n', '200', '--no-pager'],
                capture_output=True,
                text=True,
                check=False
            )
            logs[service] = result.stdout if result.stdout else f"No logs found for {service}"
        except Exception as e:
            logs[service] = f"Error retrieving logs for {service}: {e}"

    return flask.render_template('debug.html', logs=logs)


if __name__ == '__main__':
    # Run on port 80 as requested for dedicated hardware service
    app.run(host='0.0.0.0', port=80)
