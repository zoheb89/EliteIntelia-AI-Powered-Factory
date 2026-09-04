import json
import time, re, os
from c_invent.llm.capgemini import CapgeminiLLM
from c_invent.llm.gateway_bridge import build_llm
from c_invent.services.platforms import normalize_platform, derive_state, secret_status, secret_value
from c_invent.services.architecture_view import platform_fit, architecture_model
from c_invent.agents import prompts
from c_invent.services.poc_validation import build_validation_pack, detect_infinitespl

# Keys that indicate a placeholder/error payload rather than a real result.
# `_raw` was produced by the old JSON-repair fallback and is the shape that
# allowed a provider rate-limit message to be stored as delivery evidence.
_POISON_KEYS = ("_raw", "_repair_raw", "_repair_error", "error")

# Markers of a provider error that arrived with a success status code.
_PROVIDER_ERROR_MARKERS = (
    "api call limit exceeded", "rate limit", "quota exceeded", "usage limit",
    "too many requests", "please upgrade your plan", "insufficient credits",
)


def _reject_unusable(payload, stage_name: str) -> None:
    """Raise unless `payload` is a usable structured result.

    A stage must never be recorded as complete on top of an error message or an
    empty object: downstream stages consume it as evidence, and the customer
    sees it as delivered work.
    """
    if not isinstance(payload, dict) or not payload:
        raise RuntimeError(
            f"{stage_name} did not return a structured result. Nothing was persisted."
        )
    poisoned = [k for k in _POISON_KEYS if k in payload]
    if poisoned:
        detail = str(payload.get(poisoned[0]) or "")[:300]
        raise RuntimeError(
            f"{stage_name} failed: the AI provider did not return usable content. {detail}"
        )
    blob = json.dumps(payload).lower()
    if len(blob) < 1500:
        for marker in _PROVIDER_ERROR_MARKERS:
            if marker in blob:
                raise RuntimeError(
                    f"{stage_name} failed: the AI provider rejected the request. "
                    f"{json.dumps(payload)[:300]}"
                )


def _as_text(value) -> str:
    """Render a value that may be a string, list or None as readable text."""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(v) for v in value if v)
    return "" if value is None else str(value)


def _readable(tag: str) -> str:
    """`sql_database` -> `SQL database`. Tags are storage keys, not prose."""
    words = str(tag or "").replace("-", "_").split("_")
    acronyms = {"ai", "ml", "erp", "crm", "api", "sql", "bi", "sla", "kpi", "pii", "etl"}
    out = []
    for i, w in enumerate(words):
        if not w:
            continue
        out.append(w.upper() if w.lower() in acronyms
                   else (w.capitalize() if i == 0 else w.lower()))
    return " ".join(out) or str(tag)


#: What each missing-information check actually means to a delivery lead. The
#: raw keys ("sample_data", "sla") were being shown to customers as unknowns.
_MISSING_PROMPTS = {
    "business_owner": "The business owner or sponsor for this initiative has not been identified.",
    "source_inventory": "No inventory of source systems or databases has been supplied.",
    "sample_data": "No sample data or extracts have been provided for profiling.",
    "volume": "Data volumes have not been stated, so sizing cannot be evidenced.",
    "sla": "Service levels — latency, refresh windows, batch timings — have not been stated.",
    "security": "Security, privacy and data-classification requirements have not been described.",
    "integration": "Required integrations and interfaces have not been described.",
    "acceptance": "Acceptance criteria and success measures have not been agreed.",
}


class Orchestrator:
    def __init__(self, settings, store):
        self.settings=settings
        self.store=store
        # Multi-provider when LLM_PROVIDERS is configured, so one provider's
        # quota exhaustion no longer degrades every stage; otherwise unchanged.
        self.llm=build_llm(settings)

    def _run(self, pid, agent, instructions, context="", evidence_limit=16000, use_documents=True, max_tokens=1200):
        p = self.store.get_project(pid)
        docs = self.store.documents(pid) if use_documents else []
        evidence_parts = []
        remaining = max(0, evidence_limit)
        for d in docs:
            if remaining <= 0:
                break
            chunk = (d.get("text") or "")[:min(6000, remaining)]
            evidence_parts.append(f"DOCUMENT {d['name']}:\n{chunk}")
            remaining -= len(chunk)
        evidence = "\n\n".join(evidence_parts)
        combined = "\n\n".join(x for x in (evidence, context) if x)
        combined = combined[:evidence_limit + 12000]
        user = f"""PROJECT:
{json.dumps(p, indent=2)}

EVIDENCE / PRIOR OUTPUT:
{combined}

TASK:
{instructions}

Return a top-level JSON object with 'summary', 'facts', 'assumptions', and task-specific sections. Return JSON only."""
        _started = time.time()
        try:
            out = self.llm.invoke_json(
                user,
                instructions,
                extra_params={
                    "maxTokens": max_tokens,
                    "temperature": 0.0,
                    "streaming": False,
                    "topP": 0.9,
                },
            )
            # Validate before persisting: every agent flows through here, so this
            # is the single place that stops an error payload becoming evidence.
            _reject_unusable(out, agent.replace("_", " ").title())
            # Stamp what actually produced this. Only failures were ever
            # marked, so a successful AI run carried no proof it was AI and
            # the UI had nothing truthful to show. Recorded at the single
            # point where a model response has been received and validated.
            if isinstance(out, dict):
                settings = getattr(self.llm, "settings", None)
                out.setdefault("generation_mode", "ai")
                out.setdefault("ai_provider", getattr(settings, "llm_provider", "") or "")
                out.setdefault("ai_model", getattr(settings, "llm_model", "") or "")
                out.setdefault("ai_elapsed_ms", int((time.time() - _started) * 1000))
                out.setdefault("ai_client", type(self.llm).__name__)
            self.store.save_run(pid, agent, "success", instructions, out)
            self.store.add_audit(pid, f"llm:{agent}", "success", json.dumps(out)[:4000])
            return out
        except Exception as e:
            out = {"error": str(e)}
            self.store.save_run(pid, agent, "failed", instructions, out)
            self.store.add_audit(pid, f"llm:{agent}", "failed", str(e))
            return out

    def _success(self, pid, agent):
        return self.store.latest_run(pid, agent, success_only=True)

    def _fresh_after(self, run, dependency):
        if not run or not dependency:
            return False
        return run.get("created_at", "") >= dependency.get("created_at", "")

    def _current_approval(self, pid, artifact_type, run):
        approval = self.store.latest_approval(pid, artifact_type) if hasattr(self.store, "latest_approval") else None
        return bool(approval and run and approval.get("created_at", "") >= run.get("created_at", ""))

    def capture_intake(self, pid):
        """Create a factual Intake Pack from customer-supplied input only. No LLM inference."""
        project = self.store.get_project(pid)
        docs = self.store.documents(pid)
        pack = {
            "project": {"id": project["id"], "name": project["name"], "domain": project.get("domain") or "Unknown"},
            "customer_intent": project.get("description") or "",
            "customer_material": [
                {"name": d["name"], "mime_type": d.get("mime_type", ""), "size_bytes": d.get("size_bytes", 0)}
                for d in docs
            ],
            "scope_status": "Captured from customer input; not AI-inferred.",
            "unknowns": [
                "Current-state technical inventory has not yet been validated.",
                "Target platform and execution environment must be confirmed during Discovery.",
            ],
        }
        self.store.save_artifact(pid, "intake_pack", "intake_pack.json", "json", json.dumps(pack, indent=2, ensure_ascii=False))
        self.store.add_audit(pid, "delivery:intake_pack", "success", json.dumps(pack)[:4000])
        return pack

    def _target_platform_evidence(self, discovery_output):
        """Return target direction separately from target selection/provisioning.

        Discovery is allowed to capture a customer desired direction (for example,
        Azure/Databricks) without treating it as a selected or provisioned platform.
        Older discovery records that lack the explicit status are conservatively
        treated as customer-stated direction.
        """
        d = discovery_output or {}
        raw = json.dumps(d, ensure_ascii=False).lower()
        direction = d.get("target_platform_direction") or d.get("target_platform")
        if not direction:
            known = [
                ("databricks", "Databricks"), ("snowflake", "Snowflake"),
                ("microsoft fabric", "Microsoft Fabric"), ("fabric", "Microsoft Fabric"),
                ("synapse", "Azure Synapse"), ("bigquery", "BigQuery"),
                ("redshift", "Amazon Redshift"),
            ]
            for needle, label in known:
                if needle in raw:
                    direction = label
                    break
        direction = direction or "Unknown / to be confirmed"
        status = str(d.get("target_platform_status") or "").strip().lower()
        allowed = {"unknown", "customer_stated_direction", "selected_not_provisioned", "selected_and_existing", "provisioned_verified"}
        if status not in allowed:
            status = "customer_stated_direction" if direction != "Unknown / to be confirmed" else "unknown"
        evidence = d.get("target_platform_decision_evidence") or []
        if not isinstance(evidence, list):
            evidence = [str(evidence)]
        return {
            "target_platform": direction,
            "target_platform_status": status,
            "target_platform_decision_evidence": [str(x) for x in evidence if str(x).strip()],
        }

    def run_environment_assessment(self, pid, capability_report=None):
        """Assess the customer environment only from project-owned platform state.

        The global C INVENT Databricks adapter is deliberately ignored here. This
        prevents a POC workspace from being mistaken for a customer's provisioned
        target. Customer verification is performed only after Platform Workspace
        records a selected target and the appropriate connection/provisioning state.
        """
        discovery = self._success(pid, "discovery")
        if not discovery:
            return {"error": "Environment Assessment requires a successful Discovery result."}
        d = discovery.get("output") if isinstance(discovery.get("output"), dict) else {}
        project = self.store.get_project(pid)
        pcfg = project.get("platform_config") or {}
        target = normalize_platform(pcfg.get("platform")) if pcfg.get("platform") else ""
        discovery_info = self._target_platform_evidence(d)
        if not target:
            target = discovery_info["target_platform"] if discovery_info["target_platform"] != "Unknown / to be confirmed" else "Unknown / to be confirmed"
        decision_status = pcfg.get("decision_status", "not_selected")
        state = derive_state(pcfg)

        target_status = {
            "not_selected": "customer_stated_direction",
            "selected": "selected_not_provisioned",
        }.get(decision_status, discovery_info.get("target_platform_status", "unknown"))
        if state["state"] == "VERIFIED":
            target_status = "provisioned_verified"

        capability = {
            "applicable": False,
            "scope": "customer_environment",
            "state": state["state"],
            "reason": state["next_action"],
            "customer_platform_configured": bool(pcfg.get("platform")),
            "customer_endpoint_present": bool(pcfg.get("endpoint")),
            "credential_status": secret_status(pcfg),
            "cinvent_control_plane_adapter": "excluded_from_customer_evidence",
        }

        # Actual customer capability verification currently has a concrete adapter
        # for Databricks. Other platforms still receive a truthful generic state
        # and provisioning plan, rather than fabricated capability evidence.
        if target == "Databricks" and state["state"] == "READY_TO_VERIFY":
            try:
                from c_invent.databricks.client import DatabricksClient
                ref = [x.strip() for x in str(pcfg.get("credential_ref") or "").split(",") if x.strip()]
                token = secret_value(ref[-1]) if ref else ""
                customer_db = DatabricksClient(self.settings, host=pcfg.get("endpoint"), token=token)
                raw = customer_db.capability_report()
                capability = {"applicable": True, "scope": "customer_environment", **raw}
                if raw.get("configured") and not raw.get("error"):
                    pcfg["verified_at"] = self.store.now()
                    pcfg["verification_snapshot"] = raw
                    self.store.save_platform_config(pid, pcfg)
                    state = derive_state(pcfg)
                    target_status = "provisioned_verified"
                    capability["verification"] = "verified_customer_environment"
            except Exception as exc:
                capability = {"applicable": True, "scope": "customer_environment", "verification": "failed", "error": str(exc)}

        provisioning_path = (
            "Select a final target platform in Solution Blueprint/Platform Workspace before provisioning." if not pcfg.get("platform") else
            "Connect and verify an existing customer environment using customer-owned credentials." if pcfg.get("environment_mode") == "existing" else
            "Generate, review and approve the platform-specific cloud/IaC provisioning plan; execute with authorized customer/cloud credentials, then verify." if pcfg.get("environment_mode") == "provision" else
            state["next_action"]
        )
        context = json.dumps({
            "discovery": {k: d.get(k) for k in ("summary", "domain", "systems", "sources", "requirements", "unknowns") if k in d},
            "customer_platform": {"platform": target, "decision_status": decision_status, "onboarding_state": state, "config": {k:v for k,v in pcfg.items() if k not in ("verification_snapshot",)}},
            "customer_environment_capability_evidence": capability,
            "provisioning_path": provisioning_path,
        }, ensure_ascii=False, separators=(",", ":"))[:7000]
        result = self._run(pid, "environment_assessment", prompts.ENVIRONMENT_ASSESSMENT, context, evidence_limit=5000, use_documents=False, max_tokens=900)
        if isinstance(result, dict) and result.get("error"):
            # Environment Assessment is a lifecycle evidence gate, not an LLM gate.
            # If the AI provider times out, persist a deterministic snapshot so the
            # user still sees the platform state and can continue with human action.
            result = {
                "summary": "Environment Assessment created from customer platform configuration and deterministic evidence. AI enrichment was unavailable for this run.",
                # `target` may arrive as a list, which rendered the Python
                # literal "['Databricks']" on the board.
                "facts": [f"Target platform: {_as_text(target) or 'not selected'}",
                          f"Onboarding state: {_readable(state['state'])}"],
                "assumptions": [],
                "target_platform": target or "Unknown / to be confirmed",
                "target_platform_status": target_status,
                "target_platform_decision_evidence": discovery_info["target_platform_decision_evidence"],
                "customer_environment_status": state["state"].lower(),
                "current_environment": [_readable(x) for x in d.get("systems", [])],
                "access": {"customer_environment": "verified" if state["state"] == "VERIFIED" else "not_verified"},
                "capabilities": capability,
                "provisioning_path": provisioning_path,
                "platform_onboarding_state": state,
                "constraints": ["AI enrichment unavailable; deterministic evidence retained."],
                "gaps": [state["next_action"]] if state["state"] not in {"VERIFIED", "PLAN_READY"} else [],
                # Discovery artifacts written before unknowns were phrased as
                # sentences still hold raw keys such as "sla"; render those.
                "unknowns": [_MISSING_PROMPTS.get(u, _readable(u) if "_" in str(u)
                                                  and " " not in str(u) else u)
                             for u in d.get("unknowns", [])[:10]],
                "ai_enrichment": "not_available_for_this_run",
            }
            self.store.save_run(pid, "environment_assessment", "success", context, result)
            self.store.add_audit(pid, "environment:deterministic_fallback", "success", json.dumps(result)[:4000])
            self.store.save_artifact(pid, "environment_assessment", "environment_assessment.json", "json", json.dumps(result, indent=2, ensure_ascii=False))
            return result
        if isinstance(result, dict) and not result.get("error"):
            result["target_platform"] = target
            result["target_platform_status"] = target_status
            result["target_platform_decision_evidence"] = discovery_info["target_platform_decision_evidence"] + ([f"Platform Workspace selected {target} for this engagement."] if pcfg.get("platform") else [])
            result["customer_environment_status"] = "verified_customer_environment" if state["state"] == "VERIFIED" else state["state"].lower()
            result["platform_capability_evidence"] = capability
            result["provisioning_path"] = provisioning_path
            result["platform_onboarding_state"] = state
            self.store.save_run(pid, "environment_assessment", "success", context, result)
            self.store.add_audit(pid, "environment:customer_capability_snapshot", "success", json.dumps(capability)[:4000])
            self.store.save_artifact(pid, "environment_assessment", "environment_assessment.json", "json", json.dumps(result, indent=2, ensure_ascii=False))
        return result

    def generate_platform_plan(self, pid):
        """Create a reviewable, platform-neutral provisioning/connection plan."""
        project = self.store.get_project(pid)
        cfg = project.get("platform_config") or {}
        state = derive_state(cfg)
        if not cfg.get("platform") or cfg.get("decision_status") != "selected":
            return {"error": "Select and confirm the final target platform before generating a platform plan."}
        platform = normalize_platform(cfg.get("platform"))
        cloud = cfg.get("cloud") or "To be selected"
        mode = cfg.get("environment_mode") or "To be selected"
        plan = {
            "platform": platform,
            "cloud": cloud,
            "environment_mode": mode,
            "onboarding_state": state,
            "facts": [
                f"Customer target platform selected: {platform}.",
                f"Deployment path selected: {mode}.",
            ],
            "human_inputs_required": [
                "Customer/cloud subscription or account ownership and region.",
                "Network/connectivity decision for source systems.",
                "Identity/authentication and secret-manager configuration.",
                "Security, governance, backup and recovery requirements.",
            ],
            "execution": [
                "Generate platform-specific configuration/IaC from approved architecture.",
                "Review and approve the plan.",
                "Execute with authorized customer/cloud credentials.",
                "Verify platform capabilities and refresh Environment Assessment.",
            ],
            "guardrail": "C INVENT does not claim a platform is provisioned because its own POC connector exists.",
            "timestamp": self.store.now(),
        }
        cfg["provisioning_plan"] = plan
        self.store.save_platform_config(pid, cfg)
        self.store.save_artifact(pid, "platform_plan", f"{platform.lower().replace(' ','_')}_platform_plan.json", "json", json.dumps(plan, indent=2))
        self.store.add_audit(pid, "platform:plan_generated", "success", json.dumps(plan)[:5000])
        return plan
    def run_discovery(self,pid,prompt,context=""):
        if not getattr(self.store, "artifact_exists", lambda *_: False)(pid, "intake_pack"):
            return {"error": "Discovery requires a completed Intake Pack."}
        # Discovery is the first AI delivery stage. Keep the request intentionally
        # small so the Capgemini gateway can answer reliably before we fan out into
        # Assessment/Blueprint/Engineering. Larger evidence is consumed by later
        # stages after Discovery has produced a structured intermediate result.
        docs = self.store.documents(pid)
        compact_system = (
            "You are the C INVENT Discovery Agent. Analyze only supplied evidence. "
            "Do not invent facts. Return compact JSON only. Use short arrays and "
            "short phrases. Include: summary, domain, objectives, processes, "
            "actors, systems, sources, requirements, assumptions, unknowns, next_steps."
        )
        evidence=[]
        budget=4200
        for d in docs:
            if budget <= 0:
                break
            txt=(d.get("text") or "")[:min(1400,budget)]
            if txt:
                evidence.append(f"DOCUMENT {d['name']}:\n{txt}")
                budget -= len(txt)
        combined="\n\n".join(x for x in evidence if x)
        if context:
            combined += ("\n\n" if combined else "") + context[:1800]
        user=(
            "CUSTOMER INTENT:\n" + prompt[:2600] +
            "\n\nSUPPLIED EVIDENCE:\n" + (combined or "No supporting documents supplied yet.") +
            "\n\nReturn concise JSON with exactly these core fields: "
            "summary, domain, objectives, processes, actors, systems, sources, "
            "requirements, assumptions, unknowns, next_steps, target_platform_direction, target_platform_status, target_platform_decision_evidence."
        )
        try:
            out=self.llm.invoke_json(
                user, compact_system,
                extra_params={
                    "maxTokens": 350,
                    "temperature": 0.0,
                    "streaming": False,
                    "topP": 0.9,
                },
            )
            # If the gateway still times out, invoke_json already performs one
            # bounded retry. Persist only a successful structured discovery.
            if isinstance(out,dict) and "error" in out and len(out)==1:
                raise RuntimeError(out["error"])
            # Defence in depth: never persist a payload that is not a usable
            # discovery record, whatever produced it.
            _reject_unusable(out, "Discovery")
            self.store.save_run(pid,"discovery","success",compact_system,out)
            # Persist the artifact too. Without this the AI-success path produced a
            # completed stage with no inspectable/downloadable Discovery evidence.
            self.store.save_artifact(
                pid, "discovery", "discovery.json", "json",
                json.dumps(out, indent=2, ensure_ascii=False),
            )
            self.store.add_audit(pid,"llm:discovery","success",json.dumps(out)[:4000])
            return out
        except Exception as e:
            # Discovery is the first delivery stage and must never hard-block the
            # lifecycle when the AI provider is unavailable or unconfigured. The
            # universal intake analyzer already derives structured signals without
            # an LLM, so persist those as an explicitly-labelled deterministic
            # discovery result (same contract as the environment/metadata stages).
            fallback = self._deterministic_discovery(pid, prompt, str(e))
            self.store.save_run(pid, "discovery", "success", compact_system, fallback)
            self.store.save_artifact(
                pid, "discovery", "discovery.json", "json",
                json.dumps(fallback, indent=2, ensure_ascii=False),
            )
            self.store.add_audit(pid, "discovery:deterministic_fallback", "success", json.dumps(fallback)[:4000])
            return fallback

    def _deterministic_discovery(self, pid, prompt, reason):
        """Build a structured discovery result from intake signals, without the LLM.

        Every field is traceable to supplied evidence; nothing is invented. The
        result is explicitly marked so the UI and downstream stages can show that
        AI enrichment did not run.
        """
        analysis = {}
        try:
            from c_invent.services.universal_intake import analyze_intake
            docs = self.store.documents(pid)
            # `prompt` is this stage's own instruction text. Passing it here
            # made it part of the analysed corpus, so the instruction came back
            # out as a customer requirement ("Analyze the supplied engagement
            # evidence and identify the business intent..."). Only the
            # customer's own words belong in the analysis.
            project = self.store.get_project(pid) or {}
            intent = (project.get("description") or project.get("intent")
                      or project.get("name") or "")
            analysis = analyze_intake(intent, docs) or {}
        except Exception:
            analysis = {}

        # Requirement tables (RFI/RFP trackers) are the richest deterministic
        # evidence a bid team supplies, and prose extraction cannot see them:
        # a cell reading "Real-time parcel tracking" has no modal verb to match.
        tabular = {}
        try:
            from core.tabular_intake import extract_documents, summarize as tabular_summary
            tabular = extract_documents(self.store.documents(pid))
        except Exception:
            tabular = {}

        # Every domain with a single keyword hit was reported, so a healthcare
        # questionnaire came back as healthcare + insurance + retail +
        # financial services + manufacturing. Keep only those close to the
        # strongest signal.
        domain_signals = [d for d in analysis.get("domain_signals", []) if d.get("domain")]
        domains = []
        if domain_signals:
            top = max(d.get("signal_count", 0) for d in domain_signals) or 1
            domains = [d["domain"] for d in domain_signals
                       if d.get("signal_count", 0) >= max(2, top * 0.4)][:3]
            domains = domains or [domain_signals[0]["domain"]]

        use_cases = [u.get("use_case") for u in analysis.get("candidate_use_cases", []) if u.get("use_case")]
        sources = analysis.get("source_families_detected", []) or []
        requirements = analysis.get("requirements_signals", []) or []
        missing = analysis.get("missing_information", []) or []
        platform = analysis.get("target_platform_direction", "unknown")

        # Structured rows are stronger evidence than sentence matching, so they
        # lead the requirement list and carry their own source locator.
        table_requirements = []
        for r in (tabular.get("requirements") or []):
            ref = r.get("ref")
            category = r.get("category")
            label = f"[{ref}] " if ref else ""
            suffix = f" ({category})" if category else ""
            table_requirements.append(f"{label}{r['text']}{suffix}")

        combined_requirements = table_requirements + [
            r for r in requirements if r not in table_requirements
        ]

        table_note = ""
        if tabular.get("found"):
            try:
                table_note = " " + tabular_summary(tabular)
            except Exception:
                table_note = ""

        unanswered = tabular.get("unanswered_count") or 0
        extra_unknowns = (
            [f"{unanswered} requirement rows in the supplied tracker have no response yet."]
            if unanswered else []
        )

        return {
            "summary": (
                "Discovery derived deterministically from captured intake evidence. "
                "AI enrichment was unavailable for this run, so only directly observed "
                "signals are recorded." + table_note
            ),
            "domain": domains or ["unknown"],
            # Detected capability themes are not stated objectives, and saying
            # so is the difference between evidence and a guess. Processes and
            # systems stay empty rather than repeating the same list under a
            # second heading, which is what made the board look padded.
            "objectives": ([f"Candidate focus area: {_readable(u)}" for u in use_cases]
                           or ["Confirm business objectives in a discovery workshop"]),
            "processes": [],
            "actors": [],
            "systems": [],
            "sources": [_readable(x) for x in sources],
            "requirements": combined_requirements,
            "assumptions": [],
            "unknowns": ([_MISSING_PROMPTS.get(m, f"{_readable(m)} has not been established.")
                           for m in missing]
                          or ["Detailed scope pending customer confirmation"]) + extra_unknowns,
            "next_steps": [
                "Run a discovery workshop to confirm objectives, actors and processes",
                "Collect a structured source inventory and sample data",
                "Configure the AI provider to enable full discovery enrichment",
            ],
            "target_platform_direction": [platform] if platform and platform != "unknown" else [],
            "target_platform_status": analysis.get("target_platform_status", "unknown"),
            "target_platform_decision_evidence": ["Customer-stated direction only; not a selection."],
            "generation_mode": "deterministic_evidence_only",
            "ai_enrichment": "unavailable",
            "ai_enrichment_reason": reason[:400],
            "guardrails": analysis.get("guardrails", []),
            "extracted_tables": tabular.get("tables", []),
            "requirement_table_summary": {
                "requirement_count": tabular.get("requirement_count", 0),
                "answered": tabular.get("answered_count", 0),
                "unanswered": tabular.get("unanswered_count", 0),
                "categories": tabular.get("categories", {}),
            } if tabular.get("found") else {},
        }

    def run_assessment(self,pid):
        """Build an evidence-first current-state assessment without making the LLM a gate.

        Assessment is a delivery-control decision, not another generic AI generation step.
        The deterministic layer evaluates the discovered use case, data/source evidence,
        platform evidence and governance/delivery unknowns. An optional AI enrichment may
        be added later, but a Capgemini gateway timeout must never block the lifecycle.
        """
        discovery = self._success(pid, "discovery")
        environment = self._success(pid, "environment_assessment")
        if not discovery:
            return {"error": "Assessment requires a successful Discovery result."}
        if not environment or not self._fresh_after(environment, discovery):
            return {"error": "Assessment requires a current Environment Assessment after the latest Discovery."}

        d = discovery.get("output") if isinstance(discovery.get("output"), dict) else {}
        e = environment.get("output") if isinstance(environment.get("output"), dict) else {}

        def items(key, source=d):
            value = source.get(key, []) if isinstance(source, dict) else []
            if isinstance(value, list):
                return [str(x) for x in value if str(x).strip()]
            if value is None:
                return []
            return [str(value)]

        def unique(values):
            out=[]
            seen=set()
            for v in values:
                k=v.strip().lower()
                if k and k not in seen:
                    seen.add(k); out.append(v.strip())
            return out

        objectives = items("objectives")
        processes = items("processes")
        actors = items("actors")
        systems = items("systems")
        sources = items("sources")
        requirements = items("requirements")
        assumptions = items("assumptions")
        unknowns = unique(items("unknowns"))
        target = e.get("target_platform") or "Unknown / to be confirmed"
        target_status = e.get("target_platform_status") or "unknown"
        current_env = e.get("current_environment") or systems
        access = e.get("access") or {}
        capabilities = e.get("capabilities") or e.get("platform_capability_evidence") or {}
        constraints = items("constraints", e)
        env_gaps = items("gaps", e)
        env_unknowns = items("unknowns", e)

        business_evidence = unique([
            "Customer objective is captured." if d.get("summary") else "Customer objective is not yet evidenced.",
            f"{len(objectives)} objective(s) identified." if objectives else "No structured objectives identified.",
            f"{len(processes)} process/use-case item(s) identified." if processes else "No business processes/use cases identified.",
            f"{len(actors)} stakeholder/actor group(s) identified." if actors else "Stakeholder groups are not yet evidenced.",
            f"{len(requirements)} requirement item(s) identified." if requirements else "Requirements are not yet sufficiently structured.",
        ])
        if objectives and processes and actors and requirements:
            business_status = "READY WITH OPEN DECISIONS"
        elif objectives or processes or requirements:
            business_status = "CONDITIONAL"
        else:
            business_status = "INSUFFICIENT EVIDENCE"

        data_findings = unique([
            f"Current system evidence: {', '.join(systems[:4])}." if systems else "Current source system is not yet evidenced.",
            f"Source/data evidence: {', '.join(sources[:5])}." if sources else "Source inventory is not yet available.",
            "Table/schema inventory is not yet available." if not any("table" in u.lower() or "schema" in u.lower() for u in unknowns) else "Table/schema inventory is identified as an open item.",
        ])
        data_blockers = [u for u in unknowns if any(k in u.lower() for k in ("volume", "cdc", "table", "schema", "data quality", "retention"))]
        if systems and sources and not data_blockers:
            data_status = "CONDITIONAL"
        elif systems or sources:
            data_status = "CONDITIONAL / EVIDENCE REQUIRED"
        else:
            data_status = "INSUFFICIENT EVIDENCE"

        capability_configured = bool(capabilities.get("configured")) if isinstance(capabilities, dict) else False
        capability_errors = []
        if isinstance(capabilities, dict):
            for key, value in capabilities.items():
                if isinstance(value, dict) and value.get("error"):
                    capability_errors.append(f"{key}: {value.get('error')}")
        poc_adapter = isinstance(capabilities, dict) and bool(capabilities.get("cinvent_poc_adapter_configured"))
        if target_status == "customer_stated_direction":
            platform_findings = unique([
                f"Customer-stated target direction: {target}.",
                "Target is not yet a governed selection/provisioned customer environment.",
                "C INVENT POC/control-plane connectivity is separate and is not customer-environment evidence." if poc_adapter else "No customer-environment platform capability evidence is available yet.",
                "Provisioning/connection path must be resolved after architecture and approval.",
                *[str(x) for x in env_gaps[:5]],
                *capability_errors[:5],
            ])
            platform_status = "TARGET DIRECTION ONLY — NOT PROVISIONED / VERIFIED"
        elif target_status == "selected_not_provisioned":
            platform_findings = unique([
                f"Target platform selected: {target}.",
                "Customer target environment is not yet provisioned or verified.",
                "Platform Workspace must connect or provision the approved target before capability evidence can be claimed.",
                *[str(x) for x in env_gaps[:5]],
                *capability_errors[:5],
            ])
            platform_status = "SELECTED — PROVISIONING / CONNECTION REQUIRED"
        else:
            platform_findings = unique([
                f"Target platform: {target}." if target != "Unknown / to be confirmed" else "Target platform is not yet established.",
                "Customer-environment capability evidence verified through the configured adapter." if capability_configured else "C INVENT does not have verified customer-environment connectivity in this assessment.",
                *[str(x) for x in env_gaps[:5]],
                *capability_errors[:5],
            ])
            if target == "Databricks" and capability_configured and not capability_errors:
                platform_status = "VERIFIED / CONDITIONAL ON REQUIRED PERMISSIONS"
            elif target == "Unknown / to be confirmed":
                platform_status = "NOT YET ASSESSABLE"
            else:
                platform_status = "CONDITIONAL"

        governance_keywords = ("security", "privacy", "phi", "pii", "compliance", "regulat", "rbac", "access", "retention", "rpo", "rto", "sla")
        governance_unknowns = [u for u in unknowns + env_unknowns if any(k in u.lower() for k in governance_keywords)]
        governance_findings = unique([
            "Governance/compliance requirements are referenced in Discovery." if any(any(k in x.lower() for k in governance_keywords) for x in requirements + assumptions) else "Governance requirements are not sufficiently evidenced.",
            *governance_unknowns[:6],
        ])
        governance_status = "CONDITIONAL" if governance_unknowns or not requirements else "READY WITH REVIEW"

        blockers = unique(data_blockers + governance_unknowns + env_gaps)[:12]
        if business_status.startswith("INSUFFICIENT") or platform_status == "NOT YET ASSESSABLE":
            decision = "NO-GO / MORE DISCOVERY REQUIRED"
        elif blockers:
            decision = "CONDITIONAL GO"
        else:
            decision = "GO TO ARCHITECTURE"

        result = {
            "assessment_type": "evidence_based_current_state",
            "summary": f"Current-state delivery readiness assessment based on the latest Discovery and Environment Assessment. Decision: {decision}.",
            "decision": decision,
            "dimensions": {
                "business_use_case": {
                    "status": business_status,
                    "what_is_assessed": "Business objectives, use cases/processes, stakeholders and stated requirements.",
                    "evidence": business_evidence,
                    "source": ["Customer Intent", "Discovery Run"],
                },
                "data_and_sources": {
                    "status": data_status,
                    "what_is_assessed": "Current systems, source/data evidence and whether the information needed for migration/data design is available.",
                    "evidence": data_findings,
                    "open_items": data_blockers[:8],
                    "source": ["Discovery Run", "Customer Documents"],
                },
                "platform_and_environment": {
                    "status": platform_status,
                    "what_is_assessed": "Discovered target/current platform plus verified access and capability evidence; this does not infer missing capabilities.",
                    "current_environment": current_env,
                    "target_platform": target,
                    "target_platform_status": target_status,
                    "access": access,
                    "capabilities": capabilities,
                    "provisioning_path": e.get("provisioning_path"),
                    "evidence": platform_findings,
                    "source": ["Discovery Run", "Environment Assessment"],
                },
                "governance_and_delivery": {
                    "status": governance_status,
                    "what_is_assessed": "Security, privacy, compliance, SLA, RPO/RTO, access, retention and delivery dependencies visible in the evidence.",
                    "evidence": governance_findings,
                    "open_items": governance_unknowns[:8],
                    "source": ["Discovery Run", "Environment Assessment"],
                },
            },
            "risks": blockers[:10],
            "assumptions": assumptions[:10],
            "unknowns": unique(unknowns + env_unknowns)[:15],
            "recommended_next_actions": [
                "Resolve the listed evidence gaps before final architecture decisions." if blockers else "Proceed to architecture with the recorded evidence.",
                "Convert any customer-stated target direction into an explicit architecture decision before provisioning.",
                "Use Platform Workspace to connect an existing customer environment or execute an approved cloud/IaC provisioning plan after architecture approval.",
                "Keep C INVENT POC/control-plane connectivity separate from customer-environment evidence.",
                "Require human approval before downstream metadata and engineering generation.",
            ],
            "traceability": {
                "discovery_run_id": discovery.get("id"),
                "environment_assessment_run_id": environment.get("id"),
                "discovery_created_at": discovery.get("created_at"),
                "environment_assessment_created_at": environment.get("created_at"),
                "assessment_mode": "deterministic_evidence_first",
                "ai_dependency": "not required for lifecycle progression",
            },
        }
        content=json.dumps(result, indent=2, ensure_ascii=False)
        self.store.save_run(pid, "assessment", "success", "Deterministic evidence-first current-state assessment", result)
        self.store.save_artifact(pid, "assessment", "current_state_assessment.json", "json", content)
        self.store.add_audit(pid, "delivery:assessment", "success", content[:6000])
        return result

    def run_blueprint(self,pid):
        """Generate a compact blueprint from the persisted Discovery result.

        Blueprint intentionally bypasses the generic _run() wrapper because that
        wrapper adds the whole project object and can make Capgemini requests much
        larger than necessary. The verified Capgemini endpoint is sensitive to
        request size/latency, so Blueprint is a small second-stage call.
        """
        discovery = self.store.latest_run(pid, "discovery")
        assessment = self.store.latest_run(pid, "assessment")
        environment = self.store.latest_run(pid, "environment_assessment")
        if not discovery or not isinstance(discovery.get("output"), dict):
            return {"error": "Blueprint requires a successful Discovery result."}
        if not environment or not self._fresh_after(environment, discovery):
            return {"error": "Blueprint requires a current Environment Assessment result."}
        if not assessment or not self._fresh_after(assessment, environment):
            return {"error": "Blueprint requires a current Assessment result after Environment Assessment."}

        def pick(obj, keys):
            if not obj or not isinstance(obj.get("output"), dict):
                return None
            src = obj["output"]
            return {k: src[k] for k in keys if k in src}

        # Keep only fields that materially influence architecture. This avoids
        # repeatedly sending large discovery documents to the LLM.
        d = pick(discovery, [
            "summary", "domain", "objectives", "processes", "systems",
            "sources", "requirements", "assumptions", "unknowns"
        ]) or {}
        a = pick(assessment, [
            "summary", "current_state", "maturity", "complexity", "risks",
            "dependencies", "recommendations", "unknowns"
        ]) if assessment else None
        e = pick(environment, [
            "summary", "target_platform", "current_environment", "access",
            "capabilities", "constraints", "gaps", "unknowns"
        ]) if environment else None

        prior = json.dumps({"discovery": d, "environment_assessment": e, "assessment": a},
                           ensure_ascii=False, separators=(",", ":"))[:4500]

        system = """You are the C INVENT Solution/Enterprise Architect.
Create a concise target-state blueprint from the supplied Discovery/Assessment only.
Do not invent facts. Proposed technology choices must be labelled as recommendations
or assumptions. Return valid JSON only. Keep every array to at most 4 items.
Required keys: summary, target_architecture, data_flow, security_governance,
environments, delivery_phases, risks, decisions, open_questions."""
        user = """Create the target solution blueprint for this customer engagement.
Use the following structured evidence only:

""" + prior

        try:
            out = self.llm.invoke_json(
                user,
                system,
                extra_params={
                    "maxTokens": 420,
                    "temperature": 0.0,
                    "streaming": False,
                    "topP": 0.9,
                },
            )
            if isinstance(out, dict) and out.get("error") and len(out) == 1:
                raise RuntimeError(out["error"])
            # Presentation metadata is generated from persisted evidence, not from
            # a hard-coded Databricks choice. It makes the blueprint human-readable
            # while keeping the raw LLM blueprint intact for traceability.
            out = dict(out or {})
            discovery_out = discovery.get("output") if isinstance(discovery, dict) else {}
            assessment_out = assessment.get("output") if isinstance(assessment, dict) else {}
            out["platform_evaluation"] = platform_fit(discovery_out, assessment_out, out)
            out["architecture_visual"] = architecture_model(discovery_out, out)
            self.store.save_run(pid, "blueprint", "success", system, out)
            self.store.add_audit(pid, "llm:blueprint", "success", json.dumps(out)[:4000])
            return out
        except Exception as e:
            # A final ultra-compact retry is deliberately limited to Discovery's
            # essentials. This is preferable to resending the full customer context.
            try:
                fallback = json.dumps({
                    "summary": d.get("summary"),
                    "domain": d.get("domain"),
                    "objectives": d.get("objectives", [])[:3],
                    "requirements": d.get("requirements", [])[:3],
                    "systems": d.get("systems", [])[:3],
                    "unknowns": d.get("unknowns", [])[:3],
                }, ensure_ascii=False, separators=(",", ":"))[:2200]
                out = self.llm.invoke_json(
                    "Return a minimal enterprise blueprint as JSON for this evidence:\n" + fallback,
                    system,
                    extra_params={
                        "maxTokens": 260,
                        "temperature": 0.0,
                        "streaming": False,
                        "topP": 0.9,
                    },
                )
                if isinstance(out, dict) and not (out.get("error") and len(out) == 1):
                    out = dict(out)
                    discovery_out = discovery.get("output") if isinstance(discovery, dict) else {}
                    assessment_out = assessment.get("output") if isinstance(assessment, dict) else {}
                    out["platform_evaluation"] = platform_fit(discovery_out, assessment_out, out)
                    out["architecture_visual"] = architecture_model(discovery_out, out)
                    self.store.save_run(pid, "blueprint", "success", system, out)
                    self.store.add_audit(pid, "llm:blueprint", "success", json.dumps(out)[:4000])
                    return out
            except Exception as fallback_error:
                e = fallback_error
            out = {"error": str(e)}
            self.store.save_run(pid, "blueprint", "failed", system, out)
            self.store.add_audit(pid, "llm:blueprint", "failed", str(e))
            return out

    def run_metadata(self,pid):
        """Generate canonical metadata without allowing gateway latency to break the lifecycle.

        Metadata consumes the persisted Discovery + approved Blueprint only. It deliberately
        avoids resending customer documents because those documents can make a synchronous
        Capgemini invocation exceed the gateway window. If the provider is unavailable, a
        deterministic metadata skeleton is persisted as a successful, explicitly-labelled
        artifact. It contains only evidenced sources/entities and marks missing schema detail
        as an open item; it never fabricates tables or columns.
        """
        discovery=self._success(pid,"discovery")
        blueprint=self._success(pid,"blueprint")
        if not blueprint:
            return {"error": "Metadata requires a successful Architecture/Blueprint result."}
        if not self._current_approval(pid,"blueprint",blueprint):
            return {"error": "Metadata requires approval of the current Blueprint."}
        if discovery and not self._fresh_after(blueprint, discovery):
            return {"error": "Metadata requires a Blueprint generated after the latest Discovery."}

        d=(discovery or {}).get("output") if isinstance((discovery or {}).get("output"),dict) else {}
        b=blueprint.get("output") if isinstance(blueprint.get("output"),dict) else {}
        evidence={
            "discovery": {k:d.get(k) for k in ("summary","domain","systems","sources","requirements","unknowns") if k in d},
            "blueprint": {k:b.get(k) for k in ("summary","target_architecture","data_flow","security_governance","decisions","open_questions") if k in b},
        }
        prior=json.dumps(evidence,ensure_ascii=False,separators=(",",":"))[:6500]
        system=prompts.METADATA + "\nReturn compact JSON only. Do not invent tables, columns, keys or business definitions. If schema evidence is missing, use empty arrays and put the gap in assumptions/open_questions."
        try:
            out=self.llm.invoke_json(
                "Build canonical metadata from these approved structured artifacts only:\n"+prior,
                system,
                extra_params={"maxTokens":500,"temperature":0.0,"streaming":False,"topP":0.9},
            )
            if isinstance(out,dict) and not (out.get("error") and len(out)==1):
                self.store.save_run(pid,"metadata","success",system,out)
                self.store.save_artifact(pid,"metadata","metadata.json","json",json.dumps(out,indent=2,ensure_ascii=False))
                self.store.add_audit(pid,"llm:metadata","success",json.dumps(out)[:4000])
                return out
            raise RuntimeError(str(out))
        except Exception as exc:
            # Deterministic fallback: preserve the lifecycle and make the provider failure
            # visible without claiming unsupported schema facts.
            source_items=[]
            for key in ("systems","sources"):
                value=d.get(key,[])
                if isinstance(value,list): source_items.extend(str(x) for x in value if str(x).strip())
                elif value: source_items.append(str(value))
            source_items=list(dict.fromkeys(source_items))
            fallback={
                "summary":"Canonical metadata skeleton created from persisted Discovery and approved Architecture. AI enrichment was unavailable for this run.",
                "sources":source_items,
                "entities":[],
                "tables":[],
                "columns":[],
                "relationships":[],
                "transformations":[],
                "data_quality":["Schema-level data-quality rules require source inventory and profiling evidence."],
                "lineage":[],
                "target_layers":["Bronze","Silver","Gold"],
                "business_products":[],
                "assumptions":["Source schema, table and column definitions have not yet been evidenced."],
                "open_questions":["Provide source schema/table inventory and column metadata before implementation-level mappings are generated."],
                "ai_enrichment":"not_available_for_this_run",
                "provider_error":str(exc)[:500],
            }
            self.store.save_run(pid,"metadata","success",system,fallback)
            self.store.save_artifact(pid,"metadata","metadata.json","json",json.dumps(fallback,indent=2,ensure_ascii=False))
            self.store.add_audit(pid,"metadata:deterministic_fallback","success",json.dumps(fallback)[:4000])
            return fallback

    def run_poc_validation_pack(self, pid):
        """Create an evidence-safe InfiniteSPL validation harness.

        This is deliberately deterministic: it does not require the LLM and does not
        claim customer-source equivalence. It gives the engineering team a runnable
        Databricks synthetic harness when SQL Server/Oracle source access is not yet
        available.
        """
        project = self.store.get_project(pid)
        docs = self.store.documents(pid)
        if not detect_infinitespl(project, docs):
            return {"error": "InfiniteSPL validation profile was not detected. Upload the RFI/POC material or select an InfiniteSPL project."}
        spec, manifest, notebook = build_validation_pack(project, docs, catalog=(getattr(self.settings, "db_default_catalog", "main") or "main"))
        self.store.save_artifact(pid, "poc_validation_spec", "infinitespl_validation_spec.json", "json", json.dumps(spec, indent=2, ensure_ascii=False))
        self.store.save_artifact(pid, "poc_validation_manifest", "infinitespl_validation_manifest.json", "json", json.dumps(manifest, indent=2, ensure_ascii=False))
        self.store.save_artifact(pid, "poc_validation_notebook", "infinitespl_synthetic_validation.py", "python", notebook)
        self.store.save_run(pid, "poc_validation", "success", "Deterministic InfiniteSPL POC validation pack", manifest)
        self.store.add_audit(pid, "poc:infinitespl_validation_pack", "success", json.dumps(manifest)[:5000])
        return {"status": "SYNTHETIC_VALIDATION_READY", "manifest": manifest, "artifacts": ["infinitespl_validation_spec.json", "infinitespl_validation_manifest.json", "infinitespl_synthetic_validation.py"]}

    def run_qa(self,pid):
        engineering = self._success(pid, "engineering")
        if not engineering:
            return {"error": "Validation requires a successful Engineering result."}
        return self._run(pid,"qa",prompts.QA,
            json.dumps({"engineering": engineering.get("output")}, ensure_ascii=False)[:9000],
            evidence_limit=5000,use_documents=False,max_tokens=1200)
    def run_application_architecture(self,pid): return self._run(pid,"application",prompts.APP,evidence_limit=5000,use_documents=False,max_tokens=1200)
    def run_bi(self,pid): return self._run(pid,"bi",prompts.BI,evidence_limit=5000,use_documents=False,max_tokens=1200)
    def run_full_qa(self,pid): return self._run(pid,"full_qa",prompts.FULL_QA,evidence_limit=6000,use_documents=False,max_tokens=1200)

    def run_engineering(self, pid):
        """Generate production-safe Medallion engineering in resumable chunks.

        The Capgemini gateway is synchronous and has a server-side completion
        window. A single large engineering prompt is therefore intentionally
        avoided. Each component is small, persisted independently, and can be
        resumed after a timeout without regenerating successful components.
        """
        blueprint = self.store.latest_run(pid, "blueprint")
        metadata = self.store.latest_run(pid, "metadata")
        discovery = self.store.latest_run(pid, "discovery")
        if not blueprint or not isinstance(blueprint.get("output"), dict):
            return {"error": "Engineering requires a successful Blueprint result."}
        if not self._current_approval(pid, "blueprint", blueprint):
            return {"error": "Engineering requires approval of the current Blueprint."}
        if not metadata or not self._fresh_after(metadata, blueprint):
            return {"error": "Engineering requires Metadata generated after the approved Blueprint."}

        # The platform/environment gate is deliberately checked here too. This
        # protects direct URL navigation from bypassing the Control Plane.
        project = self.store.get_project(pid)
        pcfg = project.get("platform_config") or {}
        platform_state = derive_state(pcfg)
        if platform_state.get("state") != "VERIFIED":
            return {"error": "Engineering requires a verified customer target platform. Complete Platform Workspace verification first."}
        verified_at = str(pcfg.get("verified_at") or "")
        env_run = self.store.latest_run(pid, "environment_assessment")
        assessment = self.store.latest_run(pid, "assessment")
        if not env_run or (verified_at and env_run.get("created_at", "") < verified_at):
            return {"error": "Engineering requires Environment Assessment to be refreshed after customer platform verification."}
        if not assessment or assessment.get("created_at", "") < env_run.get("created_at", ""):
            return {"error": "Engineering requires Current-State Assessment to be refreshed from the latest Environment Assessment."}

        def output(run):
            return run.get("output") if isinstance(run, dict) else None

        b = output(blueprint) or {}
        m = output(metadata) or {}
        d = output(discovery) or {}
        evidence = {
            "blueprint": {k: b.get(k) for k in (
                "summary", "target_architecture", "data_flow", "security_governance",
                "environments", "delivery_phases", "decisions", "open_questions"
            ) if k in b},
            "metadata": {k: m.get(k) for k in (
                "summary", "sources", "entities", "tables", "columns", "relationships",
                "transformations", "data_quality", "lineage"
            ) if k in m},
            "discovery": {k: d.get(k) for k in (
                "domain", "objectives", "systems", "sources", "requirements"
            ) if k in d},
            "customer_platform": {
                "platform": pcfg.get("platform"),
                "cloud": pcfg.get("cloud"),
                "environment_mode": pcfg.get("environment_mode"),
                "verified_at": pcfg.get("verified_at"),
                "verification": (pcfg.get("verification_snapshot") or {}).get("verification"),
            },
        }

        state_artifact = self.store.latest_artifact(pid, "engineering_generation")
        generation = {}
        if state_artifact:
            try:
                generation = json.loads(state_artifact.get("content") or "{}")
            except Exception:
                generation = {}
        if generation.get("metadata_created_at") != metadata.get("created_at"):
            generation = {
                "generation_id": __import__("uuid").uuid4().hex,
                "status": "RUNNING",
                "metadata_created_at": metadata.get("created_at"),
                "blueprint_created_at": blueprint.get("created_at"),
                "started_at": self.store.now(),
                "completed_components": {},
                "attempts": {},
            }
        generation["status"] = "RUNNING"
        generation["updated_at"] = self.store.now()
        self.store.save_artifact(
            pid, "engineering_generation", "engineering_generation.json", "json",
            json.dumps(generation, indent=2, ensure_ascii=False),
        )

        component_specs = [
            ("bronze", "Design the Bronze/raw layer: ingestion pattern, raw/audit columns, idempotency and replay. Keep it implementation-ready but concise."),
            ("silver", "Design the Silver/conformed layer: cleansing, standardization, keys, validation and entity conformance."),
            ("gold", "Design the Gold/business layer: business-ready subject areas, metrics, semantic serving and downstream consumption."),
            ("data_quality", "Define practical data-quality rules, expectations, quarantine/error handling and observability."),
            ("orchestration", "Define orchestration using metadata-driven Lakeflow/Jobs patterns, dependencies, retries, parameters and scheduling."),
            ("testing", "Define engineering tests: schema, data-quality, transformation, reconciliation, lineage and deployment checks."),
            ("code_artifacts", "List the minimum reusable implementation artifacts to generate from metadata. Do not fabricate source columns."),
        ]

        system = (
            "You are the C INVENT Lead Data Engineer. Work only from the supplied approved "
            "structured evidence. Do not invent source tables, columns, business facts or "
            "customer capabilities. Return valid compact JSON only. Maximum 4 items per array. "
            "Design reusable metadata-driven Bronze/Silver/Gold engineering, idempotent ingestion, "
            "quality gates, auditability, lineage and testability."
        )
        results = generation.get("completed_components") or {}
        attempts = generation.get("attempts") or {}

        for name, task in component_specs:
            if isinstance(results.get(name), dict) and results[name]:
                continue
            compact_evidence = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
            prior = json.dumps({k: results[k] for k in results if k in {"bronze", "silver", "gold", "data_quality", "orchestration", "testing"}}, ensure_ascii=False, separators=(",", ":"))[:2200]
            user = (
                f"COMPONENT: {name}\nTASK: {task}\n\nAPPROVED EVIDENCE:\n"
                + compact_evidence[:4200]
                + ("\n\nALREADY GENERATED COMPONENTS:\n" + prior if prior else "")
            )
            attempts[name] = int(attempts.get(name, 0)) + 1
            generation["attempts"] = attempts
            self.store.save_artifact(
                pid, "engineering_generation", "engineering_generation.json", "json",
                json.dumps(generation, indent=2, ensure_ascii=False),
            )
            try:
                out = self.llm.invoke_json(
                    user,
                    system,
                    extra_params={
                        "maxTokens": 240 if name != "code_artifacts" else 220,
                        "temperature": 0.0,
                        "streaming": False,
                        "topP": 0.9,
                    },
                )
                if not isinstance(out, dict) or (out.get("error") and len(out) == 1):
                    raise RuntimeError(out.get("error", "Model returned an invalid engineering component."))
                results[name] = out
                generation["completed_components"] = results
                generation["updated_at"] = self.store.now()
                self.store.save_artifact(
                    pid, "engineering_generation", "engineering_generation.json", "json",
                    json.dumps(generation, indent=2, ensure_ascii=False),
                )
                self.store.save_artifact(
                    pid, f"engineering_{name}", f"{name}.json", "json",
                    json.dumps(out, indent=2, ensure_ascii=False),
                )
                self.store.add_audit(pid, f"engineering:{name}", "success", json.dumps(out)[:3000])
            except Exception as exc:
                msg = str(exc)
                generation["status"] = "TIMEOUT" if any(x in msg.lower() for x in ("timeout", "timed out", "gateway")) else "FAILED"
                generation["error"] = msg
                generation["failed_component"] = name
                generation["updated_at"] = self.store.now()
                self.store.save_artifact(
                    pid, "engineering_generation", "engineering_generation.json", "json",
                    json.dumps(generation, indent=2, ensure_ascii=False),
                )
                self.store.add_audit(pid, f"engineering:{name}", generation["status"].lower(), msg[:4000])
                return {
                    "status": generation["status"],
                    "generation_id": generation["generation_id"],
                    "failed_component": name,
                    "completed_components": list(results.keys()),
                    "error": msg,
                    "retryable": True,
                    "message": "Generation is resumable. Retry will continue from the failed component; completed components are preserved.",
                }

        final = {
            "summary": "Production-safe metadata-driven Medallion engineering package generated from approved evidence.",
            "status": "SUCCEEDED",
            "generation_id": generation["generation_id"],
            "platform": pcfg.get("platform"),
            "cloud": pcfg.get("cloud"),
            "bronze": results.get("bronze", {}),
            "silver": results.get("silver", {}),
            "gold": results.get("gold", {}),
            "data_quality": results.get("data_quality", {}),
            "orchestration": results.get("orchestration", {}),
            "testing": results.get("testing", {}),
            "code_artifacts": results.get("code_artifacts", {}),
            "traceability": {
                "blueprint_run": blueprint.get("id"),
                "metadata_run": metadata.get("id"),
                "environment_run": env_run.get("id"),
                "assessment_run": assessment.get("id"),
                "customer_environment_verified": True,
            },
        }
        self.store.save_run(pid, "engineering", "success", system, final)
        generation["status"] = "SUCCEEDED"
        generation["completed_at"] = self.store.now()
        generation["updated_at"] = generation["completed_at"]
        generation["completed_components"] = results
        generation.pop("error", None)
        generation.pop("failed_component", None)
        self.store.save_artifact(
            pid, "engineering_generation", "engineering_generation.json", "json",
            json.dumps(generation, indent=2, ensure_ascii=False),
        )
        self.store.add_audit(pid, "llm:engineering", "success", json.dumps(final)[:5000])
        return final

    def run_lakeflow(self,pid):
        instructions=prompts.ENGINEERING+"""
Focus on Lakeflow. Return pipeline_name, source_pattern, bronze, silver, gold,
data_quality_expectations, parameters and complete source under pipeline_code.
Use current Spark Declarative Pipelines syntax where appropriate.
"""
        out=self._run(pid,"lakeflow",instructions)
        if isinstance(out,dict) and out.get("pipeline_code"):
            self.store.save_artifact(pid,"lakeflow_pipeline",
                out.get("pipeline_name","cinvent_pipeline")+".py","python",out["pipeline_code"])
        return out

    def llm_test(self,text,system):
        try: return self.llm.invoke(text,system)
        except Exception as e: return {"error":str(e)}

    def create_lakeflow(self,pid,db):
        if not self.settings.allow_mutations:
            return {"status":"blocked","reason":"Mutation gate disabled"}
        validate = self._success(pid, "qa")
        if not validate:
            return {"status":"blocked","reason":"Deployment requires successful validation."}
        if not self._current_approval(pid, "deployment", validate):
            return {"status":"blocked","reason":"Deployment approval is required."}
        spec=self.run_lakeflow(pid)
        return db.create_pipeline_from_spec(pid,spec,self.store)

    def create_job(self,pid,db):
        if not self.settings.allow_mutations:
            return {"status":"blocked","reason":"Mutation gate disabled"}
        validate = self._success(pid, "qa")
        if not validate:
            return {"status":"blocked","reason":"Deployment requires successful validation."}
        if not self._current_approval(pid, "deployment", validate):
            return {"status":"blocked","reason":"Deployment approval is required."}
        name=f"cinvent_{pid[:8]}_etl"
        tasks=[]
        sources={}
        for a in self.store.artifacts(pid):
            if a["kind"] in ("bronze","silver","gold","engineering"):
                key=re.sub(r"[^A-Za-z0-9_]+","_",a["name"]).strip("_")[:50] or "engineering_plan"
                tasks.append({"task_key":key})
                sources[key]=a["content"]
        if not tasks:
            tasks=[{"task_key":"engineering_plan"}]
            sources["engineering_plan"]="# C INVENT generated task\nprint('Generate engineering artifacts first.')"
        return db.create_job({"name":name,"tasks":tasks}, sources)

    def create_lakebase(self,pid,db):
        if not self.settings.allow_mutations:
            return {"status":"blocked","reason":"Mutation gate disabled"}
        validate = self._success(pid, "qa")
        if not validate or not self._current_approval(pid, "deployment", validate):
            return {"status":"blocked","reason":"Deployment approval is required after successful validation."}
        project_id=f"cinvent-{pid[:8]}"
        return db.create_lakebase_project(project_id,self.store.get_project(pid)["name"])

    def create_app(self,pid,db,lakebase_project_id=None):
        if not self.settings.allow_mutations:
            return {"status":"blocked","reason":"Mutation gate disabled"}
        validate = self._success(pid, "qa")
        if not validate or not self._current_approval(pid, "deployment", validate):
            return {"status":"blocked","reason":"Deployment approval is required after successful validation."}
        project=self.store.get_project(pid)
        app_name=re.sub(r"[^a-z0-9-]+","-",project["name"].lower()).strip("-")[:25] or f"cinvent-{pid[:8]}"
        source_path=f"/Workspace/Shared/C_INVENT/apps/{app_name}"
        app_py = (
            "import os\n"
            "import streamlit as st\n"
            "st.set_page_config(page_title='Customer Data Product',layout='wide')\n"
            "st.title('Customer Data Product')\n"
            "st.caption('Generated by C INVENT')\n"
            "st.write('Operational and analytics application shell generated from the approved C INVENT blueprint.')\n"
            "st.write('Use the Databricks App resource named postgres for Lakebase when configured.')\n"
        )
        app_yaml = (
            "command:\n"
            "  - 'streamlit'\n"
            "  - 'run'\n"
            "  - 'app.py'\n"
            "  - '--server.port'\n"
            "  - '8000'\n"
        )
        db.ensure_workspace_dir(source_path)
        db.import_notebook(source_path+"/app.py",app_py)
        db.import_notebook(source_path+"/app.yaml",app_yaml,language=None)
        return db.create_customer_app(app_name,project["name"],source_path,lakebase_project_id)

    def run_latest_job(self,pid,db):
        jobs=db.list_jobs(prefix=f"cinvent_{pid[:8]}")
        return db.run_job(jobs[0]["job_id"]) if jobs else {"status":"not_found"}
