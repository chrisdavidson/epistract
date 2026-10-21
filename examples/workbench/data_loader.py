"""In-memory data store for pre-extracted KG data."""

from __future__ import annotations

import json
from pathlib import Path


class WorkbenchData:
    """Load and hold all extraction pipeline output in memory."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.graph_data: dict = {}
        self.claims_layer: dict = {}
        self.communities: dict = {}
        self.documents: list[dict] = []
        self.ingested_dir = output_dir / "ingested"
        self.corpus_dir: Path | None = None
        # doc_id -> original PDF, resolved once at load time. The has_pdf flag
        # and /api/sources/pdf/{doc_id} both read this map, so they always agree.
        self.pdf_paths: dict[str, Path] = {}
        self.load()

    def load(self):
        """Load JSON artifacts from output directory."""
        gp = self.output_dir / "graph_data.json"
        if gp.exists():
            self.graph_data = json.loads(gp.read_text(encoding="utf-8"))

        cp = self.output_dir / "claims_layer.json"
        if cp.exists():
            claims = json.loads(cp.read_text(encoding="utf-8"))
            # Consumers call .get() on it: a list, string or null counts as absent.
            self.claims_layer = claims if isinstance(claims, dict) else {}

        cm = self.output_dir / "communities.json"
        if cm.exists():
            self.communities = json.loads(cm.read_text(encoding="utf-8"))

        # Load triage.json for original filenames
        triage_map: dict[str, dict] = {}
        triage_path = self.output_dir / "triage.json"
        if triage_path.exists():
            triage = json.loads(triage_path.read_text(encoding="utf-8"))
            for doc in triage.get("documents", []):
                triage_map[doc.get("doc_id", "")] = doc
            if triage.get("documents"):
                fp = triage["documents"][0].get("file_path", "")
                if fp:
                    self.corpus_dir = self._resolve_recorded(fp).parent

        # Build document list from ingested/ directory
        if self.ingested_dir.exists():
            for txt_file in sorted(self.ingested_dir.glob("*.txt")):
                doc_id = txt_file.stem
                triage_info = triage_map.get(doc_id, {})
                original_path = triage_info.get("file_path", "")
                original_name = (
                    Path(original_path).name if original_path else txt_file.name
                )
                self.documents.append(
                    {
                        "doc_id": doc_id,
                        "filename": original_name,
                        "display_name": original_name.rsplit(".", 1)[0]
                        if original_name
                        else doc_id,
                        "original_path": original_path,
                        "size_bytes": txt_file.stat().st_size,
                        "original_size": triage_info.get(
                            "chars", txt_file.stat().st_size
                        ),
                        # The ingested .txt exists by construction.
                        "has_text": True,
                        "has_pdf": self._register_pdf(doc_id, triage_info),
                    }
                )

    def _resolve_recorded(self, recorded: str) -> Path:
        """Resolve a path recorded in triage.json.

        Relative paths are taken relative to the output directory, never the
        server's working directory, so the result does not depend on where the
        workbench was launched from.
        """
        path = Path(recorded)
        return path if path.is_absolute() else self.output_dir / path

    def resolve_pdf(self, doc_id: str, triage_info: dict) -> Path | None:
        """Find the original PDF of a document without walking the corpus tree.

        The single resolver behind both ``has_pdf`` and the PDF endpoint: the
        path recorded in triage.json (``file_path``, else ``original_path``) if
        it is a PDF that exists, otherwise ``<doc_id>.pdf`` directly in the
        corpus directory.
        """
        if not doc_id or ".." in doc_id or "/" in doc_id or "\\" in doc_id:
            return None
        for key in ("file_path", "original_path"):
            recorded = triage_info.get(key)
            if isinstance(recorded, str) and recorded.lower().endswith(".pdf"):
                try:
                    candidate = self._resolve_recorded(recorded)
                    if candidate.is_file():
                        return candidate
                except OSError:
                    pass
        if self.corpus_dir is None:
            return None
        candidate = self.corpus_dir / f"{doc_id}.pdf"
        try:
            return candidate if candidate.is_file() else None
        except OSError:
            return None

    def _register_pdf(self, doc_id: str, triage_info: dict) -> bool:
        """Resolve a document's PDF, remember it for the endpoint, return has_pdf."""
        pdf = self.resolve_pdf(doc_id, triage_info)
        if pdf is None:
            return False
        self.pdf_paths[doc_id] = pdf
        return True

    def get_nodes(self, entity_type: str | None = None) -> list[dict]:
        """Return graph nodes, optionally filtered by entity_type."""
        nodes = self.graph_data.get("nodes", [])
        if entity_type:
            nodes = [n for n in nodes if n.get("entity_type") == entity_type.upper()]
        return nodes

    def get_edges(self) -> list[dict]:
        """Return all graph edges (sift-kg uses 'links' key)."""
        return self.graph_data.get("links", self.graph_data.get("edges", []))

    def get_node_by_id(self, node_id: str) -> dict | None:
        """Find a specific node by its ID."""
        for node in self.graph_data.get("nodes", []):
            if node.get("id") == node_id:
                return node
        return None

    def get_document_text(self, doc_id: str) -> str | None:
        """Read ingested text for a document.

        Returns None if doc_id is empty, contains traversal markers, or resolves
        outside ingested_dir. Defense-in-depth: a string-level reject (`..`, `/`,
        `\\`) catches the obvious cases; a `Path.resolve().relative_to()` check
        catches edge cases like symlinks and URL-encoded equivalents.
        """
        if not doc_id or ".." in doc_id or "/" in doc_id or "\\" in doc_id:
            return None
        txt_path = self.ingested_dir / f"{doc_id}.txt"
        try:
            txt_path.resolve().relative_to(self.ingested_dir.resolve())
        except ValueError:
            return None
        if txt_path.exists():
            return txt_path.read_text(encoding="utf-8")
        return None

    def get_document_pdf_path(self, doc_id: str) -> Path | None:
        """Return the original PDF of a listed document, or None.

        Served from the map filled at load time by ``resolve_pdf``, so the
        endpoint returns a PDF exactly when the document's ``has_pdf`` is true.
        The traversal guard matches get_document_text.
        """
        if not doc_id or ".." in doc_id or "/" in doc_id or "\\" in doc_id:
            return None
        return self.pdf_paths.get(doc_id)
