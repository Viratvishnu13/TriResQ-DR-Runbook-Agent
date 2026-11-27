"""Local knowledge base: runbook catalogue and validation, plus SQLite FTS5 (BM25) cited search."""
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

from .errors import DrillError
from .operator import TOOLS

STEP_TYPES = {"check", "action", "communication", "decision", "wait", "validation", "signoff", "rollback"}
STALE_DAYS = 365
STOPWORDS = set("a an and are as at be been but by can could do does did for from how i if in is it its of on or "
                "our out should so that the their then there this to was we what when where which who why will with "
                "would you your me my tell about happens happen need needs please".split())

# How coordinators say it -> how the runbook says it.
WORDING = {"undo": ["rollback"], "revert": ["rollback"], "failover": ["fail"]}


class Knowledge:
    def __init__(self, root):
        self.root = Path(root)
        self.runbooks = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.root.glob("runbooks/*.json"))]
        self.documents = [self._read_markdown(p) for p in sorted(self.root.glob("docs/*.md"))]
        self.chunks = list(self._chunks())
        self._db = sqlite3.connect(":memory:", check_same_thread=False)
        self._db.execute("CREATE VIRTUAL TABLE idx USING fts5(title, text, tokenize='porter unicode61')")
        self._db.executemany("INSERT INTO idx(rowid, title, text) VALUES(?,?,?)",
                             [(i, c["title"], c["text"]) for i, c in enumerate(self.chunks)])

    @staticmethod
    def _read_markdown(path):
        _, header, body = path.read_text(encoding="utf-8").split("---", 2)
        meta = dict(line.split(":", 1) for line in header.strip().splitlines())
        meta = {k.strip(): v.strip() for k, v in meta.items()}
        sections = []
        for block in re.split(r"(?m)^## ", body)[1:]:
            title, _, text = block.partition("\n")
            sections.append({"title": title.strip(), "text": text.strip()})
        return {**meta, "sections": sections, "source_uri": f"knowledge/docs/{path.name}"}

    def _chunks(self):
        def chunk(doc, section, title, text):
            return {"document_id": doc["document_id"], "version": doc["version"], "section": section,
                    "title": title, "text": text, "application": doc["application"],
                    "approval_status": doc["approval_status"], "document_type": doc["document_type"],
                    "citation": f"{doc['document_id']} v{doc['version']} section {section}"}

        for doc in self.documents:
            for s in doc["sections"]:
                number = s["title"].split()[0] if s["title"][0].isdigit() else s["title"]
                yield chunk(doc, number, f"{doc['title']}: {s['title']}", s["text"])
        for book in self.runbooks:
            for step in book["steps"]:
                text = " ".join([step["description"], step["source"]["text"], step.get("risks", ""),
                                 "Prerequisites: " + "; ".join(step["prerequisites"])])
                yield chunk(book, step["source"]["section"], f"{step['step_id']} {step['name']}", text)
                if step.get("rollback"):
                    back = step["rollback"]
                    yield chunk(book, back["citation"].split()[-1], f"Rollback for {step['step_id']} {step['name']}",
                                f"{back['description']} Expected: {back['expected']}. "
                                f"Validation: {back['validation']}. If it fails: {back['on_failure']}.")

    def runbook(self, document_id, version):
        for book in self.runbooks:
            if (book["document_id"], book["version"]) == (document_id, version):
                return book
        raise DrillError("NOT_FOUND", "No such runbook version in the catalogue.")

    def validate(self, document_id, version, now):
        """Deterministic suitability check. Gaps are reported, never filled in."""
        book, issues = self.runbook(document_id, version), []
        if book["approval_status"] != "approved":
            issues.append(f"Runbook approval status is {book['approval_status']}, not approved.")
        if not book.get("owner"):
            issues.append("Runbook has no owner.")
        age = (now.date() - date.fromisoformat(book["last_reviewed"])).days
        if age > STALE_DAYS:
            issues.append(f"Last review is stale ({age} days old; limit {STALE_DAYS}).")
        others = [b["version"] for b in self.runbooks if b["application"] == book["application"]
                  and b["approval_status"] == "approved" and b["version"] != version]
        if others and book["approval_status"] == "approved":
            issues.append(f"Conflict: other approved versions exist ({', '.join(others)}).")
        seen = []
        for step in sorted(book["steps"], key=lambda s: s["sequence"]):
            sid = step["step_id"]
            if sid in seen:
                issues.append(f"{sid}: duplicate step id.")
            for dep in step["dependencies"]:
                if dep not in seen:
                    issues.append(f"{sid}: dependency {dep} is missing or ordered after this step.")
            seen.append(sid)
            if step["step_type"] not in STEP_TYPES:
                issues.append(f"{sid}: unknown step type {step['step_type']}.")
            if not step.get("owner"):
                issues.append(f"{sid}: no owner.")
            if not step.get("success_criteria"):
                issues.append(f"{sid}: no success criteria.")
            if not step.get("source", {}).get("citation"):
                issues.append(f"{sid}: no source citation.")
            if step.get("tool") and step["tool"] not in TOOLS:
                issues.append(f"{sid}: tool {step['tool']} is not allowlisted.")
            if step["step_type"] == "action":
                if not step.get("approval_required"):
                    issues.append(f"{sid}: action does not require approval.")
                if not step.get("rollback"):
                    issues.append(f"{sid}: action has no rollback.")
        return {"document_id": document_id, "version": version, "usable": not issues, "issues": issues}

    def catalogue(self, now):
        books = [{**{k: b[k] for k in ("document_id", "version", "title", "application", "approval_status",
                                       "owner", "last_reviewed", "source_uri")},
                  "document_type": "runbook",
                  "validation": self.validate(b["document_id"], b["version"], now)} for b in self.runbooks]
        docs = [{k: d[k] for k in ("document_id", "version", "title", "application", "approval_status", "owner",
                                   "last_reviewed", "source_uri", "document_type")} for d in self.documents]
        return {"runbooks": books, "documents": docs, "indexed_passages": len(self.chunks)}

    def template(self, name, **values):
        for doc in self.documents:
            if doc["document_type"] == "communication_template" and doc["approval_status"] == "approved":
                for s in doc["sections"]:
                    if s["title"] == name:
                        return {"draft": s["text"].format_map(values),
                                "citation": f"{doc['document_id']} v{doc['version']} section {name}"}
        raise DrillError("NOT_FOUND", f"No approved communication template named {name}.")

    def prior_lessons(self, application):
        return [{**s, "citation": f"{d['document_id']} v{d['version']}"} for d in self.documents
                if d["document_type"] == "prior_drill_report" and d["application"] == application
                for s in d["sections"]]

    def search(self, query, application=None, limit=5):
        """BM25 over approved material only. Returns [] rather than a weak guess."""
        words = [w for raw in re.findall(r"[a-z0-9]+", str(query).lower()) for w in WORDING.get(raw, [raw])]
        terms = list(dict.fromkeys(w for w in words if w not in STOPWORDS and len(w) > 1))[:20]
        if not terms:
            return []
        matched = {}
        for term in terms:
            for (rowid,) in self._db.execute("SELECT rowid FROM idx WHERE idx MATCH ?", (f'"{term}"',)):
                matched[rowid] = matched.get(rowid, 0) + 1
        ranked = self._db.execute("SELECT rowid, bm25(idx, 3.0, 1.0) FROM idx WHERE idx MATCH ? ORDER BY 2",
                                  (" OR ".join(f'"{t}"' for t in terms),)).fetchall()
        need = min(2, len(terms))
        hits = []
        for rowid, score in ranked:
            c = self.chunks[rowid]
            if c["approval_status"] != "approved" or matched[rowid] < need or matched[rowid] / len(terms) < 0.34:
                continue
            if application and c["application"] not in (application, "ALL"):
                continue
            hits.append({**c, "score": round(-score, 2)})
        return hits[:limit]
