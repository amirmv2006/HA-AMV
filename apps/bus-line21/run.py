"""Fetch GVB line 21 departures at Solebaystraat from OVapi and serve them as JSON.

The latest result is served at http://<app-hostname>:8099/bus_line21.json on
the Home Assistant internal network (no host port is published), so Home
Assistant can read it with a REST sensor without any shared folder.
"""
import gzip
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

from google.transit import gtfs_realtime_pb2

FEED_URL = "https://gtfs.ovapi.nl/nl/tripUpdates.pb"
ROUTE_ID = "152335"  # GVB line 21
STOP_NAME = "Solebaystraat"
# stop_id -> label shown for that direction
STOPS = {
    "3980704": "Centraal Station",
    "3981354": "Geuzenveld De Sav. Lohmanstraat",
}
PER_DIRECTION = 2
POLL_SECONDS = int(os.environ.get("BUS_POLL_SECONDS", "60"))
HTTP_PORT = int(os.environ.get("BUS_HTTP_PORT", "8099"))
OPTIONS_PATH = os.environ.get("BUS_OPTIONS", "/data/options.json")
AMS = ZoneInfo("Europe/Amsterdam")

_latest_lock = threading.Lock()
_latest_body = None  # bytes of the last good JSON payload


def load_contact():
    """Contact address from app options. Empty means no contact in the User-Agent."""
    try:
        with open(OPTIONS_PATH) as f:
            return (json.load(f).get("contact_email") or "").strip()
    except (OSError, ValueError):
        return ""


def user_agent(contact):
    base = "HA-AMV-bus-line21/0.1"
    return f"{base} ({contact})" if contact else base


class Feed:
    """Polls the trip-updates feed with conditional requests and gzip."""

    def __init__(self, ua):
        self.ua = ua
        self.etag = None
        self.last_modified = None
        self.message = None

    def fetch(self):
        headers = {"User-Agent": self.ua, "Accept-Encoding": "gzip"}
        if self.etag:
            headers["If-None-Match"] = self.etag
        if self.last_modified:
            headers["If-Modified-Since"] = self.last_modified
        req = urllib.request.Request(FEED_URL, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                self.etag = resp.headers.get("ETag")
                self.last_modified = resp.headers.get("Last-Modified")
        except urllib.error.HTTPError as err:
            if err.code == 304 and self.message is not None:
                return self.message  # unchanged; times are absolute, so recompute below
            raise
        msg = gtfs_realtime_pb2.FeedMessage()
        msg.ParseFromString(raw)
        self.message = msg
        return msg


def departures(msg, now_ts):
    """Next arrivals per direction for the configured stops on line 21."""
    found = {label: [] for label in STOPS.values()}
    for ent in msg.entity:
        if not ent.HasField("trip_update"):
            continue
        tu = ent.trip_update
        if tu.trip.route_id != ROUTE_ID:
            continue
        for stu in tu.stop_time_update:
            label = STOPS.get(stu.stop_id)
            if label is None:
                continue
            event = stu.arrival if stu.HasField("arrival") else stu.departure
            ts = event.time
            if ts == 0 or ts < now_ts - 30:
                continue
            found[label].append((ts, event.delay))
    result = {}
    for label, items in found.items():
        items.sort()
        result[label] = [
            {
                "time": datetime.fromtimestamp(ts, AMS).isoformat(timespec="minutes"),
                "minutes": max(0, round((ts - now_ts) / 60)),
                "delay_seconds": delay,
            }
            for ts, delay in items[:PER_DIRECTION]
        ]
    return result


def build_payload(directions, now_ts, feed_ts):
    return {
        "stop_name": STOP_NAME,
        "route": "21",
        "updated": datetime.fromtimestamp(now_ts, AMS).isoformat(timespec="seconds"),
        "feed_timestamp": datetime.fromtimestamp(feed_ts, AMS).isoformat(timespec="seconds") if feed_ts else None,
        "directions": directions,
    }


def publish(payload):
    global _latest_body
    body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    with _latest_lock:
        _latest_body = body
    return body


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] not in ("/", "/bus_line21.json"):
            self.send_error(404)
            return
        with _latest_lock:
            body = _latest_body
        if body is None:
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "no data yet"}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # keep the add-on log quiet
        pass


def start_server():
    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"serving /bus_line21.json on port {HTTP_PORT}", flush=True)


def poll_once(feed):
    msg = feed.fetch()
    now_ts = time.time()
    payload = build_payload(departures(msg, now_ts), now_ts, msg.header.timestamp)
    return publish(payload)


def main():
    feed = Feed(user_agent(load_contact()))
    once = "--once" in sys.argv
    if once:
        try:
            print(poll_once(feed).decode("utf-8"))
        except Exception as err:
            print(f"poll failed: {err}", file=sys.stderr)
            sys.exit(1)
        return

    start_server()
    while True:
        try:
            poll_once(feed)
            print("updated", datetime.now(AMS).isoformat(timespec="seconds"), flush=True)
        except Exception as err:  # keep serving the last good payload; retry next round
            print(f"poll failed: {err}", file=sys.stderr, flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
