# Bus line 21 countdown

Polls the public GTFS-Realtime trip-updates feed from OVapi once a minute and
keeps the next two departures for GVB line 21 at Solebaystraat in both
directions. The result is written to `/share/bus_line21.json`, the folder Home
Assistant shares with apps.

## Options

- `contact_email` (optional): sent in the User-Agent header so OVapi can reach
  you if your polling causes a problem. Leave it empty to send a generic agent
  name. Use an address you are comfortable publishing to a third party.

## Output

```json
{
  "stop_name": "Solebaystraat",
  "route": "21",
  "updated": "2026-11-09T20:31:00",
  "feed_timestamp": "2026-11-09T20:30:45",
  "directions": {
    "Centraal Station": [
      {"time": "2026-11-09T20:32", "minutes": 1, "delay_seconds": 217}
    ],
    "Geuzenveld De Sav. Lohmanstraat": []
  }
}
```

`feed_timestamp` shows how old the upstream data is. An empty list means no
upcoming arrival in the feed.
