"""
Domain Ontology loader and fuzzy entity matcher.

FR-39: Load ontology from docs/ontology.json at startup.
FR-40a/b: Ontology contains canonical names, types, and alias lists.
FR-41a: Match extracted entities against ontology via fuzzy match.
FR-41b: Only create a new Neo4j node if no canonical match is found.
"""

from __future__ import annotations

import difflib
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_ONTOLOGY_PATH = Path(__file__).parent.parent.parent / "docs" / "ontology.json"
_FUZZY_THRESHOLD = 0.75  # minimum SequenceMatcher ratio to accept a match


@dataclass(frozen=True)
class OntologyEntry:
    canonical: str
    type: str
    aliases: tuple[str, ...]

    @property
    def all_names(self) -> tuple[str, ...]:
        """All lower-cased names (canonical + aliases) for matching."""
        return (self.canonical.lower(),) + tuple(a.lower() for a in self.aliases)


class Ontology:
    """In-memory ontology with fuzzy canonical lookup.

    Usage:
        ontology = load_ontology()
        canonical = ontology.resolve("тимлид")  # → "Tech Lead"
        canonical = ontology.resolve("unknown term")  # → None (new node needed)
    """

    def __init__(self, entries: list[OntologyEntry]) -> None:
        self._entries = entries
        # Flat index: lower-cased alias → entry (exact lookup first)
        self._exact: dict[str, OntologyEntry] = {}
        for entry in entries:
            for name in entry.all_names:
                if name not in self._exact:
                    self._exact[name] = entry
        logger.info(
            "[ontology] loaded %d entities, %d alias keys",
            len(entries),
            len(self._exact),
        )

    def resolve(self, term: str) -> str | None:
        """Return canonical name for *term*, or None if no match found.

        FR-41a: first tries exact match, then fuzzy match.
        FR-41b: caller creates a new Neo4j node when None is returned.
        """
        key = term.strip().lower()
        if not key:
            return None

        # 1. Exact match
        if key in self._exact:
            canonical = self._exact[key].canonical
            logger.debug("[ontology] exact match: %r → %r", term, canonical)
            return canonical

        # 2. Fuzzy match via SequenceMatcher (stdlib, zero dependencies)
        best_ratio = 0.0
        best_canonical: str | None = None
        all_keys = list(self._exact.keys())
        matches = difflib.get_close_matches(key, all_keys, n=1, cutoff=_FUZZY_THRESHOLD)
        if matches:
            best_canonical = self._exact[matches[0]].canonical
            best_ratio = difflib.SequenceMatcher(None, key, matches[0]).ratio()
            logger.debug(
                "[ontology] fuzzy match: %r → %r (ratio=%.2f)",
                term, best_canonical, best_ratio,
            )
            return best_canonical

        logger.debug("[ontology] no match for %r — new node will be created", term)
        return None

    def all_entries(self) -> list[OntologyEntry]:
        return list(self._entries)

    def to_dict(self) -> list[dict]:
        return [
            {
                "canonical": e.canonical,
                "type": e.type,
                "aliases": list(e.aliases),
            }
            for e in self._entries
        ]


@lru_cache(maxsize=1)
def load_ontology(path: str | None = None) -> Ontology:
    """Load and cache the domain ontology (FR-39).

    Called once at startup; subsequent calls return the cached instance.
    """
    ontology_path = Path(path) if path else _ONTOLOGY_PATH
    if not ontology_path.exists():
        logger.warning(
            "[ontology] file not found at %s — using empty ontology", ontology_path
        )
        return Ontology([])

    with ontology_path.open(encoding="utf-8") as f:
        data = json.load(f)

    entries = [
        OntologyEntry(
            canonical=item["canonical"],
            type=item["type"],
            aliases=tuple(item.get("aliases", [])),
        )
        for item in data.get("entities", [])
    ]
    logger.info("[ontology] loaded from %s: %d entries", ontology_path, len(entries))
    return Ontology(entries)


def resolve_entity(term: str) -> tuple[str, bool]:
    """Resolve *term* to its canonical form.

    Returns:
        (canonical_name, is_new) where is_new=True means no match was found
        and the caller should create a new graph node (FR-41b).
    """
    ontology = load_ontology()
    canonical = ontology.resolve(term)
    if canonical is not None:
        return canonical, False
    return term, True  # pass through original, mark as new
