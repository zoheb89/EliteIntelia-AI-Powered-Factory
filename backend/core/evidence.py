"""Evidence ingestion and document classification (spec §8, §9).

Responsibilities:

* extract text from the supported formats
* hash for integrity and de-duplication — re-uploading the same file must not
  silently create a second copy that later contradicts the first
* classify the document type (RFI / RFP / RFQ / SOW / notes / schema …) from its
  own language rather than its filename, which is frequently wrong
* detect sensitivity (PII / PHI) so downstream governance has a real signal
* chunk with locators, so a citation can point at something a human can find

Classification is deliberately deterministic. A misclassified RFP changes which
extraction rules apply, so it must be reproducible and inspectable.
"""
from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
TYPE_SIGNALS={"rfp":[(r"\brequest for proposal\b",6),(r"\brfp\b",4),(r"\bmandatory requirement",3),(r"\bevaluation criteria\b",3),(r"\bsubmission (?:requirement|instruction|deadline)",3),(r"\bbidder|tenderer\b",2),(r"\bscope of work\b",2),(r"\bservice level agreement|\bsla\b",1.5)],"rfi":[(r"\brequest for information\b",6),(r"\brfi\b",4),(r"\binformation (?:requested|required)\b",3),(r"\bcapability (?:statement|questionnaire)\b",3),(r"\bplease describe\b",2),(r"\bvendor questionnaire\b",2)],"rfq":[(r"\brequest for quot",6),(r"\brfq\b",4),(r"\bunit price|\bprice schedule\b",3),(r"\bquantit(?:y|ies)\b",2),(r"\bquotation\b",3),(r"\bdelivery terms\b",2)],"sow":[(r"\bstatement of work\b",6),(r"\bsow\b",4),(r"\bdeliverable",2),(r"\bacceptance criteria\b",3),(r"\bmilestone",2),(r"\bchange control\b",2)],"architecture":[(r"\barchitecture (?:diagram|document|overview)\b",5),(r"\bdata flow\b",2),(r"\bcomponent diagram\b",3),(r"\bhigh[- ]level design\b",4),(r"\btarget state\b",2)],"schema":[(r"\bcreate table\b",5),(r"\bprimary key\b",3),(r"\bforeign key\b",3),(r"\bdata dictionary\b",5),(r"\bcolumn name\b",2),(r"\bvarchar|nvarchar|int\b",1)],"meeting_notes":[(r"\bmeeting (?:notes|minutes)\b",6),(r"\battendees\b",4),(r"\baction items?\b",3),(r"\bagenda\b",2),(r"\bnext steps\b",2),(r"\bworkshop\b",3)],"requirements":[(r"\bfunctional requirement",5),(r"\bnon[- ]functional requirement",5),(r"\buser stor(?:y|ies)\b",3),(r"\bshall\b",1.5),(r"\bacceptance criteria\b",2)]}
SENSITIVITY_SIGNALS={"phi":[r"\bpatient\b",r"\bdiagnos",r"\bmedical record\b",r"\bclinical\b",r"\bprescription\b",r"\bhipaa\b",r"\bprotected health information\b",r"\badmission\b",r"\bdischarge\b"],"pii":[r"\bdate of birth\b",r"\bnational id\b",r"\bpassport\b",r"\bssn\b",r"\bemail address\b",r"\bphone number\b",r"\bgdpr\b",r"\bpersonally identifiable\b",r"\baddress\b"]}
SUPPORTED={".pdf":"application/pdf",".docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document",".doc":"application/msword",".xlsx":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",".xls":"application/vnd.ms-excel",".pptx":"application/vnd.openxmlformats-officedocument.presentationml.presentation",".txt":"text/plain",".csv":"text/csv",".json":"application/json",".xml":"application/xml",".md":"text/markdown",".eml":"message/rfc822",".msg":"application/vnd.ms-outlook"}
CHUNK_CHARS=1200; CHUNK_OVERLAP=120
@dataclass
class Classification:
    document_type:str; confidence:str; scores:Dict[str,float]=field(default_factory=dict); sensitivity:str="normal"; sensitivity_signals:List[str]=field(default_factory=list); signals_matched:List[str]=field(default_factory=list)
    def to_dict(self)->dict:return {"document_type":self.document_type,"confidence":self.confidence,"scores":{k:round(v,1) for k,v in self.scores.items() if v},"sensitivity":self.sensitivity,"sensitivity_signals":self.sensitivity_signals,"signals_matched":self.signals_matched[:12]}
def sha256(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def classify(text:str,filename:str="")->Classification:
    body=(text or "").lower(); name=(filename or "").lower(); scores={}; matched=[]
    for doc_type,signals in TYPE_SIGNALS.items():
        total=0.0
        for pattern,weight in signals:
            hits=len(re.findall(pattern,body))
            if hits: total+=weight*min(hits,4); matched.append(f"{doc_type}:{pattern.strip(chr(92)+'b')}")
        if re.search(rf"\b{doc_type}\b",name): total+=2.0
        scores[doc_type]=total
    best=max(scores,key=lambda k:scores[k]) if scores else "unknown"; top=scores.get(best,0.0); runner=sorted(scores.values(),reverse=True)[1] if len(scores)>1 else 0.0
    if top<4: doc_type,confidence=("notes" if body.strip() else "unknown"),"LOW"
    elif top>=10 and top>=runner*1.8: doc_type,confidence=best,"HIGH"
    else: doc_type,confidence=best,"MEDIUM"
    sensitivity,sens_signals="normal",[]
    for level,patterns in SENSITIVITY_SIGNALS.items():
        hits=[p for p in patterns if re.search(p,body)]
        if len(hits)>=2: sensitivity=level; sens_signals=[h.strip(chr(92)+"b") for h in hits[:6]]; break
    return Classification(doc_type,confidence,scores,sensitivity,sens_signals,matched)
def chunk(text:str,size:int=CHUNK_CHARS,overlap:int=CHUNK_OVERLAP)->List[dict]:
    text=text or ""
    if not text.strip(): return []
    out=[]; start=0
    while start<len(text):
        end=min(start+size,len(text))
        if end<len(text):
            window=text.rfind(". ",start+size//2,end)
            if window!=-1:end=window+1
        body=text[start:end].strip()
        if body:out.append({"locator":f"chars:{start}-{end}","text":body})
        if end>=len(text):break
        start=max(end-overlap,start+1)
    return out
def extract(filename:str,data:bytes)->Tuple[str,dict]:
    try:
        from c_invent.services.document_intel import extract_upload
        class _Shim:
            def __init__(self,name,payload):self.name,self._d=name,payload
            def getvalue(self):return self._d
        text,meta=extract_upload(_Shim(filename,data));return text or "",(meta or {})
    except Exception as exc:
        try:return data.decode("utf-8",errors="replace"),{"extraction_error":str(exc)[:300]}
        except Exception:return "",{"extraction_error":str(exc)[:300]}
def extract_explicit_intent(text:str)->str:
    """Extract only explicit customer-authored intent; never invent a goal."""
    body=" ".join((text or "").split())
    if not body:return ""
    patterns=[r"(?:the\s+)?(?:purpose|objective|goal)\s+(?:of\s+(?:this\s+)?(?:rfp|project|initiative)\s+)?(?:is|are|:)\s+(.{40,500}?)(?=\.\s+|$)",r"(?:this\s+(?:rfp|project|initiative))\s+(?:seeks|aims|is\s+intended)\s+to\s+(.{40,500}?)(?=\.\s+|$)",r"(?:we\s+(?:seek|are\s+looking)\s+to|the\s+requirement\s+is\s+to)\s+(.{40,500}?)(?=\.\s+|$)"]
    for pattern in patterns:
        match=re.search(pattern,body,re.IGNORECASE)
        if match:
            value=match.group(1).strip(" :;-\t")
            if len(value)>=40:return value[:500].rstrip(" ,;:")+("." if not value.endswith((".","!","?")) else "")
    return ""
def ingest(repo,project_id:str,filename:str,data:bytes,mime_type:str="",source:str="upload")->Dict[str,Any]:
    digest=sha256(data); existing=repo.find_evidence_by_hash(project_id,digest)
    if existing:return {"duplicate":True,"evidence_id":existing.id,"name":existing.name,"document_type":existing.document_type,"message":"This file has already been ingested; the existing record was kept."}
    text,meta=extract(filename,data); cls=classify(text,filename); chunks=chunk(text)
    ev=repo.add_evidence(project_id,name=filename,mime_type=mime_type or SUPPORTED.get("."+filename.rsplit(".",1)[-1].lower(),""),size_bytes=len(data),sha256=digest,source=source,document_type=cls.document_type,sensitivity=cls.sensitivity,classification="confidential" if cls.sensitivity!="normal" else "internal",status="processed" if text.strip() else "failed",extracted_text=text[:200_000],analysis_json=__import__("json").dumps({**cls.to_dict(),"extraction":meta,"chunks":len(chunks)}))
    if chunks:repo.add_chunks(ev.id,project_id,chunks)
    intent=extract_explicit_intent(text); project=repo.get_project(project_id); intent_captured=False
    if intent and project and not (project.intent or "").strip():
        project.intent=intent
        repo.add_statement(project_id,kind="intent",text=intent,provenance="FACT",confidence="HIGH",evidence=[{"evidence_id":ev.id,"locator":"document","excerpt":intent}],stage="intent",ref="INT-001")
        repo.audit("intent.captured","stage","intent",reason="Explicit customer intent captured from uploaded evidence.",after={"evidence_id":ev.id,"text":intent[:300]},actor_kind="system",project_id=project_id); intent_captured=True
    repo.add_statement(project_id,kind="evidence",text=f"Source document '{filename}' was ingested and indexed as {cls.document_type.upper()}.",provenance="FACT",confidence="HIGH",evidence=[{"evidence_id":ev.id,"locator":"document","excerpt":filename}],stage="evidence",ref=f"EVD-{ev.id[:8]}")
    repo.save_artifact(project_id,"evidence_index",__import__("json").dumps({"documents":[{"evidence_id":ev.id,"name":filename,"document_type":cls.document_type,"status":ev.status,"chunks":len(chunks),"sensitivity":cls.sensitivity}],"intent_captured":intent_captured},indent=2),name="evidence_index.json",fmt="json",stage="evidence",generated_by="evidence_ingestion")
    return {"duplicate":False,"evidence_id":ev.id,"name":filename,"document_type":cls.document_type,"confidence":cls.confidence,"sensitivity":cls.sensitivity,"sensitivity_signals":cls.sensitivity_signals,"characters":len(text),"chunks":len(chunks),"status":ev.status,"sha256":digest[:16],"intent_captured":intent_captured,"message":(f"Ingested as {cls.document_type.upper()} ({cls.confidence.lower()} confidence), {len(chunks)} chunks indexed.")}
