# Bus line 21 countdown

Polls the public GTFS-Realtime trip-updates feed from OVapi once a minute and
keeps the next departure for GVB line 21 at Solebaystraat in both directions.
The result is served as JSON on the Home Assistant internal network at
`http://<app-hostname>:8099/bus_line21.json`. No host port is published, so it
is not reachable from outside Home Assistant.

The app hostname is shown on the app's Info tab (for example `9e519bb6-bus-line21`).

## Output fields

For each direction the app exposes:

- `departure_time`: when the bus leaves Solebaystraat (ISO time with offset), or `null`.
- `delay_seconds`: the delay reported for that departure, or `null`.
- `age_seconds`: seconds since the feed last returned this departure, or `null`.

If a poll returns nothing for a direction, the last departure is kept and its
`age_seconds` grows. Once `departure_time` has passed, all three fields become
`null` until the feed returns a new departure. The app does not calculate
remaining minutes; the consumer does that.

## Example REST sensor

```yaml
rest:
  - resource: http://9e519bb6-bus-line21:8099/bus_line21.json
    scan_interval: 60
    sensor:
      - name: "Bus line 21 next to Centraal"
        value_template: "{% set d = value_json.directions['Centraal Station'] %}{% set m = (((as_datetime(d.departure_time) - now()).total_seconds() / 60) | round(0) | int) if d.departure_time else -1 %}{{ m if m >= 0 else 'none' }}"
```

## Options

- `contact_email` (optional): sent in the User-Agent header so OVapi can reach
  you if your polling causes a problem. Leave it empty to send a generic agent
  name. Use an address you are comfortable publishing to a third party.

## Output example

```json
{
  "stop_name": "Solebaystraat",
  "route": "21",
  "updated": "2026-11-10T20:31:00+01:00",
  "feed_timestamp": "2026-11-10T20:30:45+01:00",
  "directions": {
    "Centraal Station": {
      "departure_time": "2026-11-10T20:32:17+01:00",
      "delay_seconds": 217,
      "age_seconds": 0
    },
    "Geuzenveld De Sav. Lohmanstraat": {
      "departure_time": null,
      "delay_seconds": null,
      "age_seconds": null
    }
  }
}
```

`feed_timestamp` shows how old the upstream data is. `updated` is the time of
the last poll.
