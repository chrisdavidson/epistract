# Epistract TODO

## Documentation
- [ ] Convert all ASCII art diagrams in README.md, DEVELOPER.md, and design specs to Mermaid diagrams (or render with `beautiful-mermaid` for SVG/ASCII output)
- [ ] Diagrams to convert:
  - [ ] DEVELOPER.md: main architecture diagram
  - [ ] docs/epistract-plugin-design.md: data flow pipeline diagram
  - [ ] docs/epistract-plugin-design.md: Claude-as-extractor adapter diagram
  - [ ] docs/drug-discovery-domain-spec.md: Central Dogma Chain
  - [ ] docs/drug-discovery-domain-spec.md: Protein Function Chain
  - [ ] docs/drug-discovery-domain-spec.md: Drug Action Chain
  - [ ] docs/drug-discovery-domain-spec.md: Hybrid Extraction Architecture (Phase 1/Phase 2)
  - [ ] docs/drug-discovery-domain-spec.md: Validation Pipeline system diagram

## Phase 1 — Extraction + KG + Visualization
- [ ] Implement plugin commands
- [ ] Implement drug-discovery-extraction skill (SKILL.md)
- [ ] Implement domain.yaml
- [ ] Implement extraction adapter scripts
- [ ] Implement molecular validation scripts
- [ ] Implement extractor and validator agents
- [ ] End-to-end test with real PubMed abstracts

## Phase 2 — Neo4j + Vector RAG
- [ ] Neo4j exporter
- [ ] Vector embeddings
- [ ] RAG query layer
- [ ] Production query commands
