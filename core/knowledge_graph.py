"""Knowledge Graph — extracts entities and relations from documents."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Entity:
    name: str
    type: str
    context: str = ""


@dataclass
class Relation:
    source: str
    target: str
    relation_type: str
    context: str = ""


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
            "entities": [{"name": e.name, "type": e.type, "context": e.context}
                        for e in self.entities],
            "relations": [{"source": r.source, "target": r.target,
                          "type": r.relation_type, "context": r.context}
                         for r in self.relations],
        }

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
    CLASS_PATTERN = re.compile(
        r'(?:public|private|protected)?\s*(?:abstract|final|static)?\s*'
        r'(?:class|interface|enum|record|trait|object)\s+(\w+)'
    )
    FUNCTION_PATTERN = re.compile(
        r'(?:public|private|protected|static|final|async|def|fun|function)\s+'
        r'(\w+)\s*\('
    )
    IMPORT_PATTERN = re.compile(
        r'(?:import|from|require|using)\s+[\'"]?([\w.]+)[\'"]?'
    )

    _RESERVED_KEYWORDS = frozenset({
        'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'return',
        'try', 'catch', 'finally', 'throw', 'throws', 'new', 'this', 'super',
        'extends', 'implements', 'instanceof', 'typeof', 'void', 'null',
        'true', 'false', 'None', 'True', 'False', 'and', 'or', 'not',
        'in', 'is', 'lambda', 'with', 'yield', 'async', 'await',
    })

    def extract(self, text: str, source: str = "") -> tuple[list[Entity], list[Relation]]:
        entities = []
        relations = []
        seen = set()

        for match in self.CLASS_PATTERN.finditer(text):
            name = match.group(1)
            if name not in seen and len(name) > 2 and name.lower() not in self._RESERVED_KEYWORDS:
                entities.append(Entity(name=name, type="CODE_CLASS", context=source))
                seen.add(name)

        for match in self.FUNCTION_PATTERN.finditer(text):
            name = match.group(1)
            kw_check = name.split('_')[0].lower()
            if (name not in seen and len(name) > 2
                    and not name.startswith('_')
                    and kw_check not in self._RESERVED_KEYWORDS):
                entities.append(Entity(name=name, type="FUNCTION", context=source))
                seen.add(name)

        for match in self.IMPORT_PATTERN.finditer(text):
            module = match.group(1)
            source_base = source.split("/")[-1].replace(".java", "").replace(".py", "")
            relations.append(Relation(
                source=source_base,
                target=module.split(".")[-1],
                relation_type="IMPORTS",
                context=module,
            ))

        return entities, relations


class KnowledgeGraphIndex:
    def __init__(self, storage_path: str = "./data/knowledge_graphs"):
        self.storage_path = Path(storage_path)
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
            return {"found": False, "name": entity_name}

        return {
            "found": True,
            "entity": {"name": entity.name, "type": entity.type},
            "neighbors": kg.get_neighbors(entity_name),
            "relations": [
                {"target": r.target, "type": r.relation_type}
                for r in kg.get_related(entity_name)
            ],
        }
