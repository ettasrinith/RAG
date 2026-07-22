"""Knowledge Graph — extracts entities and relations from documents.

Supports 9 entity types with NLP-enhanced extraction and entity clustering.
"""
from __future__ import annotations

import json
import re
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from core.config import resolve_data_path
from core.logging import get_logger

log = get_logger("knowledge_graph")

# ── 9 Entity Types ──────────────────────────────────────────────────

ENTITY_TYPES = {
    "PERSON": "People, authors, contributors",
    "ORGANIZATION": "Companies, teams, institutions",
    "CODE_CLASS": "Classes, interfaces, structs, records",
    "FUNCTION": "Functions, methods, procedures",
    "MODULE": "Modules, packages, libraries, imports",
    "CONCEPT": "Technical concepts, algorithms, patterns",
    "FILE": "Files, paths, configurations",
    "API_ENDPOINT": "REST endpoints, RPC methods, routes",
    "DEPENDENCY": "External dependencies, packages, frameworks",
}

RELATION_TYPES = {
    "IMPORTS": "Module imports another",
    "EXTENDS": "Class inheritance / implementation",
    "CALLS": "Function calls another",
    "DEPENDS_ON": "Project depends on package",
    "CONTAINS": "Module contains function/class",
    "IMPLEMENTS": "Class implements interface",
    "USES": "General usage relationship",
    "AUTHORED_BY": "Person authored/created entity",
    "PART_OF": "Entity is part of organization/team",
    "RELATED_TO": "General semantic relationship",
}


@dataclass
class Entity:
    name: str
    type: str
    context: str = ""
    mentions: int = 1
    embedding: list[float] | None = None
    aliases: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return hashlib.md5(f"{self.type}:{self.name.lower()}".encode()).hexdigest()[:12]


@dataclass
class Relation:
    source: str
    target: str
    relation_type: str
    context: str = ""
    weight: float = 1.0
    metadata: dict = field(default_factory=dict)


@dataclass
class KnowledgeGraph:
    repo: str
    entities: list[Entity] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)

    def add_entity(self, entity: Entity) -> None:
        self.entities.append(entity)

    def add_relation(self, relation: Relation) -> None:
        key = (relation.source.lower(), relation.target.lower(), relation.relation_type.lower(), relation.context.strip())
        existing = {
            (r.source.lower(), r.target.lower(), r.relation_type.lower(), r.context.strip())
            for r in self.relations
        }
        if key not in existing:
            self.relations.append(relation)

    def get_entity(self, name: str) -> Entity | None:
        for e in self.entities:
            if e.name.lower() == name.lower():
                return e
        return None

    def get_related(self, entity_name: str) -> list[Relation]:
        return [r for r in self.relations
                if r.source.lower() == entity_name.lower() or
                r.target.lower() == entity_name.lower()]

    def get_neighbors(self, entity_name: str) -> list[str]:
        neighbors = set()
        for r in self.get_related(entity_name):
            if r.source.lower() != entity_name.lower():
                neighbors.add(r.source)
            if r.target.lower() != entity_name.lower():
                neighbors.add(r.target)
        return sorted(neighbors)

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "entities": [
                {
                    "name": e.name, "type": e.type, "context": e.context,
                    "mentions": e.mentions, "id": e.id,
                    **({"aliases": e.aliases} if e.aliases else {}),
                }
                for e in self.entities
            ],
            "relations": [
                {"source": r.source, "target": r.target,
                 "type": r.relation_type, "context": r.context, "weight": r.weight}
                for r in self.relations
            ],
        }

    def get_clusters(self, min_size: int = 2) -> list[dict]:
        """Find entity clusters using connected components (union-find).

        Clusters are groups of entities that are densely connected through
        relations. Useful for discovering logical modules, feature areas,
        or domain groupings.
        """
        parent: dict[str, str] = {}
        rank: dict[str, int] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            rank.setdefault(x, 0)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str):
            ra, rb = find(a), find(b)
            if ra == rb:
                return
            if rank[ra] < rank[rb]:
                ra, rb = rb, ra
            parent[rb] = ra
            if rank[ra] == rank[rb]:
                rank[ra] += 1

        # Build unions from relations
        for r in self.relations:
            union(r.source.lower(), r.target.lower())

        # Group entities by cluster
        clusters: dict[str, list[Entity]] = defaultdict(list)
        for e in self.entities:
            root = find(e.name.lower())
            clusters[root].append(e)

        # Filter and format
        result = []
        for root, members in clusters.items():
            if len(members) >= min_size:
                type_counts = Counter(e.type for e in members)
                result.append({
                    "id": hashlib.md5(root.encode()).hexdigest()[:8],
                    "size": len(members),
                    "entities": [{"name": e.name, "type": e.type} for e in members[:20]],
                    "dominant_type": type_counts.most_common(1)[0][0] if type_counts else "UNKNOWN",
                    "type_distribution": dict(type_counts),
                })

        result.sort(key=lambda c: c["size"], reverse=True)
        return result

    def entity_stats(self) -> dict:
        """Return statistics about the knowledge graph."""
        type_counts = Counter(e.type for e in self.entities)
        rel_counts = Counter(r.relation_type for r in self.relations)
        return {
            "total_entities": len(self.entities),
            "total_relations": len(self.relations),
            "entity_types": dict(type_counts),
            "relation_types": dict(rel_counts),
            "clusters": len(self.get_clusters(min_size=2)),
        }

    def search_entities(self, query: str, entity_type: str = "", limit: int = 20) -> list[dict]:
        """Search entities by name substring match."""
        q = query.lower()
        results = []
        for e in self.entities:
            if entity_type and e.type != entity_type:
                continue
            if q in e.name.lower() or any(q in a.lower() for a in e.aliases):
                results.append({
                    "name": e.name, "type": e.type, "mentions": e.mentions,
                    "id": e.id, "context": e.context,
                })
                if len(results) >= limit:
                    break
        return results

    def save(self, path: str) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2),
                              encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> KnowledgeGraph:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        kg = cls(repo=data["repo"])
        for e in data.get("entities", []):
            kg.add_entity(Entity(name=e["name"], type=e["type"],
                                context=e.get("context", "")))
        for r in data.get("relations", []):
            kg.add_relation(Relation(source=r["source"], target=r["target"],
                                    relation_type=r["type"],
                                    context=r.get("context", "")))
        return kg


class EntityExtractor:
    """Extracts 9 entity types with pattern-based and context-aware rules."""

    # ── Code patterns ──
    CLASS_PATTERN = re.compile(
        r'(?:public|private|protected)?\s*(?:abstract|final|static)?\s*'
        r'(?:class|interface|enum|record|trait|object|struct)\s+(\w+)'
    )
    FUNCTION_PATTERN = re.compile(
        r'(?:public|private|protected|static|final|async|def|fun|function|fn|func)\s+'
        r'(\w+)\s*\('
    )
    IMPORT_PATTERN = re.compile(
        r'(?:import|from|require|using|use)\s+[\'"]?([\w.]+)[\'"]?'
    )
    ENDPOINT_PATTERN = re.compile(
        r'(?:@(?:app|router)\.(?:get|post|put|patch|delete|route))\s*\(\s*[\'"]([^\'"]+)[\'"]'
        r'|(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+([/\w\-{}]+)'
        r'|(?:path|route)\s*\(\s*[\'"]([^\'"]+)[\'"]'
    )
    FILE_PATTERN = re.compile(
        r'(?:[\w\-]+\.(?:py|js|ts|jsx|tsx|java|go|rs|rb|cpp|c|h|hpp|yaml|yml|json|toml|md|txt|sh))'
    )
    DEPENDENCY_PATTERN = re.compile(
        r'(?:requirements?\.txt|package\.json|pyproject\.toml|Cargo\.toml|go\.mod|build\.gradle|pom\.xml)'
    )
    API_CALL_PATTERN = re.compile(
        r'(?:fetch|axios|requests?\.(?:get|post|put|delete)|http\.(?:get|post)|'
        r'client\.\w+\.\w+)\s*\('
    )

    # ── NLP-style patterns for concepts ──
    CONCEPT_PATTERNS = [
        (re.compile(r'\b(SOLID|DRY|KISS|YAGNI|MVC|MVP|MVVM|REST|GraphQL|gRPC|WebSocket)\b', re.I), "CONCEPT"),
        (re.compile(r'\b(pattern|algorithm|paradigm|architecture|framework|protocol)\b', re.I), "CONCEPT"),
        (re.compile(r'\b(caching|pagination|serialization|authentication|authorization|middleware)\b', re.I), "CONCEPT"),
        (re.compile(r'\b(circuit.?breaker|rate.?limit|load.?balanc|retry|backoff|throttl)\w*', re.I), "CONCEPT"),
        (re.compile(r'\b(recursive|async|concurrent|parallel|distributed|microservice)\w*', re.I), "CONCEPT"),
    ]

    # ── Organization patterns ──
    ORG_PATTERNS = [
        re.compile(r'\b(Google|Microsoft|Apple|Meta|Amazon|OpenAI|Anthropic|DeepMind|HuggingFace|Apache|Mozilla)\b'),
        re.compile(r'\b(team|department|group|division|company|corporation|inc|llc|ltd)\b', re.I),
    ]

    # ── Person patterns ──
    PERSON_PATTERNS = [
        re.compile(r'\b(?:by| authored by|written by|created by|developed by)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)'),
        re.compile(r'@(\w+)\b'),  # GitHub handles
    ]

    _RESERVED_KEYWORDS = frozenset({
        'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'return',
        'try', 'catch', 'finally', 'throw', 'throws', 'new', 'this', 'super',
        'extends', 'implements', 'instanceof', 'typeof', 'void', 'null',
        'true', 'false', 'None', 'True', 'False', 'and', 'or', 'not',
        'in', 'is', 'lambda', 'with', 'yield', 'async', 'await',
        'print', 'log', 'error', 'warn', 'debug', 'info',
    })

    def extract(self, text: str, source: str = "") -> tuple[list[Entity], list[Relation]]:
        entities: list[Entity] = []
        relations: list[Relation] = []
        seen: set[str] = set()
        mention_counts: Counter = Counter()

        def _add(name: str, etype: str, ctx: str = ""):
            key = f"{etype}:{name.lower()}"
            if key in seen or len(name) < 2 or name.lower() in self._RESERVED_KEYWORDS:
                return
            seen.add(key)
            mention_counts[key] += 1
            entities.append(Entity(name=name, type=etype, context=ctx or source, mentions=1))

        # CODE_CLASS
        for m in self.CLASS_PATTERN.finditer(text):
            _add(m.group(1), "CODE_CLASS")

        # FUNCTION
        for m in self.FUNCTION_PATTERN.finditer(text):
            name = m.group(1)
            kw = name.split('_')[0].lower()
            if not name.startswith('_') and kw not in self._RESERVED_KEYWORDS:
                _add(name, "FUNCTION")

        # MODULE (from imports)
        for m in self.IMPORT_PATTERN.finditer(text):
            module = m.group(1)
            parts = module.split(".")
            root = parts[0] if parts else module
            _add(root, "MODULE")
            if len(parts) > 1:
                source_base = Path(source).stem if source else "unknown"
                relations.append(Relation(
                    source=source_base, target=root,
                    relation_type="IMPORTS", context=module,
                ))

        # API_ENDPOINT
        for m in self.ENDPOINT_PATTERN.finditer(text):
            endpoint = m.group(1) or m.group(2) or m.group(3)
            if endpoint:
                _add(endpoint, "API_ENDPOINT")

        # FILE
        for m in self.FILE_PATTERN.finditer(text):
            _add(m.group(0), "FILE")

        # DEPENDENCY
        for m in self.DEPENDENCY_PATTERN.finditer(text):
            _add(m.group(0), "DEPENDENCY")

        # CONCEPT (NLP-style)
        for pattern, etype in self.CONCEPT_PATTERNS:
            for m in pattern.finditer(text):
                _add(m.group(0) if not m.groups() else (m.group(1) or m.group(0)), "CONCEPT")

        # ORGANIZATION
        for pattern in self.ORG_PATTERNS:
            for m in pattern.finditer(text):
                name = m.group(0) if not m.groups() else (m.group(1) or m.group(0))
                _add(name, "ORGANIZATION")

        # PERSON
        for pattern in self.PERSON_PATTERNS:
            for m in pattern.finditer(text):
                name = m.group(1) if m.groups() else m.group(0)
                if name and len(name) > 1:
                    _add(name, "PERSON")

        # ── Derive relations from co-occurrence ──
        self._derive_relations(entities, relations, text, source)

        return entities, relations

    def _derive_relations(
        self,
        entities: list[Entity],
        relations: list[Relation],
        text: str,
        source: str,
    ) -> None:
        """Derive additional relations from entity co-occurrence and context."""
        entity_map = {e.name.lower(): e for e in entities}
        existing = {(r.source.lower(), r.target.lower(), r.relation_type) for r in relations}

        # CLASS extends / implements
        extend_pattern = re.compile(
            r'(?:class|interface|record|trait)\s+(\w+)\s+(?:extends|implements|:)\s+(\w+)'
        )
        for m in extend_pattern.finditer(text):
            src, tgt = m.group(1), m.group(2)
            key = (src.lower(), tgt.lower(), "EXTENDS")
            if key not in existing:
                relations.append(Relation(source=src, target=tgt, relation_type="EXTENDS"))
                existing.add(key)

        # CONTAINS relations (file contains classes/functions)
        file_entities = [e for e in entities if e.type == "FILE"]
        code_entities = [e for e in entities if e.type in ("CODE_CLASS", "FUNCTION")]
        for fe in file_entities:
            for ce in code_entities:
                key = (fe.name.lower(), ce.name.lower(), "CONTAINS")
                if key not in existing:
                    relations.append(Relation(
                        source=fe.name, target=ce.name,
                        relation_type="CONTAINS", context="file contains",
                    ))
                    existing.add(key)

        # CALLS relations (function A calls function B)
        call_pattern = re.compile(r'(\w+)\s*\.\s*(\w+)\s*\(')
        for m in call_pattern.finditer(text):
            obj, method = m.group(1), m.group(2)
            if obj.lower() in entity_map and method.lower() in entity_map:
                key = (obj.lower(), method.lower(), "CALLS")
                if key not in existing:
                    relations.append(Relation(source=obj, target=method, relation_type="CALLS"))
                    existing.add(key)


class KnowledgeGraphIndex:
    def __init__(self, storage_path: str = "./data/knowledge_graphs"):
        self.storage_path = resolve_data_path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.graphs: dict[str, KnowledgeGraph] = {}

    def get_or_create(self, repo: str) -> KnowledgeGraph:
        if repo not in self.graphs:
            path = self.storage_path / f"{repo}.json"
            if path.exists():
                self.graphs[repo] = KnowledgeGraph.load(str(path))
            else:
                self.graphs[repo] = KnowledgeGraph(repo=repo)
        return self.graphs[repo]

    def save_all(self) -> None:
        for repo, kg in self.graphs.items():
            path = self.storage_path / f"{repo}.json"
            kg.save(str(path))

    def build_from_doc(self, repo: str, doc_id: str, content: str) -> None:
        kg = self.get_or_create(repo)
        extractor = EntityExtractor()
        entities, relations = extractor.extract(content, doc_id)

        for e in entities:
            if not kg.get_entity(e.name):
                kg.add_entity(e)

        for r in relations:
            kg.add_relation(r)

    def query(self, repo: str, entity_name: str) -> dict:
        kg = self.get_or_create(repo)
        entity = kg.get_entity(entity_name)
        if not entity:
            # Try fuzzy search
            matches = kg.search_entities(entity_name, limit=5)
            if matches:
                return {"found": False, "name": entity_name, "similar": matches}
            return {"found": False, "name": entity_name}

        return {
            "found": True,
            "entity": {"name": entity.name, "type": entity.type, "id": entity.id},
            "neighbors": kg.get_neighbors(entity_name),
            "relations": [
                {"target": r.target, "type": r.relation_type, "weight": r.weight}
                for r in kg.get_related(entity_name)
            ],
        }

    def stats(self, repo: str) -> dict:
        """Get statistics for a repo's knowledge graph."""
        kg = self.get_or_create(repo)
        return kg.entity_stats()

    def clusters(self, repo: str, min_size: int = 2) -> list[dict]:
        """Get entity clusters for a repo."""
        kg = self.get_or_create(repo)
        return kg.get_clusters(min_size=min_size)

    def search(self, repo: str, query: str, entity_type: str = "", limit: int = 20) -> list[dict]:
        """Search entities in a repo's knowledge graph."""
        kg = self.get_or_create(repo)
        return kg.search_entities(query, entity_type=entity_type, limit=limit)
