import requests
from requests.exceptions import RequestException
import time
import logging
from google.transit import gtfs_realtime_pb2
from concurrent.futures import ThreadPoolExecutor, as_completed


class WeatherClient:
    FALLBACK_LAT = 41.50
    FALLBACK_LON = -73.97

    def __init__(self):
        self.session = requests.Session()
        self.weather_zip = None
        self.lat = None
        self.lon = None

    def get_lat_lon(self, zip_code):
        zip_str = str(zip_code)
        if (
            self.weather_zip == zip_str
            and self.lat is not None
            and self.lon is not None
        ):
            return self.lat, self.lon

        url = f"http://api.zippopotam.us/us/{zip_str}"
        try:
            response = self.session.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            self.lat = float(data["places"][0]["latitude"])
            self.lon = float(data["places"][0]["longitude"])
            self.weather_zip = zip_str  # Only cache on success

            return self.lat, self.lon
        except RequestException as e:
            logging.error(f"Failed to translate Zip Code {zip_str}: {e}")
            return self.FALLBACK_LAT, self.FALLBACK_LON  # Fallback

    def get_current_weather(self, zip_code):
        """Returns {'temperature': 72, 'weathercode': 51} or None on error."""
        endpoint = "https://api.open-meteo.com/v1/forecast"
        lat, lon = self.get_lat_lon(zip_code)
        params = {
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "temperature_unit": "fahrenheit",
        }
        try:
            response = self.session.get(endpoint, params=params, timeout=5)
            response.raise_for_status()
            data = response.json().get("current_weather")
            if not data:
                return None
            return {
                "temperature": int(data["temperature"]),
                "weathercode": data["weathercode"],
            }
        except RequestException as e:
            logging.error(f"Weather fetch error: {e}")
            return None

    def get_sun_forecast(self, zip_code):
        """Returns the Open-Meteo daily payload including sunrise, sunset, and
        timezone, or None on error.

        Example return value::

            {
                'sunrise': ['2026-05-12T05:47'],
                'sunset':  ['2026-05-12T20:11'],
                'timezone': 'America/New_York',
            }
        """
        endpoint = "https://api.open-meteo.com/v1/forecast"
        lat, lon = self.get_lat_lon(zip_code)
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": ["sunrise", "sunset"],
            "timezone": "auto",
        }
        try:
            response = self.session.get(endpoint, params=params, timeout=5)
            response.raise_for_status()
            body = response.json()
            daily = body.get("daily")
            if daily and daily.get("sunrise") and daily.get("sunset"):
                daily["timezone"] = body.get("timezone")
                return daily
            return None
        except RequestException as e:
            logging.error(f"Sun times fetch error: {e}")
            return None


class TransitClient:
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

    def __init__(self):
        self.session = requests.Session()

    def fetch_upcoming_trains(self, stop_ids, active_routes, current_timestamp=None):
        """Returns [{'route': 'A', 'time': 12345}, ...]"""
        new_arrivals = []
        now = current_timestamp if current_timestamp is not None else int(time.time())

        def fetch_url(url):
            try:
                response = self.session.get(url, timeout=5)
                if response.status_code != 200:
                    return None
                return response.content
            except RequestException as e:
                logging.error(f"Error fetching feed {url}: {e}")
                return None

        with ThreadPoolExecutor(max_workers=len(self.FEED_URLS)) as executor:
            future_to_url = {
                executor.submit(fetch_url, url): url for url in self.FEED_URLS
            }
            for future in as_completed(future_to_url):
                content = future.result()
                if not content:
                    continue
                try:
                    feed = gtfs_realtime_pb2.FeedMessage()
                    feed.ParseFromString(content)
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
                            if arrival_time >= now:
                                new_arrivals.append(
                                    {"route": route_id, "time": arrival_time}
                                )
                except Exception as e:
                    logging.error(f"Error parsing feed: {e}")

        new_arrivals.sort(key=lambda x: x["time"])
        return new_arrivals
