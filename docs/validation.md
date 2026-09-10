# Validation — 2026-09-10

## Automated tests

Command: `LC_ALL=en_US.UTF-8 PYTHONUTF8=1 .venv/bin/python -m unittest discover -s tests -v`.

Covered: exact OR thresholds, 80% dense-strip selection, 60% override, A/B/C restoration, original low-overlap gaps, missing AGL, time boundaries, unknown-time stream bypass, turns, cross-track and oblique rejection, unequal footprints, invalid configuration, ExifTool fallback, date precision, per-image heights, duplicate relative filenames, source changes, exclusive outputs and report/copy CLI integration.

Result: 20 tests passed, including ExifTool timeout and vendor-field normalization tests.

Synthetic geometry tests are deterministic; they do not establish real photogrammetric quality.

## Real-photo scan

Input: existing user photo directory outside the Git repository. Reports are ignored local files under `outputs/real-scan-001/`.

- Supported images: 804.
- Total bytes: 22,535,655,779 (22.54 decimal GB).
- ExifTool version: 13.55.
- Analysis duration: 7.868 seconds on this machine; not a portable performance guarantee.
- All 804 retained with HEIGHT_REFERENCE_UNCERTAIN; 0 skipped.
- Copy was not requested for the full 22.54 GB batch.
- One real image was separately copied with the CLI; source and destination bytes were independently compared by SHA-256. Local smoke-test input/output copies remain under ignored data/ and outputs/.
- Minimum retained overlap recorded as 0.80.

Observed sample camera: Autel XT701, 8000×6000, focal length 4.74 mm. Vendor XMP has Pitch/Yaw and AboveGroundAltitude; the latter closely matches GPS altitude and VertCS is ellipsoidal. These observations do not establish AGL semantics or validated sensor size. No camera profile or height was invented.

## Outstanding validation boundaries

Actual photo reduction on this dataset requires trusted height data, camera sensor dimensions and camera-angle conventions. Cross-strip overlap/coverage checks and A/B Metashape modeling are not implemented/performed in this release. Reports explicitly mark these states. Source images are never edited or deleted by the application.
