# Design decisions — 0.2.0

Source specification: parent-folder UDAS VibePrompt and section 71 of the modeling-link supplement. User approved an independent local tool and a configurable initial minimum retained forward overlap of 80%.

1. ExifTool handles EXIF/XMP parsing; pyproj.Geod handles WGS84 distance and bearing. No pixel decoding or feature matching.
2. Height is explicit per-image AGL evidence, not an alias for vendor relative altitude. Empty camera profiles intentionally retain images until actual sensor dimensions are confirmed.
3. Segmentation precedes last-kept reduction. Invalid geometry splits sequences; each segment's endpoints are kept. Missing timestamps retain the associated camera stream.
4. Candidates are deferred until the next anchor. A safe pair commits candidates to SKIP; unsafe/unknown pairs restore all pending candidates. Final retained links are independently recorded. Original gaps remain marked, not hidden.
5. Reduction is O(n) after O(n log n) sorting. Reports are O(n); file bytes stream in 1 MiB blocks only when copying.
6. Output is exclusive, outside input, and never deletes photos. User-selected config and overrides are captured. Invalid CLI configuration stops before producing a selection rather than silently changing policy.
7. Version scope excludes cross-strip coverage safety, GUI, UDAS integration and real modeling validation. These are explicitly reported rather than fabricated.

## DSM trial extension

8. A projected metre-unit DSM may act as a local terrain gate. Horn slope and relief are computed from the 3×3 cell neighborhood; rough, missing and outside cells retain the photo. The check is deliberately local and does not claim footprint-wide coverage.
9. `gps_minus_dsm_trial` estimates geometry height as GPS altitude minus the DSM center elevation. It never writes this estimate into the measured `agl_m` field. The report labels the vertical datum as unconfirmed and the result as experimental.
10. GPS/DSM height stability is checked over adjacent images and a bounded five-image time window. Height-change regions split selection strips and remain retained.
11. Travel along either principal image axis is supported. Sub-two-metre hover motion uses a conservative square footprint to avoid unstable GPS bearings. Unsafe deferred runs may retain the last candidate as a bridge, and every retained link is rechecked.

## Upstream documentation

- https://exiftool.org/TagNames/DJI.html
- https://exiftool.org/TagNames/XMP.html
- https://pyproj4.github.io/pyproj/stable/api/geod.html
- https://developer.dji.com/onboard-sdk/documentation/guides/component-guide-altitude.html

Manufacturer-specific angle conventions and height semantics require confirmation per camera. Vendor tags are retained as evidence; their names alone are insufficient validation.
