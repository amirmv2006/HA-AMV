# Bus line 21 countdown

Polls the public GTFS-Realtime trip-updates feed from OVapi once a minute and
keeps the next two departures for GVB line 21 at Solebaystraat in both
directions. The result is served as JSON on the Home Assistant internal network
at `http://<app-hostname>:8099/bus_line21.json`. No host port is published, so
it is not reachable from outside Home Assistant.

The app hostname is shown on the app's Info tab (for example `9e519bb6-bus-line21`).

Example REST sensor:

```yaml
sensor:
  - platform: rest
    name: Bus line 21 next to Centraal
    resource: http://9e519bb6-bus-line21:8099/bus_line21.json
    scan_interval: 60
    value_template: >-
      {% set d = value_json.directions['Centraal Station'] %}
      {{ d[0].minutes if d else 'none' }}
```

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
