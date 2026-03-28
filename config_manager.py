import json
import os
import logging

CONFIG_FILE = '/etc/subway-clock.json'

class Config:
    def __init__(self):
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
        """Loads configuration from the file, applying defaults for missing values."""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    user_config = json.load(f)
                    self.config.update(user_config)
            else:
                logging.warning(f"Config file {CONFIG_FILE} not found. Using defaults.")
        except Exception as e:
            logging.error(f"Error reading JSON config: {e}")

    def save(self):
        """Saves the current configuration to the file."""
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logging.error(f"Error writing config file: {e}")

    def get(self, field, default=None):
        """Retrieves a configuration value, returning the default if not found."""
        return self.config.get(field, default if default is not None else self.defaults.get(field))

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
