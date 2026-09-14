"""Next Best Action — deterministic lifecycle guidance."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List
from core.domain.lifecycle import STAGES, STAGE_BY_ID, LifecycleState
EVIDENCED = {"FACT", "CUSTOMER_DECISION"}
OWNER_BY_HANDLER = {"intake":"Business Analyst","evidence":"Business Analyst","discovery":"Business Analyst","questions":"Business Analyst","assessment":"Solution Architect","requirements":"Business Analyst","platform":"Solution Architect","architecture":"Solution Architect","data":"Data Engineer","ai":"AI Engineer","bi":"BI Developer","application":"Application Architect","engineering":"Data Engineer","testing":"QA Engineer","qa":"QA Engineer","estimate":"Delivery Manager","estimation":"Delivery Manager","sow":"Delivery Manager","commercial":"Delivery Manager","governance":"Governance Lead","deployment":"DevOps Engineer","operations":"Delivery Manager","operations_handover":"Delivery Manager"}
@dataclass
class Action:
    id: str; title: str; why: str; owner: str; kind: str; stage_id: str = ""; priority: int = 50; automatable: bool = False; blocked_by: List[str] = field(default_factory=list)
    def to_dict(self) -> dict: return {"id":self.id,"title":self.title,"why":self.why,"owner":self.owner,"kind":self.kind,"stage_id":self.stage_id,"automatable":self.automatable,"blocked_by":self.blocked_by}
def _owner_for(stage_id: str) -> str:
    stage=STAGE_BY_ID.get(stage_id); return OWNER_BY_HANDLER.get(getattr(stage,"agent",""),"Delivery Manager")
def engagement_state(state: LifecycleState, evidence_count: int) -> str:
    done,total=state.progress
    if not evidence_count and done<=1:return "AWAITING EVIDENCE"
    if state.pending_approval():return "AWAITING APPROVAL"
    if done==0:return "INTAKE"
    if done>=total:return "COMPLETE"
    latest=None
    for s in STAGES:
        if state.is_complete(s.id): latest=s
    return f"{latest.group} IN PROGRESS" if latest else "INTAKE"
def evidence_completeness(statements: List[Any]) -> Dict[str, Any]:
    # Re-running a stage must not inflate coverage or the customer decision queue.
    unique = {}
    for s in statements:
        if getattr(s, "kind", "") in ("source",):
            continue
        key = (getattr(s, "kind", ""), " ".join((getattr(s, "text", "") or "").split()).casefold())
        if key[1] and key not in unique:
            unique[key] = s
    considered = list(unique.values())
    if not considered:return {"percent":0,"evidenced":0,"open_questions":0,"total":0}
    evidenced=sum(1 for s in considered if (getattr(s,"provenance","") or "") in EVIDENCED)
    open_questions=sum(1 for s in considered if (getattr(s,"provenance","") or "") == "UNKNOWN")
    return {"percent":round(100*evidenced/len(considered)),"evidenced":evidenced,"open_questions":open_questions,"total":len(considered)}
def recommend(state: LifecycleState, statements: List[Any], evidence_count: int, limit: int = 6) -> Dict[str, Any]:
    actions=[]; completeness=evidence_completeness(statements)
    if not evidence_count:
        actions.append(Action("collect-evidence","Upload the customer's RFI, RFP, SOW or notes","No evidence has been supplied, so every downstream stage would be inference rather than fact.","Business Analyst","collect_evidence",priority=0))
    # Never expose a non-existent intent agent as an executable action. If an
    # uploaded source did not contain an explicit purpose/objective, ask for
    # confirmation instead of attempting to run a missing stage.
    if evidence_count and not state.is_complete("intent"):
        actions.append(Action("confirm-business-intent","Confirm business intent","The source pack is present, but no explicit customer intent was captured. Confirm it before the factory proceeds.","Business Analyst","answer_questions",stage_id="intent",priority=1))
    pending=state.pending_approval()
    if pending:
        blocked=[s.label for s in STAGES if pending.id in s.requires and not state.is_complete(s.id)]
        actions.append(Action(f"approve-{pending.id}",f"Review and approve {pending.label}",(f"{pending.label} is complete but needs {pending.approval.value.lower()} approval" + (f", which is holding up {', '.join(blocked[:3])}." if blocked else ".")),_owner_for(pending.id),"approve",stage_id=pending.id,priority=5))
    if completeness["open_questions"]:
        actions.append(Action("answer-open-questions",f"Get customer answers to {completeness['open_questions']} open question{'' if completeness['open_questions']==1 else 's'}","These are recorded as UNKNOWN, so anything built on them is an assumption that will not survive scope lock.","Business Analyst","answer_questions",priority=20))
    nxt=state.next_stage()
    if nxt and nxt.id != "intent":
        actions.append(Action(f"run-{nxt.id}",f"Run {nxt.label}",nxt.description or f"{nxt.label} is the next stage whose inputs are satisfied.",_owner_for(nxt.id),"run_stage",stage_id=nxt.id,priority=10,automatable=True))
    for s in STAGES:
        if state.is_complete(s.id):continue
        reasons=state.blockers(s.id)
        if reasons and (not nxt or s.id != nxt.id):
            actions.append(Action(f"blocked-{s.id}",f"{s.label} is blocked"," ".join(reasons),_owner_for(s.id),"blocked",stage_id=s.id,priority=80,blocked_by=reasons))
            if len([a for a in actions if a.kind=="blocked"])>=3:break
    actions.sort(key=lambda a:a.priority); done,total=state.progress
    return {"state":engagement_state(state,evidence_count),"progress":{"complete":done,"total":total},"evidence":{"documents":evidence_count,**completeness},"primary":actions[0].to_dict() if actions else None,"actions":[a.to_dict() for a in actions[:limit]],"basis":"deterministic: lifecycle gates, approvals and recorded provenance"}
