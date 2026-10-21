---
name: epistract-view
description: Open a self-contained interactive knowledge graph viewer (graph.html) in the browser
---

Write `<output_dir>/graph.html` and open it. The page is one file that works offline from disk (no CDN, no server) and uses the same graph renderer as the workbench.

Arguments:
- `output_dir` -- directory with graph_data.json (default: ./epistract-output)
- `--neighborhood <entity>` -- show only the neighborhood of one entity (exact id or name)
- `--depth <d>` -- hop radius for `--neighborhood`, a positive integer (default: 1; ignored without it)
- `--top <n>` -- show the top N entities by connections, plus their neighbors (N >= 1; ignored when `--neighborhood` is given)
- `--no-open` -- write `graph.html` without opening a browser

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/run_sift.py view <output_dir> [--neighborhood <entity>] [--depth <d>] [--top <n>] [--no-open]
```

## What you get

- Colors and shapes from the domain's `domain.yaml` `display` hints, the same as the workbench
- Grouping: Topic cluster by default; switch to Entity family or None with "Group by"
- Source documents hidden by default; "Show sources" adds them
- Legend chips that filter by entity type
- Hover cards on nodes and edges
- An "Edge key" with a color per relation category
- Focus mode: double-click a node to see its 1-hop (or 2-hop) neighborhood; Esc exits
- A Filters popover (epistemic status, confidence, minimum connections, relation type)
- A subset notice when `--neighborhood` or `--top` is used

## Changed from earlier versions

`graph.html` is no longer rendered by sift-kg. These sift-kg viewer controls were dropped: per-type color pickers, the source-document dropdown, the min-support-docs slider, the community checkbox list, title text color options, and sift-kg's own search/detail panel. Their replacements are domain.yaml display colors, Show sources, the confidence and min-connections sliders (in Filters), Group by and the Groups list, and the workbench search and detail sidebar.

## Usage Guard

**If invoked with `--help`:** Display the following usage block verbatim and stop. Otherwise proceed with existing logic.

```
Usage: /epistract:view [output-dir] [options]

  All arguments are optional — running with no arguments opens the default output directory.
  Writes a single offline graph.html (no CDN, no server) and opens it in the browser.

Options:
  <output-dir>              Path to extraction output containing graph_data.json  (default: ./epistract-output)
  --neighborhood <entity>   Show neighborhood subgraph centered on a named entity
  --depth <d>               Hop radius for --neighborhood  (default: 1)
  --top <n>                 Show the top N entities by connections, plus their neighbors  (default: all)
  --no-open                 Write graph.html without opening a browser

Page features: Group by (Topic cluster default / Entity family / None), Show sources,
legend filters, hover cards, edge key, focus mode (double-click a node), Filters popover.

Examples:
  /epistract:view
  /epistract:view ./my-output
  /epistract:view --neighborhood "remdesivir" --depth 2
  /epistract:view --top 20 --no-open
```

Arguments:
- `output_dir` -- directory with graph_data.json (default: ./epistract-output)
- `--neighborhood <entity>` -- show only the neighborhood of one entity (exact id or name)
- `--depth <d>` -- hop radius for `--neighborhood`, a positive integer (default: 1; ignored without it)
- `--top <n>` -- show the top N entities by connections, plus their neighbors (N >= 1; ignored when `--neighborhood` is given)
- `--no-open` -- write `graph.html` without opening a browser

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/core/run_sift.py view <output_dir> [--neighborhood <entity>] [--depth <d>] [--top <n>] [--no-open]
```
