# Changelog

## 0.1.1

- Write output to `/share/bus_line21.json` (mapped `share`, read-write) instead
  of `/media`, which is root-owned on Home Assistant OS.
- Accept an empty `contact_email` option.

## 0.1.0

- First version: poll OVapi trip updates, write `/media/bus_line21.json`.
