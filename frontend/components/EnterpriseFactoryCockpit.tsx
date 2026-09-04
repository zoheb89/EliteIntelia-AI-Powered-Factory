'use client';

import {useEffect, useMemo, useState} from 'react';
import Link from 'next/link';
import {
  Activity, ArrowRight, Bot, BrainCircuit, Check, CheckCircle2, ChevronRight,
  CircleAlert, Clock3, Database, FileCheck2, FileText, Gauge, GitBranch,
  Layers3, Lightbulb, ListChecks, LockKeyhole, Plus, RefreshCw, Rocket,
  Scale, Search, ShieldCheck, Sparkles, Target, UsersRound, Workflow, X
} from 'lucide-react';
import {
  AcceleratorCatalogue, FactoryProject, ProjectLifecycle, Statement, ArtifactRow,
  listFactoryProjects, createFactoryProject, getProjectLifecycle, getNextAction,
  getAcceleratorCatalogue, getProjectAccelerators, runFactoryStage, approveStage,
  listStatements, listFactoryArtifacts, listUnknowns
} from '../lib/factory-api';

type Product = {
  code:string; name:string; tagline:string; icon:any; accent:string;
  accelerators:string[]; outputs:string[]; route:string;
};

const PRODUCTS:Product[] = [
  {code:'01',name:'Intake & RFP Intelligence',tagline:'Turn a short brief, RFI/RFP or document pack into an executable engagement.',icon:FileText,accent:'cyan',accelerators:['Universal Intake','RFP/RFI Analyzer','Document Intelligence','Requirement Signal Miner','Scope & Dependency Mapper'],outputs:['Business intent','Evidence register','Initial scope','Open questions'],route:'/intake'},
  {code:'02',name:'Business Analysis Studio',tagline:'Move from customer conversation to governed BRD → FRD → SRD.',icon:ListChecks,accent:'violet',accelerators:['BRD Generator','FRD Generator','SRD Generator','Requirement Traceability','Acceptance Criteria Builder'],outputs:['BRD','FRD','SRD','Traceability matrix'],route:'/factory'},
  {code:'03',name:'Discovery & Assessment',tagline:'Evidence-backed discovery across business, data, technology and operating model.',icon:Search,accent:'blue',accelerators:['Discovery Accelerator','Current-State Assessment','Environment Assessment','Data Estate Profiler','Gap & Risk Analyzer'],outputs:['Discovery pack','Current state','Risks','Readiness score'],route:'/discovery'},
  {code:'04',name:'Architecture & Platform Decision',tagline:'Select the right target architecture and platform using evidence and constraints.',icon:Layers3,accent:'purple',accelerators:['Platform Fit Scorer','Reference Architecture','Migration Planner','Cloud Alignment','Architecture Decision Record'],outputs:['Target architecture','Platform decision','ADR','Migration roadmap'],route:'/architecture'},
  {code:'05',name:'Data Engineering Factory',tagline:'Generate governed ingestion, transformation, metadata and production-ready pipelines.',icon:Database,accent:'cyan',accelerators:['Pipeline Factory','Metadata Factory','Lakehouse Accelerator','SQL/dbt Generator','Data Quality Pack'],outputs:['Metadata','Pipeline code','Tests','Deployment plan'],route:'/engineering'},
  {code:'06',name:'AI & Analytics Factory',tagline:'Build semantic, AI and BI experiences on the same governed data backbone.',icon:BrainCircuit,accent:'violet',accelerators:['AI Readiness','RAG/Knowledge Pack','Semantic Model Factory','BI Accelerator','GenAI Use-Case Mapper'],outputs:['AI use cases','Semantic layer','BI assets','Evaluation plan'],route:'/ai-analytics'},
  {code:'07',name:'Quality, Validation & Release',tagline:'Prove correctness before production with evidence, gates and deterministic checks.',icon:ShieldCheck,accent:'green',accelerators:['Validation Factory','Data Quality','AI Evaluation','Security & Governance','Release Readiness'],outputs:['Validation evidence','Defect register','Approval gates','Release pack'],route:'/validation'},
  {code:'08',name:'Delivery & Commercial Control Plane',tagline:'Operate the programme with effort, automation, SOW, approvals and audit in one cockpit.',icon:Gauge,accent:'amber',accelerators:['Effort Estimator','Automation Scoring','SOW Factory','Commercial Inputs','Delivery Control Tower'],outputs:['Effort model','Automation %','SOW','Audit trail'],route:'/factory/estimate'}
];

const STAGES = [
  ['intent','Intent'],['evidence','Evidence'],['discovery','Discovery'],['environment_assessment','Environment'],
  ['assessment','Assessment'],['requirements','Requirements'],['architecture','Architecture'],['platform_onboarding','Platform'],
  ['metadata','Metadata'],['engineering','Engineering'],['validate','Validate'],['deploy','Deploy'],['operate','Operate']
] as const;

function pct(n:number,d:number){return d ? Math.round((n/d)*100) : 0}
function stageLabel(id:string){return STAGES.find(s=>s[0]===id)?.[1] || id.replaceAll('_',' ')}

export function EnterpriseFactoryCockpit(){
  const [projects,setProjects]=useState<FactoryProject[]>([]);
  const [project,setProject]=useState<FactoryProject|null>(null);
  const [life,setLife]=useState<ProjectLifecycle|null>(null);
  const [next,setNext]=useState<any|null>(null);
  const [statements,setStatements]=useState<Statement[]>([]);
  const [artifacts,setArtifacts]=useState<ArtifactRow[]>([]);
  const [unknowns,setUnknowns]=useState<{id:string;text:string;stage:string}[]>([]);
  const [cat,setCat]=useState<AcceleratorCatalogue|null>(null);
  const [recommended,setRecommended]=useState<any[]>([]);
  const [loading,setLoading]=useState(false);
  const [message,setMessage]=useState('');
  const [tab,setTab]=useState<'command'|'products'|'evidence'|'runs'>('command');
  const [showCreate,setShowCreate]=useState(false);
  const [customer,setCustomer]=useState('');
  const [name,setName]=useState('');
  const [intent,setIntent]=useState('');
  const [query,setQuery]=useState('');

  async function refresh(p=project){
    if(!p) return;
    setLoading(true); setMessage('');
    try{
      const [l,n,s,a,u,r] = await Promise.all([
        getProjectLifecycle(p.id), getNextAction(p.id), listStatements(p.id), listFactoryArtifacts(p.id), listUnknowns(p.id), getProjectAccelerators(p.id)
      ]);
      setLife(l); setNext(n); setStatements(s.items); setArtifacts(a.items); setUnknowns(u.items); setRecommended(r.recommended || []);
    }catch(e:any){setMessage(e?.message || 'Unable to load factory state.');}
    finally{setLoading(false)}
  }

  useEffect(()=>{
    Promise.all([listFactoryProjects(),getAcceleratorCatalogue()]).then(([p,c])=>{
      setProjects(p.items || []); setCat(c);
      const saved = typeof window !== 'undefined' ? localStorage.getItem('eliteintelia_factory_project') : null;
      const found = (p.items || []).find(x=>x.id===saved) || (p.items || [])[0] || null;
      setProject(found);
    }).catch(e=>setMessage(e?.message || 'Factory API is not reachable.'));
  },[]);
  useEffect(()=>{if(project) refresh(project)},[project?.id]);

  async function create(){
    if(!name.trim()) return;
    setLoading(true);
    try{
      const created=await createFactoryProject({name:name.trim(),customer:customer.trim(),intent:intent.trim(),domain:'Enterprise Data & AI'});
      const p:FactoryProject={id:created.id,name:created.name,intent:intent.trim(),domain:'Enterprise Data & AI',version:created.version};
      setProjects(v=>[p,...v]); setProject(p); localStorage.setItem('eliteintelia_factory_project',p.id); setShowCreate(false); setName('');setCustomer('');setIntent('');
    }catch(e:any){setMessage(e?.message || 'Could not create engagement.')}finally{setLoading(false)}
  }

  async function run(stage:string){
    if(!project) return;
    setLoading(true); setMessage(`Starting ${stageLabel(stage)}…`);
    try{
      await runFactoryStage(project.id,stage,true); setMessage(`${stageLabel(stage)} job submitted. Refreshing control plane…`); await refresh(project);
    }catch(e:any){setMessage(e?.message || `Unable to run ${stageLabel(stage)}.`)}finally{setLoading(false)}
  }

  async function approve(stage:string){
    if(!project) return;
    setLoading(true);
    try{await approveStage(project.id,stage,'Approved from Enterprise Factory Cockpit');await refresh(project);setMessage(`${stageLabel(stage)} approved.`)}
    catch(e:any){setMessage(e?.message || 'Approval failed.')}finally{setLoading(false)}
  }

  const filteredProducts=useMemo(()=>PRODUCTS.filter(p=>{
    const q=query.toLowerCase().trim(); return !q || [p.name,p.tagline,...p.accelerators].join(' ').toLowerCase().includes(q)
  }),[query]);
  const progress=life ? pct(life.progress.complete,life.progress.total) : 0;
  const pending=life?.pending_approval;
  const currentStage=life?.next_stage?.id || next?.primary?.stage || 'intent';
  const engineMode=life?.generation?.any_degraded ? 'Evidence-only fallback active' : 'AI + deterministic engine ready';

  return <div className="efc">
    <section className="efcHero">
      <div className="efcHeroCopy">
        <div className="efcEyebrow"><FactoryPulse/> ELITEINTELIA · AI DATA AUTOMATION FACTORY</div>
        <h1>Enterprise transformation,<br/><span>run as a governed factory.</span></h1>
        <p>One control plane from intake and business analysis through architecture, data engineering, AI, validation, deployment and operations — with AI recommendations, deterministic scoring, customer constraints and human approvals.</p>
        <div className="efcHeroActions">
          <button className="efcPrimary" onClick={()=>setShowCreate(true)}><Plus size={17}/> New engagement</button>
          <Link className="efcSecondary" href="/intake"><FileText size={17}/> Start from RFP / brief</Link>
        </div>
      </div>
      <div className="efcHeroDiagram">
        <div className="efcOrbit"><div className="orbitCore"><Sparkles size={25}/><b>AI</b><span>recommend</span></div><div className="orbitNode n1">Evidence</div><div className="orbitNode n2">Constraints</div><div className="orbitNode n3">Engine</div><div className="orbitNode n4">Approval</div></div>
      </div>
    </section>

    <section className="efcControlBar">
      <div className="efcProjectSelect"><div className="efcProjectIcon"><Workflow size={17}/></div><div><small>ACTIVE ENGAGEMENT</small><strong>{project?.name || 'No engagement selected'}</strong></div><select value={project?.id || ''} onChange={e=>{const p=projects.find(x=>x.id===e.target.value)||null;setProject(p);if(p)localStorage.setItem('eliteintelia_factory_project',p.id)}}><option value="">Select</option>{projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
      <div className="efcHealth"><span className="liveDot"/> Factory control plane <b>LIVE</b><span className="divider"/><span>{engineMode}</span></div>
      <button className="efcIconBtn" onClick={()=>refresh()} title="Refresh"><RefreshCw size={16}/></button>
    </section>

    {message && <div className="efcNotice"><CircleAlert size={16}/><span>{message}</span><button onClick={()=>setMessage('')}><X size={15}/></button></div>}

    {!project ? <section className="efcEmpty"><div><Rocket size={30}/><h2>Start the first governed engagement</h2><p>Create a customer engagement and the factory will derive the lifecycle, readiness gates, evidence lineage and next best action.</p><button className="efcPrimary" onClick={()=>setShowCreate(true)}><Plus size={17}/> Create engagement</button></div></section> : <>
      <section className="efcMetrics">
        <Metric icon={Target} label="Lifecycle progress" value={`${progress}%`} sub={`${life?.progress.complete || 0} of ${life?.progress.total || 13} stages`} progress={progress}/>
        <Metric icon={FileCheck2} label="Evidence coverage" value={`${next?.evidence?.percent ?? 0}%`} sub={`${next?.evidence?.documents ?? 0} documents · ${next?.evidence?.evidenced ?? 0} evidenced`} progress={next?.evidence?.percent ?? 0}/>
        <Metric icon={CircleAlert} label="Open questions" value={`${next?.evidence?.open_questions ?? unknowns.length}`} sub="Need customer / analyst decision" tone={(next?.evidence?.open_questions ?? unknowns.length)>0?'warn':'ok'}/>
        <Metric icon={Bot} label="AI acceleration" value={life?.generation?.any_degraded?'Fallback':'Ready'} sub={life?.generation?.ai_stages?.length ? `${life.generation.ai_stages.length} AI stages enabled` : 'Provider status inherited from factory'} tone={life?.generation?.any_degraded?'warn':'ok'}/>
      </section>

      <div className="efcTabs"><button className={tab==='command'?'active':''} onClick={()=>setTab('command')}>Command Center</button><button className={tab==='products'?'active':''} onClick={()=>setTab('products')}>Product Factory</button><button className={tab==='evidence'?'active':''} onClick={()=>setTab('evidence')}>Evidence & Decisions</button><button className={tab==='runs'?'active':''} onClick={()=>setTab('runs')}>Execution Trace</button></div>

      {tab==='command' && <div className="efcGrid">
        <section className="efcPanel efcNext"><PanelTitle icon={Lightbulb} title="AI + Engine Next Best Action" label="DECISION SUPPORT"/><div className="nextCard"><div className="nextIcon"><Sparkles size={20}/></div><div className="nextBody"><span className="decisionTag">RECOMMENDED ACTION</span><h2>{next?.primary?.title || life?.next_stage?.label || 'Establish business intent'}</h2><p>{next?.primary?.reason || next?.basis || 'The factory will determine the next executable step from evidence, lifecycle state and customer constraints.'}</p><div className="decisionLogic"><LogicChip icon={BrainCircuit} label="AI recommendation"/><LogicChip icon={Scale} label="Deterministic scoring"/><LogicChip icon={LockKeyhole} label="Customer constraints"/></div><div className="nextActions"><button className="efcPrimary" disabled={loading || !currentStage} onClick={()=>run(currentStage)}><Rocket size={16}/> Execute next stage</button>{pending && <button className="efcSecondary" onClick={()=>approve(pending.id)}><Check size={16}/> Approve {pending.label}</button>}</div></div></div></section>

        <section className="efcPanel"><PanelTitle icon={Workflow} title="Lifecycle control" label="13-STAGE FACTORY"/><div className="lifecycleRail">{STAGES.map(([id,label],i)=>{const s=life?.stages?.[id];const done=s?.status==='complete'||s?.status==='success'||s?.approved;const running=s?.status==='running';return <div key={id} className={`railStage ${done?'done':''} ${running?'running':''} ${id===currentStage?'current':''}`}><div className="railDot">{done?<Check size={11}/>:i+1}</div><span>{label}</span>{i<STAGES.length-1&&<i/>}</div>})}</div><div className="lifecycleFoot"><span><i className="dot done"/> Completed</span><span><i className="dot current"/> Next action</span><span><i className="dot"/> Locked / pending evidence</span></div></section>

        <section className="efcPanel"><PanelTitle icon={ShieldCheck} title="Governance gates" label="HUMAN IN THE LOOP"/><div className="gateRows"><Gate label="Evidence provenance" status={unknowns.length?'Review required':'Clear'} ok={!unknowns.length}/><Gate label="AI output classification" status="Enforced" ok/><Gate label="Mutation control" status="Approval required" ok/><Gate label="Customer decision" status={pending?`Pending · ${pending.label}`:'No pending gate'} ok={!pending}/></div></section>

        <section className="efcPanel"><PanelTitle icon={Sparkles} title="Recommended accelerators" label={`${recommended.length} MATCHED`}/>{recommended.length ? <div className="recList">{recommended.slice(0,6).map((a:any)=><div className="recRow" key={a.id}><div className="recIcon"><ZapIcon/></div><div><strong>{a.name}</strong><span>{a.reason || a.summary}</span></div><small>{a.engine==='deterministic'?'ENGINE':a.engine==='ai'?'AI':'AI + ENGINE'}</small></div>)}</div>:<div className="efcEmptyMini"><Sparkles size={19}/><span>Accelerators will be recommended when the engagement has evidence.</span></div>}</section>
      </div>}

      {tab==='products' && <section className="efcProductSection"><div className="efcSectionHead"><div><span>THE ELITEINTELIA DIFFERENTIATOR</span><h2>Eight products. One governed factory.</h2><p>Each product is independently useful, but all accelerators operate against the same engagement, evidence, decision and approval backbone.</p></div><div className="efcSearch"><Search size={15}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search products or accelerators"/></div></div><div className="productGrid">{filteredProducts.map(p=><ProductCard key={p.code} product={p}/>)}</div></section>}

      {tab==='evidence' && <div className="efcGrid"><section className="efcPanel wide"><PanelTitle icon={FileCheck2} title="Evidence register" label={`${artifacts.length} ARTIFACTS`}/><div className="dataTable"><div className="tr th"><span>Artifact / decision</span><span>Type</span><span>Approval</span><span>Version</span></div>{artifacts.slice(0,10).map(a=><div className="tr" key={a.id}><span><b>{a.name}</b><small>{a.kind}</small></span><span>{a.fmt}</span><span><StatusPill value={a.approval_state}/></span><span>v{a.version}</span></div>)}{!artifacts.length&&<div className="tableEmpty">No persisted artifacts yet. Run the first factory stage to start the evidence chain.</div>}</div></section><section className="efcPanel"><PanelTitle icon={CircleAlert} title="Unknowns & questions" label={`${unknowns.length} OPEN`}/>{unknowns.length?<div className="unknownList">{unknowns.slice(0,8).map(u=><div key={u.id}><span>{u.stage}</span><p>{u.text}</p></div>)}</div>:<div className="efcEmptyMini"><CheckCircle2 size={19}/><span>No open questions detected.</span></div>}</section><section className="efcPanel"><PanelTitle icon={UsersRound} title="Statements" label={`${statements.length} RECORDED`}/><div className="statementList">{statements.slice(0,7).map(s=><div key={s.id}><div><b>{s.ref}</b><StatusPill value={s.provenance}/></div><p>{s.text}</p><small>{s.confidence} confidence · {s.evidence?.length || 0} citations</small></div>)}{!statements.length&&<div className="tableEmpty">Statements appear as discovery and requirements are executed.</div>}</div></section></div>}

      {tab==='runs' && <section className="efcPanel wide"><PanelTitle icon={Activity} title="Execution trace" label="CONTROL PLANE"/><div className="traceHero"><div className="traceIcon"><Activity size={23}/></div><div><h2>Resumable, auditable execution</h2><p>Agents propose. The orchestrator checks gates, persists approved changes and records provenance. Failed provider calls degrade explicitly instead of pretending to be AI output.</p></div></div><div className="traceTimeline">{STAGES.map(([id,label],i)=>{const s=life?.stages?.[id];return <div className="traceRow" key={id}><div className={`traceDot ${s?.status==='complete'?'ok':''}`}>{s?.status==='complete'?<Check size={11}/>:i+1}</div><div><strong>{label}</strong><span>{s?.status || 'locked'}{s?.generation_mode?` · ${s.generation_mode}`:''}</span></div><small>{s?.blockers?.length?`${s.blockers.length} blocker(s)`:'Gate state evaluated'}</small></div>})}</div></section>}
    </>}

    {showCreate && <div className="efcModalBackdrop" onMouseDown={()=>setShowCreate(false)}><div className="efcModal" onMouseDown={e=>e.stopPropagation()}><div className="modalHead"><div><span>NEW ENGAGEMENT</span><h2>Start a governed factory run</h2></div><button onClick={()=>setShowCreate(false)}><X/></button></div><label>Engagement name<input value={name} onChange={e=>setName(e.target.value)} placeholder="e.g. Enterprise Data Modernization" autoFocus/></label><label>Customer / organization<input value={customer} onChange={e=>setCustomer(e.target.value)} placeholder="Customer name"/></label><label>Business intent<textarea value={intent} onChange={e=>setIntent(e.target.value)} placeholder="Describe the desired outcome, even if the brief is only a few sentences…"/></label><div className="modalHint"><Sparkles size={16}/><span>The factory will turn this into intent, evidence requirements, readiness gates and the next best action.</span></div><div className="modalActions"><button className="efcSecondary" onClick={()=>setShowCreate(false)}>Cancel</button><button className="efcPrimary" disabled={!name.trim()||loading} onClick={create}>{loading?'Creating…':'Create engagement'} <ArrowRight size={16}/></button></div></div></div>}
  </div>
}

function Metric({icon:Icon,label,value,sub,progress,tone}:{icon:any;label:string;value:string;sub:string;progress?:number;tone?:string}){return <div className="metric"><div className="metricIcon"><Icon size={17}/></div><div className="metricCopy"><span>{label}</span><strong className={tone||''}>{value}</strong><small>{sub}</small>{progress!==undefined&&<div className="metricBar"><i style={{width:`${Math.min(100,progress)}%`}}/></div>}</div></div>}
function PanelTitle({icon:Icon,title,label}:{icon:any;title:string;label:string}){return <div className="panelTitle"><Icon size={17}/><div><b>{title}</b><span>{label}</span></div></div>}
function LogicChip({icon:Icon,label}:{icon:any;label:string}){return <span className="logicChip"><Icon size={13}/>{label}</span>}
function Gate({label,status,ok}:{label:string;status:string;ok:boolean}){return <div className="gateRow"><div><span>{label}</span><b>{status}</b></div><div className={ok?'gateOk':'gateWarn'}>{ok?<CheckCircle2 size={17}/>:<Clock3 size={17}/>}</div></div>}
function StatusPill({value}:{value:string}){return <em className={`statusPill ${String(value).toLowerCase().replaceAll('_','-')}`}>{String(value).replaceAll('_',' ')}</em>}
function ProductCard({product:p}:{product:Product}){const Icon=p.icon;return <article className={`productCard ${p.accent}`}><div className="productTop"><div className="productIcon"><Icon size={20}/></div><span>{p.code}</span></div><h3>{p.name}</h3><p>{p.tagline}</p><div className="productLabel">ACCELERATORS</div><div className="accelChips">{p.accelerators.map(a=><span key={a}>{a}</span>)}</div><div className="productLabel">FACTORY OUTPUTS</div><div className="outputList">{p.outputs.map(o=><span key={o}><Check size={12}/>{o}</span>)}</div><Link href={p.route}>Open product <ArrowRight size={14}/></Link></article>}
function FactoryPulse(){return <span className="factoryPulse"><span/><span/><span/></span>}
function ZapIcon(){return <Sparkles size={14}/>}
export default EnterpriseFactoryCockpit;
