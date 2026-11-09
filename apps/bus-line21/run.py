"""Fetch GVB line 21 departures at Solebaystraat from OVapi and write them to JSON.

Output (default /share/bus_line21.json) is rewritten after every poll so that
Home Assistant can read it from its own /share folder.
"""
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
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
OPTIONS_PATH = os.environ.get("BUS_OPTIONS", "/data/options.json")
OUTPUT_PATH = os.environ.get("BUS_OUTPUT", "/share/bus_line21.json")
AMS = ZoneInfo("Europe/Amsterdam")


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


def write_output(directions, now_ts, feed_ts):
    payload = {
        "stop_name": STOP_NAME,
        "route": "21",
        "updated": datetime.fromtimestamp(now_ts, AMS).isoformat(timespec="seconds"),
        "feed_timestamp": datetime.fromtimestamp(feed_ts, AMS).isoformat(timespec="seconds") if feed_ts else None,
        "directions": directions,
    }
    tmp = OUTPUT_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, OUTPUT_PATH)


def poll_once(feed):
    msg = feed.fetch()
    now_ts = time.time()
    write_output(departures(msg, now_ts), now_ts, msg.header.timestamp)


def main():
    feed = Feed(user_agent(load_contact()))
    once = "--once" in sys.argv
    while True:
        try:
            poll_once(feed)
            print("wrote", OUTPUT_PATH, flush=True)
        except Exception as err:  # keep the last good file; log and retry
            print(f"poll failed: {err}", file=sys.stderr, flush=True)
            if once:
                sys.exit(1)
        if once:
            return
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
