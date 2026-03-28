import unittest
from datetime import datetime, time
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
            mock_datetime.now.return_value.time.return_value = time(21, 0)
            mock_datetime.strptime = datetime.strptime
            self.assertTrue(live_clock.is_night_mode(start, end))
            
        # Outside window
        with patch('live_clock.datetime') as mock_datetime:
            mock_datetime.now.return_value.time.return_value = time(19, 0)
            mock_datetime.strptime = datetime.strptime
            self.assertFalse(live_clock.is_night_mode(start, end))

        # Case 2: Start > End (Over midnight, e.g., 20:00 to 08:00)
        start = "20:00"
        end = "08:00"
        
        # Before midnight
        with patch('live_clock.datetime') as mock_datetime:
            mock_datetime.now.return_value.time.return_value = time(23, 0)
            mock_datetime.strptime = datetime.strptime
            self.assertTrue(live_clock.is_night_mode(start, end))
            
        # After midnight
        with patch('live_clock.datetime') as mock_datetime:
            mock_datetime.now.return_value.time.return_value = time(1, 0)
            mock_datetime.strptime = datetime.strptime
            self.assertTrue(live_clock.is_night_mode(start, end))
            
        # During day
        with patch('live_clock.datetime') as mock_datetime:
            mock_datetime.now.return_value.time.return_value = time(12, 0)
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

if __name__ == '__main__':
    unittest.main()
