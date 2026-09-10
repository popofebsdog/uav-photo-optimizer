# Local optimizer implementation

- [x] Inspect workspace; confirm independent tool requested and source photos external to repository.
- [x] Define Python src layout, configuration and conservative geometry contract.
- [x] Implement metadata scanning, segmentation, selection and copy/report CLI.
- [x] Verify 20 meaningful tests, 804-photo real scan and single-photo copy without inventing AGL.
- [x] Document limitations, usage and reproducible environment; prepare initial Git commit.

Initial minimum retained forward overlap: 0.80, configurable. Camera profiles and height evidence are explicit. No image decoding, deletion, upload or feature matching. Missing evidence retains original photos. Source photos and reports are not versioned.
