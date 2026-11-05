# Design decisions — 0.6.0

Source specification: parent-folder UDAS VibePrompt and section 71 of the modeling-link supplement. User approved an independent local tool and a configurable initial minimum retained forward overlap of 80%.

1. ExifTool handles EXIF/XMP parsing; pyproj.Geod handles WGS84 distance and bearing. No pixel decoding or feature matching.
2. Height is explicit per-image AGL evidence, not an alias for vendor relative altitude. Empty camera profiles intentionally retain images until actual sensor dimensions are confirmed.
3. Segmentation precedes last-kept reduction. Invalid geometry splits sequences; each segment's endpoints are kept. Missing timestamps retain the associated camera stream.
4. Candidates are deferred until the next anchor. A safe pair commits candidates to SKIP; unsafe/unknown pairs restore all pending candidates. Final retained links are independently recorded. Original gaps remain marked, not hidden.
5. Forward reduction is O(n) after O(n log n) sorting. Cross-strip comparisons are pruned by strip metadata and spatial envelopes but remain O(n²) in the worst case. Reports are O(n); file bytes stream in 1 MiB blocks only when copying.
6. Output is exclusive, outside input, and never deletes photos. User-selected config and overrides are captured. Invalid CLI configuration stops before producing a selection rather than silently changing policy.
7. Version scope excludes GUI, UDAS integration, image-content matching and real modeling validation. Version 0.4.0 restores a skipped cross-strip partner only when an originally valid metadata link was lost; original side uncertainty is reported without cancelling an otherwise safe forward reduction. Footprint-wide terrain/occlusion coverage remains explicitly unsupported.

## DSM trial extension

8. A projected metre-unit DSM may act as a local terrain gate. Horn slope and relief are computed from the 3×3 cell neighborhood; rough, missing and outside cells retain the photo. The check is deliberately local and does not claim footprint-wide coverage.
9. `gps_minus_dsm_trial` estimates geometry height as GPS altitude minus the DSM center elevation. It never writes this estimate into the measured `agl_m` field. The report labels the vertical datum as unconfirmed and the result as experimental.
10. A bounded five-image stability diagnostic is recorded for trial modes. Only the legacy GPS-altitude proxy uses it as a selection protection; GPS-minus-DSM mode uses per-photo variable footprints instead.
11. Travel along either principal image axis is supported. Sub-two-metre hover motion uses a conservative square footprint to avoid unstable GPS bearings. Unsafe deferred runs may retain the last candidate as a bridge, and every retained link is rechecked.

## Cross-strip extension

12. In `gps_minus_dsm_trial`, height change is represented by each photo's own footprint instead of acting as an automatic bypass. Non-positive or unavailable estimates still retain the photo.
13. A strip frame is derived from its first stable movement and matched only to a different, approximately parallel frame from the same configurable 30-minute task window. Cross-track separation below 5 m is treated as the same flight line, not side coverage; repeated surveys cannot satisfy each other's coverage.
14. A side partner must meet both retained forward-overlap alignment and the configured side-overlap floor. If forward reduction removes every qualifying partner of a retained photo, the best skipped partner is restored. A retained point with no qualifying source partner remains explicitly uncertain without cancelling the strip's otherwise safe forward reduction.
15. Cross-strip checks use metadata rectangles on a local flat-plane approximation and run only on geometry-eligible strips. Rough-terrain and other bypass-retained photos are not promoted to a geometric PASS.
16. The global side status cannot be PASS while any retained photo is outside the evaluated subset. A separate reduction-subset status reports whether every retained anchor on strips that still contain skipped candidates passed side coverage.
17. Strip time, camera identity, heading and conservative expanded spatial envelopes prune impossible comparisons before photo-pair geometry. Shared geodesic helpers live in `geometry.py`, avoiding a selection/coverage import cycle.

## TWVD2001 height conversion

18. `gps_geoid_dsm` computes `H = h - N` and `AGL = H - DSM`. GPS coordinates are transformed from WGS84 to the TWD97 horizontal datum of the geoid grid before bilinear point-grid interpolation.
19. A geoid GeoTIFF is accepted only when its full-file SHA-256 matches the config and its tags explicitly identify TWVD2001, metre units, `N = h - H`, point-pixel semantics and source provenance. Grid mismatch is a run error; per-photo missing/outside values, unconfirmed ellipsoidal GPS-height semantics and non-positive AGL retain that photo.
20. The DSM vertical datum is an explicit config declaration because the supplied GeoTIFF has no encoded vertical CRS. The report records that limitation, both raster hashes, the redistributed archive hash, source URL and applied formula.
21. The included converter targets QPS's public pre-release redistribution and does not claim that file is the official NLSC original. Its LLDLLD grid is written as a north-up EPSG:3824 point grid without altering values.

## Geometry and restoration corrections

22. Tilted photos are retained even within the legacy near-nadir tolerance. Only metadata pitch of -90° (floating-point epsilon) is eligible until full pose projection is supported; roll and lens distortion are not modeled.
23. Photo pairs use a symmetric common camera-axis direction. Yaw differences uniformly shrink each rectangle until its corners fit in the original rotated footprint; the original nominal dimensions remain the overlap denominator. Hover geometry uses the same shrinkage and full displacement on both axes.
24. Strip iteration is sorted by stable strip identity, and equal-score partners are selected by photo identity. Pair separation uses a canonical geodesic direction, so reversing a pair or the strip processing order does not change its geometry or decisions.
25. Side restoration and forward-link repair repeat until no additional forward photos are restored. Each step only changes SKIP to KEEP, guaranteeing termination. A failing non-consecutive retained link restores its original intermediate photos; only failing original consecutive links are classified as original gaps. Side statuses and restoration totals reflect the final retained set.

## Opt-in graded terrain policy

26. Existing configurations default to `terrain_policy=strict`; local terrain above the original gentle thresholds still bypasses reduction. The graded trial explicitly admits WARNING terrain up to separate hard slope/relief ceilings, without changing GENTLE classification or the sampled height.
27. The included graded 50% trial uses 15°/20 m gentle limits and 30°/40 m hard ceilings. Either hard-limit violation remains ROUGH and retained; missing samples, invalid corrected heights and unsupported pose remain protected. Hard ceilings cannot be below gentle limits.
28. WARNING is an experimental permission to continue the other geometry checks, not a claim of a flat surface or model quality. Manifest reasons and Summary warning selected/skipped counts preserve this distinction; the same local flat-plane approximation and its terrain/occlusion limitations still apply.

## Upstream documentation

- https://data.gov.tw/dataset/169808
- https://www.nlsc.gov.tw/cp.aspx?n=1483
- https://www.nlsc.gov.tw/cp.aspx?n=1551
- https://qpssoftware.scrollhelp.site/geodeticui/download-pre-released-vertical-models
- https://exiftool.org/TagNames/DJI.html
- https://exiftool.org/TagNames/XMP.html
- https://pyproj4.github.io/pyproj/stable/api/geod.html
- https://developer.dji.com/onboard-sdk/documentation/guides/component-guide-altitude.html

Manufacturer-specific angle conventions and height semantics require confirmation per camera. Vendor tags are retained as evidence; their names alone are insufficient validation.
