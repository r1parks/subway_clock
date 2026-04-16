import unittest
import sys


# 1. Extreme Mocking - no MagicMock
class MockFlask:
    def __init__(self):
        self.request = MockRequest()
        self.render_template_called = False
        self.render_template_args = None
        self.redirect_called = False

    def Flask(self, name):
        return self

    def render_template(self, *args, **kwargs):
        self.render_template_called = True
        self.render_template_args = (args, kwargs)
        return "rendered"

    def redirect(self, url):
        self.redirect_called = True
        return "redirected"

    def url_for(self, name):
        return "/url"

    def route(self, path, **kwargs):
        def decorator(f):
            return f
        return decorator


class MockRequest:
    def __init__(self):
        self.method = 'GET'
        self.form = {}

    def get(self, k, d=None):
        return self.form.get(k, d)

    def getlist(self, k):
        return []


mock_flask = MockFlask()
sys.modules['flask'] = mock_flask

import web_server  # noqa: E402
web_server.flask = mock_flask


class MockConfig:
    def __init__(self):
        self.update_bulk_called = False

    def load(self):
        pass

    def to_dict(self):
        return {"portal_ssid": "test"}

    def update_bulk(self, data):
        self.update_bulk_called = True


class TestWebServer(unittest.TestCase):
    def test_parse_int(self):
        self.assertEqual(web_server.parse_int("10", 0), 10)
        self.assertEqual(web_server.parse_int("abc", 5), 5)
        self.assertEqual(web_server.parse_int(None, 7), 7)
        self.assertEqual(web_server.parse_int("5", 0, min_val=10), 10)
        self.assertEqual(web_server.parse_int("15", 0, max_val=10), 10)

    def test_get_all_stops_failure(self):
        # Mock STOPS_FILE to point to a non-existent file
        original_stops_file = web_server.STOPS_FILE
        web_server.STOPS_FILE = "non_existent_stops.json"
        web_server._stops_cache = None  # Clear cache
        try:
            stops = web_server.get_all_stops()
            self.assertEqual(stops, {})
        finally:
            web_server.STOPS_FILE = original_stops_file

    def test_index_get(self):
        web_server.config_obj = MockConfig()
        mock_flask.request.method = 'GET'
        mock_flask.render_template_called = False

        web_server.index()
        self.assertTrue(mock_flask.render_template_called)

    def test_index_post(self):
        web_server.config_obj = MockConfig()
        mock_flask.request.method = 'POST'
        mock_flask.request.form = {'portal_ssid': 'new'}

        # Patching the form to have a get method like a dict/MultiDict
        class Form(dict):
            def getlist(self, k):
                return []
        mock_flask.request.form = Form(mock_flask.request.form)

        web_server.index()
        self.assertTrue(web_server.config_obj.update_bulk_called)

    def test_debug(self):
        import subprocess

        # Mock subprocess.run
        original_run = subprocess.run

        class MockResult:
            def __init__(self, stdout, stderr=""):
                self.stdout = stdout
                self.stderr = stderr

        def mock_run(*args, **kwargs):
            return MockResult("mock logs")
        subprocess.run = mock_run

        try:
            mock_flask.render_template_called = False
            web_server.debug()
            self.assertTrue(mock_flask.render_template_called)
            # Check if logs were passed
            args, kwargs = mock_flask.render_template_args
            self.assertIn('logs', kwargs)
            self.assertEqual(
                kwargs['logs']['subway-clock.service'], "mock logs"
            )
        finally:
            subprocess.run = original_run


if __name__ == '__main__':
    unittest.main()
