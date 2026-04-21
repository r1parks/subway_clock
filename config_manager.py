import json
import os
import logging

DEFAULT_CONFIG_FILE = "/etc/subway-clock.json"


class Config:
    def __init__(self, config_file=None):
        self.config_file = config_file or DEFAULT_CONFIG_FILE
        self._last_mtime = 0
        self.defaults = {
            "portal_ssid": "SubwayClock",
            "stop_ids": ["A19S"],
            "routes": ["A", "C", "B"],
            "day_brightness": 100,
            "night_brightness": 2,
            "night_start_time": "20:00",
            "night_end_time": "08:00",
            "weather_zip": 10025,
        }
        self.config = self.defaults.copy()
        self.load()

    def load(self):
        """Loads configuration from the file."""
        try:
            if os.path.exists(self.config_file):
                self._last_mtime = os.path.getmtime(self.config_file)
                with open(self.config_file, "r") as f:
                    user_config = json.load(f)
                    self.config.update(user_config)
            else:
                logging.warning(
                    f"Config file {self.config_file} not found. " "Using defaults."
                )
        except Exception as e:
            logging.error(f"Error reading JSON config: {e}")

    def is_modified(self):
        """Checks if the config file has been modified on disk."""
        if not os.path.exists(self.config_file):
            return False
        try:
            return os.path.getmtime(self.config_file) > self._last_mtime
        except OSError:
            return False

    def save(self):
        """Saves the current configuration to the file."""
        try:
            with open(self.config_file, "w") as f:
                json.dump(self.config, f, indent=2)
        except IOError as e:
            logging.error(f"Error writing config file: {e}")
        except Exception as e:
            logging.error(f"An unexpected error occurred while writing config: {e}")

    def get(self, field, default=None):
        """Retrieves a configuration value."""
        return self.config.get(
            field, default if default is not None else self.defaults.get(field)
        )

    def set(self, field, value):
        """Sets a configuration value and persists it to the file."""
        self.config[field] = value
        self.save()

    def update_bulk(self, new_values):
        """Updates multiple configuration values at once and saves."""
        self.config.update(new_values)
        self.save()

    def to_dict(self):
        """Returns the current configuration as a dictionary."""
        return self.config.copy()
