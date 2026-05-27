from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CONTRACT_NAME = "mneme-agent-brain"
CONTRACT_VERSION = "mneme-agent-brain-v1"

MANDATORY_RULES = [
    "evidence_before_belief",
    "candidates_are_tentative",
    "killed_edges_never_surface",
    "semantic_edges_need_validation",
    "open_loops_need_current_evidence",
    "dismissal_weakens_by_default",
    "temporary_agent_memory_uses_mneme_namespace",
    "generated_artifacts_are_private",
]

AGENT_RULES = [
    "Read truth_policy before using any item.",
    "Never state candidate_only edges as facts.",
    "Never use killed or excluded edges.",
    "Treat provenance_not_fact as navigation or source context, not real-world truth.",
    "Treat source_contained_observation as evidence that a source said something, not proof it is currently true.",
    "Treat old open loops as historical unless fresh evidence confirms they are live.",
    "Use mneme:// memory for temporary agent state.",
    "Only write Markdown when the user explicitly asks.",
]

_RELATION_POLICIES: dict[str, dict[str, Any]] = {
    "links_to": {"category": "reference", "requires_validation": False},
    "linked_from": {"category": "reference", "requires_validation": False},
    "has_heading": {"category": "structure", "requires_validation": False},
    "mentions_email": {"category": "extraction", "requires_validation": False},
    "mentions_date": {"category": "extraction", "requires_validation": False},
    "has_fact": {"category": "observation", "requires_validation": False},
    "has_blocked": {"category": "observation", "requires_validation": False},
    "has_risk": {"category": "observation", "requires_validation": False},
    "has_done": {"category": "observation", "requires_validation": False},
    "belongs_to": {"category": "semantic", "requires_validation": True},
    "has_part": {"category": "semantic", "requires_validation": True},
    "located_in": {"category": "semantic", "requires_validation": True},
    "contains_location": {"category": "semantic", "requires_validation": True},
    "father_of": {"category": "semantic", "requires_validation": True},
    "part_of": {"category": "semantic", "requires_validation": True},
    "attends_activity": {"category": "semantic", "requires_validation": True},
    "requested_activity": {"category": "semantic_pending", "requires_validation": True},
    "revalidated_by": {"category": "observation", "requires_validation": False},
}


@dataclass(frozen=True)
class RelationshipPolicy:
    relation: str
    category: str
    requires_validation: bool
    known: bool = True


@dataclass(frozen=True)
class EdgeWriteDecision:
    status: str
    strength: float
    blocked: bool = False
    reasons: list[str] = field(default_factory=list)
    contract_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContractReport:
    status: str
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": CONTRACT_NAME,
            "version": CONTRACT_VERSION,
            "status": self.status,
            "failures": self.failures,
            "warnings": self.warnings,
            "checked": self.checked,
        }


def relationship_policy(relation: str) -> RelationshipPolicy:
    data = _RELATION_POLICIES.get(relation)
    if data is None:
        return RelationshipPolicy(relation=relation, category="unknown", requires_validation=True, known=False)
    return RelationshipPolicy(
        relation=relation,
        category=str(data["category"]),
        requires_validation=bool(data["requires_validation"]),
    )


def explicit_validation(metadata: dict[str, Any] | None, *, source_type: str, evidence_text: str | None, confidence: float) -> bool:
    metadata = metadata or {}
    if metadata.get("explicitly_validated") or metadata.get("validated") or metadata.get("user_confirmed"):
        return True
    if metadata.get("research_resolution") and source_type not in {"vault", "ingest"}:
        return bool((evidence_text or "").strip()) and confidence >= 0.9
    if source_type in {"receipt", "user_confirmation", "sense_bridge"}:
        return bool((evidence_text or "").strip()) and confidence >= 0.9
    return False


def deterministic_ingest_status(relation: str) -> str:
    policy = relationship_policy(relation)
    if policy.category == "observation":
        return "active"
    return "candidate"


def enforce_edge_write(
    *,
    relation: str,
    requested_status: str,
    evidence_text: str | None,
    confidence: float,
    source_type: str,
    metadata: dict[str, Any] | None,
    requested_strength: float | None = None,
) -> EdgeWriteDecision:
    policy = relationship_policy(relation)
    requested_status = requested_status or "candidate"
    strength = float(confidence if requested_strength is None else requested_strength)
    reasons: list[str] = []
    status = requested_status
    validated = explicit_validation(metadata, source_type=source_type, evidence_text=evidence_text, confidence=float(confidence))

    if requested_status == "killed":
        status = "killed"
        strength = 0.0 if requested_strength is None else min(0.0, strength)
        reasons.append("killed_tombstone")
    elif requested_status == "active" and policy.requires_validation and not validated:
        status = "candidate"
        reasons.append("requires_explicit_validation")
    elif requested_status == "active" and policy.requires_validation and not (evidence_text or "").strip():
        status = "candidate"
        reasons.append("missing_evidence")

    payload = {
        "name": CONTRACT_NAME,
        "version": CONTRACT_VERSION,
        "rules": MANDATORY_RULES,
        "relation": relation,
        "category": policy.category,
        "requires_validation": policy.requires_validation,
        "requested_status": requested_status,
        "status": status,
        "explicit_validation": validated,
        "reasons": reasons,
    }
    return EdgeWriteDecision(status=status, strength=strength, reasons=reasons, contract_payload=payload)


def truth_policy_for_edge(
    *,
    status: str | None,
    relation: str,
    source_type: str | None = None,
    evidence_text: str | None = None,
) -> str:
    del source_type, evidence_text
    policy = relationship_policy(relation)
    status = status or "candidate"
    if status == "killed":
        return "excluded"
    if status != "active":
        return "candidate_only"
    if policy.requires_validation:
        return "active_validated_claim"
    if policy.category in {"reference", "structure", "extraction"}:
        return "provenance_not_fact"
    if policy.category == "observation":
        return "source_contained_observation"
    return "active_evidence"


def validate_retrieval_pack(pack: dict[str, Any]) -> ContractReport:
    failures: list[str] = []
    warnings: list[str] = []
    checked = {"items": 0, "candidate_edges": 0, "excluded_edges": 0}
    for item in pack.get("items") or []:
        checked["items"] += 1
        kind = item.get("kind")
        status = item.get("status")
        truth_policy = item.get("truth_policy")
        if truth_policy is None:
            failures.append(f"{kind or 'item'}:{item.get('id')} missing truth_policy")
        if status == "killed" or truth_policy == "excluded":
            checked["excluded_edges"] += 1
            failures.append(f"{kind or 'item'}:{item.get('id')} includes killed/excluded memory")
        if kind == "edge" and status != "active":
            checked["candidate_edges"] += 1
            if truth_policy != "candidate_only":
                failures.append(f"edge:{item.get('id')} candidate edge is not marked candidate_only")
    return ContractReport(status="fail" if failures else "pass", failures=failures, warnings=warnings, checked=checked)


def validate_agent_action(action: dict[str, Any], context_item: dict[str, Any]) -> ContractReport:
    truth_policy = context_item.get("truth_policy")
    failures: list[str] = []
    if truth_policy in {"candidate_only", "excluded"} and action.get("phrased_as_fact"):
        failures.append("agent action treats tentative or excluded memory as fact")
    return ContractReport(status="fail" if failures else "pass", failures=failures, checked={"actions": 1})


def _loads_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def check_db_contract(db_path: Path) -> ContractReport:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    failures: list[str] = []
    warnings: list[str] = []
    checked = {"edges": 0, "active_edges": 0, "killed_edges": 0}
    try:
        rows = conn.execute(
            "SELECT id,relation,status,evidence_text,confidence,source_type,metadata_json FROM edges"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        conn.close()
        return ContractReport(status="fail", failures=[f"database is missing graph tables: {exc}"], checked=checked)
    for row in rows:
        checked["edges"] += 1
        if row["status"] == "active":
            checked["active_edges"] += 1
        if row["status"] == "killed":
            checked["killed_edges"] += 1
        policy = relationship_policy(row["relation"])
        metadata = _loads_json(row["metadata_json"])
        validated = explicit_validation(
            metadata,
            source_type=row["source_type"] or "vault",
            evidence_text=row["evidence_text"],
            confidence=float(row["confidence"] or 0.0),
        )
        if row["status"] == "active" and policy.requires_validation and not validated:
            failures.append(f"edge:{row['id']} active {policy.category} relation lacks explicit validation")
        if row["status"] == "active" and policy.requires_validation and not (row["evidence_text"] or "").strip():
            failures.append(f"edge:{row['id']} active {policy.category} relation lacks evidence")
        if row["status"] == "active" and not policy.known:
            warnings.append(f"edge:{row['id']} uses unknown relation {row['relation']!r}")
    conn.close()
    return ContractReport(status="fail" if failures else "pass", failures=failures, warnings=warnings, checked=checked)


def report_to_json(report: ContractReport) -> str:
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=lambda value: asdict(value))
