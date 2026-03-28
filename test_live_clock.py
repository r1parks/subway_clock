import unittest
from datetime import datetime, time as dt_time
import time
from unittest.mock import MagicMock, patch
import sys

# Mock hardware and transit libraries before importing live_clock
mock_matrix = MagicMock()
mock_transit = MagicMock()
sys.modules['rgbmatrix'] = mock_matrix
sys.modules['google.transit'] = mock_transit
sys.modules['google.transit.gtfs_realtime_pb2'] = MagicMock()
sys.modules['qrcode'] = MagicMock()

import live_clock

class TestLiveClock(unittest.TestCase):
    def test_is_night_mode(self):
        # Case 1: Start < End (e.g., 20:00 to 22:00)
        start = "20:00"
        end = "22:00"
        
        # Inside window
        with patch('live_clock.datetime') as mock_datetime:
            mock_datetime.now.return_value.time.return_value = dt_time(21, 0)
            mock_datetime.strptime = datetime.strptime
            self.assertTrue(live_clock.is_night_mode(start, end))
            
        # Outside window
        with patch('live_clock.datetime') as mock_datetime:
            mock_datetime.now.return_value.time.return_value = dt_time(19, 0)
            mock_datetime.strptime = datetime.strptime
            self.assertFalse(live_clock.is_night_mode(start, end))

        # Case 2: Start > End (Over midnight, e.g., 20:00 to 08:00)
        start = "20:00"
        end = "08:00"
        
        # Before midnight
        with patch('live_clock.datetime') as mock_datetime:
            mock_datetime.now.return_value.time.return_value = dt_time(23, 0)
            mock_datetime.strptime = datetime.strptime
            self.assertTrue(live_clock.is_night_mode(start, end))
            
        # After midnight
        with patch('live_clock.datetime') as mock_datetime:
            mock_datetime.now.return_value.time.return_value = dt_time(1, 0)
            mock_datetime.strptime = datetime.strptime
            self.assertTrue(live_clock.is_night_mode(start, end))
            
        # During day
        with patch('live_clock.datetime') as mock_datetime:
            mock_datetime.now.return_value.time.return_value = dt_time(12, 0)
            mock_datetime.strptime = datetime.strptime
            self.assertFalse(live_clock.is_night_mode(start, end))

    def test_route_name(self):
        self.assertEqual(live_clock.route_name("GS"), "S")
        self.assertEqual(live_clock.route_name("FS"), "S")
        self.assertEqual(live_clock.route_name("A"), "A")
        self.assertEqual(live_clock.route_name("SIR"), "S")

    def test_update_brightness(self):
        mock_matrix = MagicMock()
        mock_matrix.brightness = 100
        
        # Test switch to night mode
        with patch('live_clock.is_night_mode', return_value=True):
            new_brightness = live_clock.update_brightness(mock_matrix, 100, 100, 2, "20:00", "08:00")
            self.assertEqual(new_brightness, 2)
            self.assertEqual(mock_matrix.brightness, 2)
            
        # Test stay in day mode
        mock_matrix.brightness = 100
        with patch('live_clock.is_night_mode', return_value=False):
            new_brightness = live_clock.update_brightness(mock_matrix, 100, 100, 2, "20:00", "08:00")
            self.assertEqual(new_brightness, 100)
            self.assertEqual(mock_matrix.brightness, 100)

    @patch('live_clock.requests.get')
    def test_fetch_weather_success(self, mock_get):
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'current_weather': {
                'temperature': 72,
                'weathercode': 0
            }
        }
        mock_get.return_value = mock_response
        
        # Mock get_lat_lon_from_zip to avoid another network call
        with patch('live_clock.get_lat_lon_from_zip', return_value=(40.71, -74.00)):
            result = live_clock.fetch_weather(10001)
            self.assertEqual(result, "72° Clear")

    @patch('live_clock.requests.get')
    def test_fetch_trains_mock(self, mock_get):
        # Mock a minimal GTFS response for the first call, empty for others
        mock_response = MagicMock()
        mock_response.status_code = 200
        
        # We only want one response to succeed with data
        mock_empty = MagicMock()
        mock_empty.status_code = 404 # Skip others
        
        mock_get.side_effect = [mock_response] + [mock_empty] * 7
        
        with patch('live_clock.gtfs_realtime_pb2.FeedMessage') as mock_feed_class:
            mock_feed = mock_feed_class.return_value
            # Create a mock entity
            entity = MagicMock()
            entity.HasField.side_effect = lambda x: x == 'trip_update'
            entity.trip_update.trip.route_id = 'A'
            
            stop_time = MagicMock()
            stop_time.stop_id = 'A19S'
            stop_time.HasField.side_effect = lambda x: x == 'arrival'
            stop_time.arrival.HasField.side_effect = lambda x: x == 'time'
            stop_time.arrival.time = int(time.time()) + 300 # 5 mins from now
            
            entity.trip_update.stop_time_update = [stop_time]
            mock_feed.entity = [entity]
            
            arrivals = live_clock.fetch_trains(['A19S'], ['A'])
            self.assertEqual(len(arrivals), 1)
            self.assertEqual(arrivals[0]['route'], 'A')

if __name__ == '__main__':
    unittest.main()
