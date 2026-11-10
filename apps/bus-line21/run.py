"""Fetch GVB line 21 departures at Solebaystraat from OVapi and serve them as JSON.

The latest result is served at http://<app-hostname>:8099/bus_line21.json on
the Home Assistant internal network (no host port is published), so Home
Assistant can read it with a REST sensor without any shared folder.

Per direction the app keeps the next departure it has seen (absolute time,
delay) and how old that information is. Empty or failed polls keep the last
departure and let its age grow. Once the departure time has passed, all three
fields are reset to null. Remaining minutes are computed by the consumer.
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
GRACE_SECONDS = 30  # a bus counts as gone this many seconds after its time
POLL_SECONDS = int(os.environ.get("BUS_POLL_SECONDS", "60"))
HTTP_PORT = int(os.environ.get("BUS_HTTP_PORT", "8099"))
OPTIONS_PATH = os.environ.get("BUS_OPTIONS", "/data/options.json")
AMS = ZoneInfo("Europe/Amsterdam")

_latest_lock = threading.Lock()
_latest_body = None  # bytes of the last published JSON payload


def load_contact():
    """Contact address from app options. Empty means no contact in the User-Agent."""
    try:
        with open(OPTIONS_PATH) as f:
            return (json.load(f).get("contact_email") or "").strip()
    except (OSError, ValueError):
        return ""


def user_agent(contact):
    base = "HA-AMV-bus-line21/0.2"
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


def new_state():
    return {
        "feed_ts": None,
        "directions": {
            label: {"departure_ts": None, "delay_seconds": None, "fresh_ts": None}
            for label in STOPS.values()
        },
    }


def next_departures(msg, now_ts):
    """Earliest upcoming arrival per direction in this feed: {label: (ts, delay)}."""
    found = {}
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
            if ts == 0 or ts < now_ts - GRACE_SECONDS:
                continue
            best = found.get(label)
            if best is None or ts < best[0]:
                found[label] = (ts, event.delay)
    return found


def update_state(state, found, now_ts):
    """Apply one poll. found holds fresh departures; empty means no new data."""
    for d in state["directions"].values():
        if d["departure_ts"] is not None and d["departure_ts"] < now_ts - GRACE_SECONDS:
            d["departure_ts"] = d["delay_seconds"] = d["fresh_ts"] = None  # bus has gone
    for label, (ts, delay) in found.items():
        d = state["directions"][label]
        d["departure_ts"] = ts
        d["delay_seconds"] = delay
        d["fresh_ts"] = now_ts


def build_payload(state, now_ts):
    directions = {}
    for label, d in state["directions"].items():
        if d["departure_ts"] is None:
            directions[label] = {"departure_time": None, "delay_seconds": None, "age_seconds": None}
        else:
            directions[label] = {
                "departure_time": datetime.fromtimestamp(d["departure_ts"], AMS).isoformat(timespec="seconds"),
                "delay_seconds": d["delay_seconds"],
                "age_seconds": round(now_ts - d["fresh_ts"]),
            }
    feed_ts = state["feed_ts"]
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


def tick(feed, state):
    """One poll cycle. Failures count as an empty poll, and the payload is republished so ages keep moving."""
    now_ts = time.time()
    found = {}
    try:
        msg = feed.fetch()
        found = next_departures(msg, now_ts)
        state["feed_ts"] = msg.header.timestamp
    except Exception as err:  # keep serving the last known data; retry next round
        print(f"poll failed: {err}", file=sys.stderr, flush=True)
    update_state(state, found, now_ts)
    return publish(build_payload(state, now_ts))


def main():
    feed = Feed(user_agent(load_contact()))
    state = new_state()
    if "--once" in sys.argv:
        try:
            msg = feed.fetch()
        except Exception as err:
            print(f"poll failed: {err}", file=sys.stderr)
            sys.exit(1)
        now_ts = time.time()
        update_state(state, next_departures(msg, now_ts), now_ts)
        state["feed_ts"] = msg.header.timestamp
        print(publish(build_payload(state, now_ts)).decode("utf-8"))
        return

    start_server()
    while True:
        tick(feed, state)
        print("updated", datetime.now(AMS).isoformat(timespec="seconds"), flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
