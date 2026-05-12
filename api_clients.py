import requests
from requests.exceptions import RequestException
import time
import logging
from google.transit import gtfs_realtime_pb2
from concurrent.futures import ThreadPoolExecutor, as_completed
from timezonefinder import TimezoneFinder

# Loaded once per process — the binary timezone database is ~50 MB and
# TimezoneFinder is stateless after construction, so a single shared
# instance is safe across all WeatherClient objects.
_TIMEZONE_FINDER = TimezoneFinder()


class WeatherClient:
    FALLBACK_LAT = 41.50
    FALLBACK_LON = -73.97

    def __init__(self):
        self.session = requests.Session()
        self._tf = _TIMEZONE_FINDER
        self.weather_zip = None
        self.lat = None
        self.lon = None
        self.timezone_name = None

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
            self.timezone_name = None  # Invalidate cached timezone on new coords
            return self.lat, self.lon
        except RequestException as e:
            logging.error(f"Failed to translate Zip Code {zip_str}: {e}")
            return self.FALLBACK_LAT, self.FALLBACK_LON  # Fallback

    def get_timezone(self, zip_code):
        """Returns the IANA timezone string for a zip code, e.g. 'America/New_York'.

        Caches the result for the current zip/coordinates. Returns None on failure.
        """
        self.get_lat_lon(zip_code)  # Ensure lat/lon are populated
        if self.lat is None or self.lon is None:
            return None
        if self.timezone_name is None:
            self.timezone_name = self._tf.timezone_at(lat=self.lat, lng=self.lon)
            if self.timezone_name is None:
                logging.error(
                    f"Could not determine timezone for zip {zip_code} "
                    f"(lat={self.lat}, lon={self.lon})"
                )
        return self.timezone_name

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
        """Returns {'sunrise': ['...'], 'sunset': ['...']} or None on error."""
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
            daily = response.json().get("daily")
            if daily and daily.get("sunrise") and daily.get("sunset"):
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
