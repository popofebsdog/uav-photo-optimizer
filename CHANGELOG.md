# Changelog

## 0.2.0 — 2026-09-11

- Added projected-DSM local slope/relief protection with provenance and SHA-256 reporting.
- Added explicitly experimental GPS-minus-DSM height mode; unconfirmed vertical datum is surfaced in every report.
- Added the XT701 flat-terrain 70% trial configuration and a separate unsafe GPS-altitude proxy comparison configuration.
- Protected height-change neighborhoods, hover motion, travel along either camera axis and the last safe bridge candidate.
- Expanded tests and recorded the 804-photo DSM trial; no real-photo modeling validation is claimed.

## 0.1.0 — 2026-09-10

- Independent local Python CLI with ExifTool scanning and pyproj geometry.
- Configurable 80% minimum retained forward overlap, threshold triggers and config snapshots.
- Conservative strip segmentation, deferred redundancy decisions and interval restoration.
- CSV/JSON reports and optional exclusive streaming copy preserving relative paths.
- Tests, real-data scan record and explicit unsupported-geometry/coverage status.
- Local Git structure; original photos, private reports and runtime environment excluded.
