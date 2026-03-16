---
name: epistract-build
description: Build knowledge graph from existing epistract extractions
---

Build the knowledge graph from extraction JSONs already in the output directory.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/run_sift.py build <output_dir> --domain ${CLAUDE_PLUGIN_ROOT}/skills/drug-discovery-extraction/domain.yaml
```

Report the entity count, relation count, and communities detected.
