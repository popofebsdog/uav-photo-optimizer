# Validation — 2026-09-10

## Automated tests

Command: `LC_ALL=en_US.UTF-8 PYTHONUTF8=1 .venv/bin/python -m unittest discover -s tests -v`.

Covered: exact OR thresholds, 80% dense-strip selection, 60% override, A/B/C restoration, original low-overlap gaps, missing AGL, time boundaries, unknown-time stream bypass, turns, cross-track and oblique rejection, unequal footprints, invalid configuration, ExifTool fallback, date precision, per-image heights, duplicate relative filenames, source changes, exclusive outputs and report/copy CLI integration.

Version 0.2.0 additionally covers projected DSM validation and masking, Horn slope/relief, rough/missing terrain protection, explicit GPS-minus-DSM estimates, GPS-height-change protection, 70% selection, sideways flight, hover noise and last-safe-candidate restoration.

Current release result: 52 tests passed, including repeated-mission isolation, global false-PASS prevention, conservative spatial pruning, cross-strip restoration, asymmetric geoid interpolation, converter orientation, pinned hashes, datum/GPS-height-reference validation and fail-closed behavior, ExifTool timeout and vendor-field normalization tests.

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

## Forward + cross-strip 70% trial — 2026-09-11

Version 0.3.0 used `GPSAltitude - DSM center elevation` per photo, the explicit moderate 15°/20 m DSM terrain policy, 70% minimum forward overlap, 70% minimum side overlap and a 30-minute cross-strip task window. Report-only output is under `outputs/dsm70-cross70-moderate-008/`.

- 804 input photos; 720 selected and 84 marked `SKIP`.
- 1,994,259,706 bytes marked skippable: 10.448% of photos and 8.849% of storage.
- Terrain classification: 281 `GENTLE`, 521 `ROUGH`, 2 `OUTSIDE_OR_EDGE`.
- 24 eligible strip fragments; 121 initial excessive-forward-overlap candidates.
- Cross-strip protection restored 37 candidates: 1 direct partner and 36 because a related strip contained an unpairable retained point.
- 64 unique retained cross-strip links were evaluated; 75 retained points recorded a side-overlap PASS.
- No original below-threshold side partner was detected. Twenty-three retained points remained `UNPAIRED_OR_UNCERTAIN`; their related candidate photos were restored rather than treated as safe removals.
- Another 622 retained photos were outside the geometry-eligible cross-strip subset, so the global side status correctly remains `GAPS_OR_UNCERTAINTY`; it is not presented as full-dataset PASS.
- All 74 evaluated retained forward links passed 70%; zero forward FAIL links remained.
- All 84 remaining `SKIP` candidates belong to nine strips whose 28 retained anchors have side-overlap PASS. Within those strips, the minimum recorded side overlap is 76.234% and minimum retained forward overlap is 70.029%.
- `cross_strip_reduction_subset_status` is `PASS`; the global and reduction-subset states are deliberately separate.
- Analysis took 7.087 seconds on this machine. Copy was not requested and source photos were unchanged.

The original 10°/10 m terrain policy was also rerun without changing its safety thresholds: 796 selected, 8 marked `SKIP`, 164,233,624 bytes marked skippable, 13 cross-strip restorations, and a `PASS` reduction subset of four retained anchors. Its report is under `outputs/dsm70-cross70-conservative-008/`. The 15°/20 m result is therefore a separate moderate policy trial, not a silent relaxation of the original config.

A 1,000-photo synthetic benchmark with 20 parallel strips measured 1.299 seconds before strip/time/spatial pruning and 0.417 seconds after on this machine. This is a local measurement, not a portable performance guarantee.

This is metadata geometry validation, not footprint-wide terrain projection, image matching, or Metashape A/B modeling. The unconfirmed GPS/DSM vertical-datum compatibility remains the principal modeling limitation.

## Adaptive uncertainty handling — 2026-09-15

Version 0.4.0 reran the same 804-photo moderate 15°/20 m, forward 70%, side 70% configuration. The only selection change was to stop restoring every forward-overlap candidate on a strip merely because the source data had no verifiable side partner. A skipped photo is still restored when it was an originally valid side partner and its removal would break that retained metadata link. Report-only output is under `outputs/dsm70-cross70-moderate-009/`.

- 804 input photos; 684 selected and 120 marked `SKIP`.
- 2,853,881,153 bytes marked skippable: 14.925% of photos and 12.664% of storage, up from 10.448% and 8.849% respectively.
- Cross-strip restoration fell from 37 to 1: the one deletion-induced partner loss was still repaired; the other 36 were original pairing uncertainty and no longer cancelled safe forward reduction.
- All 38 evaluated retained forward links passed; minimum recorded forward overlap was 70.029%.
- Forty-five retained points had a cross-strip `PASS`; minimum recorded side overlap among them was 70.130%.
- Global and reduction-subset side states remain `GAPS_OR_UNCERTAINTY`, not `PASS`, because original/bypassed coverage remains unverified.
- The geometry-eligible subset contained 182 photos; the adaptive selector retained 62 and skipped 120 (65.934% reduction). Simple alternating selection within each eligible strip would retain 98 and skip 84, so the adaptive spacing is already more aggressive than odd/even selection where geometry is trustworthy.
- Alternating the complete capture-time sequence would retain 402 of 804 photos. That 50% count is recorded only as the user-provided modeling comparison baseline; it crosses 622 protected rough-terrain, DSM-unavailable or nadir-uncertain photos and is not certified by this metadata-only run.
- Manifest counts, byte totals and `selected-files.json` were independently cross-checked against the summary. Copy was not requested and source photos were unchanged.

The remaining gap between 684 selected photos and the 402-photo empirical baseline is therefore dominated by evidence eligibility, not by the adaptive forward-spacing rule. Relaxing that boundary would require an explicit dataset-specific validated override or image/model-quality evidence; it must not become a default for other missions.

## TWVD2001-corrected height run — 2026-09-15

Version 0.5.0 adds `gps_geoid_dsm`: `H = h - N`, followed by `AGL = H - H_DSM`. The supplied 20 m DSM is explicitly declared TWVD2001 based on its official catalog metadata; because the GeoTIFF itself contains no vertical CRS, the report preserves this as a declaration rather than claiming an embedded-datum check. The geoid input was converted from QPS's public TWHyGEO2014 pre-release redistribution; it is not described as the official NLSC original.

- QPS source ZIP SHA-256: `2bbdc5e1684a17e9b74448c6e0686b1cd4a17dfdc19bc3fda0019fb33563f249`; converted GeoTIFF SHA-256: `ae97de21c4601d81a7223ba57ef95fb63e4a366f518e113889ebd6a99b82b223`.
- 802 photos had usable geoid samples; the two invalid `(0,0)` GPS coordinates were outside both DSM and geoid coverage and remained protected.
- Geoid undulation ranged from 23.0813 m to 24.3628 m, averaging 23.4530 m. Corrected AGL ranged from 6.2504 m to 143.4216 m, averaging 55.8186 m.
- 804 input photos; 707 selected and 97 marked `SKIP`; 2,301,586,100 bytes marked skippable: 12.065% of photos and 10.213% of storage.
- The geometry-eligible subset remained 182 photos: 85 retained and 97 skipped. Cross-strip protection restored two candidates.
- Fifty-three retained forward links passed, with minimum confirmed overlap 70.635%. Four original retained links were below 70%; no photos were skipped across those original gaps, which remain explicitly reported as `ORIGINAL_LINK_GAP_OR_UNCERTAINTY`.
- Forty retained points had cross-strip `PASS`; minimum confirmed side overlap was 70.098%. Forty-five eligible retained points remained unpaired or uncertain. Global and reduction-subset status therefore remain `GAPS_OR_UNCERTAINTY`, not a fabricated PASS.
- Relative to the uncorrected v0.4.0 run, the corrected footprint height is lower by the local `N` (23.4530 m mean). The selector consequently keeps 23 more photos and marks 552,295,053 fewer bytes skippable.
- Report-only output is under `outputs/dsm70-cross70-moderate-twvd2001-005/`; no copy was requested and source photos were unchanged.

This removes the known ellipsoidal-versus-orthometric subtraction error. It still does not provide image matching, footprint-wide terrain/occlusion projection or Metashape A/B quality validation, so `SKIP` remains a modeling candidate rather than permission to delete originals.
