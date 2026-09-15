# Cross-strip Overlap Protection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure retained overlap between adjacent parallel flight strips and restore skipped photos whenever the retained set cannot preserve at least 70% side overlap that existed in the source set.

**Architecture:** Keep forward selection in `selection.py`, then run a second conservative pass in a focused `coverage.py` module. The pass derives a track frame for each eligible strip, finds physically intersecting partners on other parallel strips, restores a skipped partner when needed, and records original gaps separately rather than claiming they were repaired.

**Tech Stack:** Python 3.11 dataclasses, `pyproj.Geod`, standard-library `unittest`, existing JSON/CSV report pipeline.

## Global Constraints

- Default behavior remains unchanged unless `cross_strip_enabled` is true.
- Minimum retained side overlap is 0.70 in `config/xt701-dsm70-trial.json`.
- Same-line fragments closer than 5 m cross-track are not treated as separate strips.
- Photos more than 1,800 seconds apart cannot satisfy each other's side coverage.
- Missing geometry or an original side gap always retains the affected source photo.
- Global PASS is forbidden while any retained source photo remains outside the evaluated subset.
- No source photo is modified, moved, or deleted.
- Side-overlap PASS means metadata geometry only; it does not claim photogrammetric model validation.

---

### Task 1: Side-overlap geometry

**Files:**
- Create: `src/uav_photo_optimizer/coverage.py`
- Modify: `src/uav_photo_optimizer/config.py`
- Modify: `src/uav_photo_optimizer/metadata.py`
- Test: `tests/test_cross_strip.py`

**Interfaces:**
- Consumes: `Photo`, `Config`, `selection.distance()`, `selection.footprint()`.
- Produces: `StripFrame`, `strip_frame(strip, config)`, and `side_pair(a, b, frame_a, frame_b, config)` returning side and along overlap ratios or `None`.

- [x] **Step 1: Write failing geometry tests**

```python
def test_parallel_strips_measure_seventy_percent_side_overlap():
    a = [photo(i, i * 10, east=0) for i in range(3)]
    b = [photo(i + 10, i * 10, east=40) for i in range(3)]
    fa, fb = strip_frame(a, config()), strip_frame(b, config())
    side, along = side_pair(a[1], b[1], fa, fb, config())
    self.assertAlmostEqual(side, 0.70)
    self.assertGreater(along, 0)

def test_collinear_fragments_are_not_cross_strips():
    self.assertIsNone(side_pair(a[1], b[1], fa, fb, config(cross_strip_min_separation_m=5)))
```

- [x] **Step 2: Run tests and verify RED**

Run: `LC_ALL=en_US.UTF-8 PYTHONUTF8=1 .venv/bin/python -m unittest tests/test_cross_strip.py -v`

Expected: import failure because `uav_photo_optimizer.coverage` does not exist.

- [x] **Step 3: Implement the minimum geometry**

```python
@dataclass(frozen=True)
class StripFrame:
    strip_id: int
    bearing_deg: float
    image_axis_offset_deg: int

def interval_overlap(size_a, size_b, separation):
    intersection = max(0.0, min(size_a / 2, separation + size_b / 2)
                       - max(-size_a / 2, separation - size_b / 2))
    return intersection / max(size_a, size_b)
```

Add validated config fields `cross_strip_enabled=False`, `min_retained_side_overlap=0.70`, and `cross_strip_min_separation_m=5.0`. Add per-photo report fields for side status, partner, overlap, and restoration.

- [x] **Step 4: Run tests and verify GREEN**

Run the same unittest command; expect both tests to pass.

### Task 2: Cross-strip restoration and original-gap reporting

**Files:**
- Modify: `src/uav_photo_optimizer/coverage.py`
- Modify: `src/uav_photo_optimizer/selection.py`
- Test: `tests/test_cross_strip.py`

**Interfaces:**
- Consumes: eligible strips after `reduce_strip()`.
- Produces: `protect_cross_strip(strips, config) -> dict` with evaluated-link, restored-photo, pass, and original-gap counts.

- [x] **Step 1: Write failing behavioral tests**

```python
def test_skipped_partner_is_restored_for_side_coverage():
    result = protect_cross_strip([left, right], config(cross_strip_enabled=True))
    self.assertEqual(right_middle.decision, "KEEP")
    self.assertTrue(right_middle.cross_strip_restored)
    self.assertEqual(result["cross_strip_original_gap_count"], 0)

def test_original_side_gap_is_reported_without_fabricated_pass():
    result = protect_cross_strip([left, far_right], config(cross_strip_enabled=True))
    self.assertGreater(result["cross_strip_original_gap_count"], 0)
    self.assertEqual(left_middle.cross_strip_status, "ORIGINAL_GAP_OR_UNCERTAIN")
```

- [x] **Step 2: Run tests and verify RED**

Expected: `protect_cross_strip` is absent or does not restore/report as asserted.

- [x] **Step 3: Implement restoration pass**

For each retained photo, compute source-valid partners on other parallel strip frames. Prefer an already retained partner; otherwise restore the best skipped partner and mark `CROSS_STRIP_LINK_PROTECTION`. If no source-valid partner exists, keep the photo and mark `ORIGINAL_SIDE_GAP_OR_UNCERTAINTY`. Recompute forward retained-link fields after restorations.

- [x] **Step 4: Run focused and complete tests**

Run: `LC_ALL=en_US.UTF-8 PYTHONUTF8=1 .venv/bin/python -m unittest tests/test_cross_strip.py -v`

Run: `LC_ALL=en_US.UTF-8 PYTHONUTF8=1 .venv/bin/python -m unittest discover -s tests -v`

Expected: all tests pass and no prior selection behavior changes when cross-strip checking is disabled.

### Task 3: Reports, DSM trial, and real-data validation

**Files:**
- Modify: `src/uav_photo_optimizer/cli.py`
- Modify: `config/xt701-dsm70-trial.json`
- Modify: `README.md`
- Modify: `docs/design.md`
- Modify: `docs/validation.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: the dictionary returned by `protect_cross_strip()` and per-photo side fields.
- Produces: summary `side_overlap_status`, cross-strip counts, manifest evidence, and a new report-only real-data trial.

- [x] **Step 1: Write a failing summary integration test**

Assert that cross-strip-enabled CLI output contains `side_overlap_status`, `cross_strip_evaluated_link_count`, `cross_strip_restored_photo_count`, and `cross_strip_original_gap_count`.

- [x] **Step 2: Verify RED, then add summary fields and enable the 0.70 trial setting**

```json
"cross_strip_enabled": true,
"min_retained_side_overlap": 0.7,
"cross_strip_min_separation_m": 5.0
```

- [x] **Step 3: Run the real dataset in report-only mode**

Run the CLI against `../UserUpload-original` and the supplied DSM with a new output directory and without `--copy`. Confirm retained-link FAIL count is zero; report original side gaps explicitly if present.

- [x] **Step 4: Document evidence and limitations**

Record exact counts, thresholds, runtime, restoration count, and the distinction between metadata geometry and A/B modeling validation.

- [x] **Step 5: Final verification and commit**

Run `git diff --check`, dependency checks, compilation, full tests, and a local secret-pattern scan. Commit only source, tests, configs, plans, and docs; keep real-photo reports ignored.
