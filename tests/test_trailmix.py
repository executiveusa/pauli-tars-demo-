import json
import unittest
from unittest import mock

import trailmix


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class _Response:
    def __init__(self, payload, headers=None):
        self.payload = json.dumps(payload).encode()
        self.headers = _Headers(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, n=-1):
        return self.payload if n < 0 else self.payload[:n]


class TrailMixxTests(unittest.TestCase):
    def test_unconfigured_is_truthful(self):
        out = trailmix.now_playing({})
        self.assertFalse(out["configured"])
        self.assertFalse(out["connected"])
        self.assertEqual([], out["stations"])

    def test_rejects_credentials_in_base_url(self):
        with self.assertRaises(trailmix.TrailMixxError):
            trailmix.now_playing({"base_url": "https://user:secret@example.com"})

    @mock.patch("trailmix.urllib.request.urlopen")
    def test_reads_public_nowplaying_and_sanitizes(self, urlopen):
        urlopen.return_value = _Response([
            {
                "station": {"id": 7, "name": "Trail Mixx Radio", "shortcode": "trailmixx", "listen_url": "secret-ish-field-not-forwarded"},
                "is_online": True,
                "now_playing": {
                    "played_at": 123,
                    "duration": 180,
                    "elapsed": 20,
                    "remaining": 160,
                    "song": {"title": "Example Track", "artist": "Example Artist", "album": "Example Album", "custom_fields": {"ignored": True}},
                },
                "listeners": {"current": 3, "unique": 2, "total": 4},
                "mounts": [{"url": "not-forwarded"}],
            }
        ])
        out = trailmix.now_playing({"base_url": "https://radio.example.com"})
        self.assertTrue(out["connected"])
        self.assertEqual("/api/nowplaying", out["endpoint"])
        self.assertEqual("Example Track", out["stations"][0]["now_playing"]["title"])
        self.assertNotIn("listen_url", out["stations"][0]["station"])
        self.assertNotIn("mounts", out["stations"][0])
        request = urlopen.call_args.args[0]
        self.assertEqual("https://radio.example.com/api/nowplaying", request.full_url)

    @mock.patch("trailmix.urllib.request.urlopen")
    def test_station_filter_accepts_id_or_shortcode(self, urlopen):
        urlopen.return_value = _Response([
            {"station": {"id": 1, "name": "One", "shortcode": "one"}, "is_online": True},
            {"station": {"id": 2, "name": "Two", "shortcode": "two"}, "is_online": True},
        ])
        out = trailmix.now_playing({"base_url": "https://radio.example.com", "station_id": "two"})
        self.assertEqual(1, len(out["stations"]))
        self.assertEqual("Two", out["stations"][0]["station"]["name"])


if __name__ == "__main__":
    unittest.main()
