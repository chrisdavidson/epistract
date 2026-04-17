# Phase 13 Bug-4 Reproducer Fixture (24 files → 23 logical docs)

- 16 good files (good_01..good_16)
- 3 variant-filename files (variant_raw, weird_extraction_input, hyphen-extraction)
- 2 missing-document_id files (missing_id_alpha, missing_id_beta)
- 2 duplicate files for same doc_id (dupe_target + dupe_target_raw → 1 logical doc)
- 1 schema-drift file (drift_bad_field)

Post-normalize expectation: 23/23 recoverable (100% pass rate), above the 95% threshold.
