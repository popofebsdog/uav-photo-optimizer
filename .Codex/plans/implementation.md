# Local optimizer implementation

- [x] Inspect workspace; confirm independent tool requested and source photos external to repository.
- [x] Define Python src layout, configuration and conservative geometry contract.
- [x] Implement metadata scanning, segmentation, selection and copy/report CLI.
- [x] Verify 20 meaningful tests, 804-photo real scan and single-photo copy without inventing AGL.
- [x] Document limitations, usage and reproducible environment; prepare initial Git commit.
- [x] Add a conservative DSM terrain gate and explicit XT701 angle/profile trial.
- [x] Replace the unsafe GPS-altitude footprint trial with GPS-minus-DSM experimental geometry.
- [x] Validate flat-terrain 70% behavior with synthetic tests and the 804-photo dataset.
- [ ] Confirm GPS/DSM vertical-datum compatibility and perform original-vs-selected photogrammetry A/B validation.

Initial minimum retained forward overlap: 0.80, configurable. Camera profiles and height evidence are explicit. No image decoding, deletion, upload or feature matching. Missing evidence retains original photos. Source photos and reports are not versioned.
