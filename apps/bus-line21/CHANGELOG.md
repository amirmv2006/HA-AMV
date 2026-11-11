# Changelog

## 0.2.1

- Log each poll: feed timestamp and age, entity and line 21 trip counts, stop
  event counts per direction, and the departure stored for each direction.

## 0.2.0

- Expose the absolute departure time, delay and data age per direction instead
  of a precomputed minute count. Consumers calculate remaining time themselves,
  so values no longer go stale between polls.
- Keep the last known departure when a poll returns nothing, and reset all
  fields once the departure has passed.
- Only the next departure per direction is kept (previously two).
- Failed polls republish the payload so `age_seconds` keeps increasing.

## 0.1.3

- Serve the latest departures as JSON on port 8099 inside the Home Assistant
  network instead of writing a file. The app no longer needs `/media` or
  `/share`, which the unprivileged app user cannot write to.

## 0.1.1

- Write output to `/share/bus_line21.json` (mapped `share`, read-write) instead
  of `/media`, which is root-owned on Home Assistant OS.
- Accept an empty `contact_email` option.

## 0.1.0

- First version: poll OVapi trip updates, write `/media/bus_line21.json`.
