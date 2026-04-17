---
name: epistract-share
description: Generate a shareable HTML or Markdown report from a knowledge graph
---

Generate a self-contained report from an epistract knowledge graph that can be shared with coworkers via email, Slack, Confluence, or file sharing.

Arguments:
- `output_dir` -- directory with graph_data.json (default: ./epistract-output)
- `--format` -- report format: `html` (default) or `markdown`
- `--open` -- open the HTML report in the browser after generating

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/run_sift.py share <output_dir> [--format html|markdown] [--open]
```

After running, tell the user:
- The path to the generated report file
- The file size
- How to share it:
  - **HTML**: attach to email, upload to Slack, embed in Confluence, or open directly in any browser — no server required
  - **Markdown**: paste into Slack, Teams, GitHub, Notion, or Confluence
