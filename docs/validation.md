# Validation — 2026-09-10

## Automated tests

Command: `LC_ALL=en_US.UTF-8 PYTHONUTF8=1 .venv/bin/python -m unittest discover -s tests -v`.

Covered: exact OR thresholds, 80% dense-strip selection, 60% override, A/B/C restoration, original low-overlap gaps, missing AGL, time boundaries, unknown-time stream bypass, turns, cross-track and oblique rejection, unequal footprints, invalid configuration, ExifTool fallback, date precision, per-image heights, duplicate relative filenames, source changes, exclusive outputs and report/copy CLI integration.

Version 0.2.0 additionally covers projected DSM validation and masking, Horn slope/relief, rough/missing terrain protection, explicit GPS-minus-DSM estimates, GPS-height-change protection, 70% selection, sideways flight, hover noise and last-safe-candidate restoration.

Result: 33 tests passed, including ExifTool timeout and vendor-field normalization tests.

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

## DSM flat-terrain 70% trial — 2026-09-11

Command used `config/xt701-dsm70-trial.json`, the supplied 20 m Taiwan DSM, `--force`, and report-only mode. The DSM is a 10,173×19,081 projected metre grid; its captured SHA-256 is `1b594ebcf3e2169fee0acbf4c883945cc93343235091ec2ee2fc6ec13019b6d0`.

- 804 input photos; 797 selected and 7 marked `SKIP`.
- 160,480,476 bytes marked skippable: 0.871% of photos and 0.712% of storage.
- Terrain classification: 57 `GENTLE`, 745 `ROUGH`, 2 `OUTSIDE_OR_EDGE`.
- Protections: 745 terrain-change, 35 GPS/DSM-height-change, 4 nadir-geometry, and 2 DSM-unavailable reason occurrences.
- Six eligible strips; five evaluated retained links, all `PASS`; no bridge restoration was needed.
- Analysis took 6.126 seconds on this machine. Copy was not requested; the source was unchanged.
- Skipped candidates: `MAX_20112.JPG`, `MAX_20113.JPG`, `MAX_20345.JPG`, `MAX_20462.JPG`, `MAX_20473.JPG`, `MAX_20474.JPG`, `MAX_20475.JPG`.

The estimated geometry heights of those candidates range from 66.35 m to 150.91 m, using `GPSAltitude - DSM center elevation`. The source XMP identifies its vertical reference as ellipsoidal, but the supplied DSM contains no confirmed vertical CRS. The report therefore classifies this run as `EXPERIMENTAL_GPS_MINUS_DSM_UNCONFIRMED_VERTICAL_DATUM`. These seven decisions are candidates for inspection/A-B modeling, not authorization to delete originals.

An earlier GPS-altitude-proxy run marked 11 photos skippable, but it used absolute GPS elevation directly as footprint height and overstated the usable footprint. It is retained only as a comparison artifact and is not the accepted trial result.
