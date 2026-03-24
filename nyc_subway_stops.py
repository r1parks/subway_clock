#!/usr/bin/env python3

import csv
import logging
import json
import urllib.request

# The base URL, stripped of the query string
CSV_URL = "https://data.ny.gov/api/views/39hk-dx4f/rows.csv"

# The query parameters stored in a dictionary
CSV_PARAMS = {
    "accessType": "DOWNLOAD"
}

stops = {}

logging.info("Downloading MTA station data from NY State Open Data...")
req = urllib.request.Request(
        CSV_URL, params=CSV_PARAMS, headers={'User-Agent': 'Mozilla/5.0'}
      )
response = urllib.request.urlopen(req)
lines = [line.decode('utf-8') for line in response.readlines()]
reader = csv.DictReader(lines)

for row in reader:
    base_id = row.get('GTFS Stop ID', '').strip()
    if not base_id:
        continue

    stop_name = row.get('Stop Name', '').strip()
    routes = row.get('Daytime Routes', '').strip()

    display_name = f"{stop_name} [{routes}]" if routes else stop_name

    stops[f"{base_id}N"] = f"{display_name} (Uptown / Northbound)"
    stops[f"{base_id}S"] = f"{display_name} (Downtown / Southbound)"

# Sort alphabetically so the dropdown is easy to navigate
sorted_stops = dict(sorted(stops.items(), key=lambda item: item[1]))

with open('/home/robert/subway_clock/stops.json', 'w') as jsonfile:
    json.dump(sorted_stops, jsonfile, indent=2)

logging.info(
    f"Success! Generated stops.json mapping {len(sorted_stops)} platforms."
)
