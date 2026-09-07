'use client';
import {useState} from 'react';
import {FileUp,ArrowRight,Sparkles,CheckCircle2,Download,LoaderCircle} from 'lucide-react';
import {createFactoryProject,uploadEvidence,listEvidence} from '../lib/factory-api';
import Link from 'next/link';

export function IntakeCenter(){
  const [files,setFiles]=useState<File[]>([]),[text,setText]=useState(''),[name,setName]=useState(''),[customer,setCustomer]=useState(''),[domain,setDomain]=useState(''),[busy,setBusy]=useState(false),[result,setResult]=useState<any|null>(null),[error,setError]=useState('');
  const submit=async()=>{
    if(!name.trim() && !text.trim() && !files.length) return;
    setBusy(true);setError('');
    try{
      const project=await createFactoryProject({name:name.trim()||files[0]?.name||'New Engagement',intent:text.trim(),domain:domain.trim()||'Enterprise Data & AI',customer:customer.trim()});
      for(const file of files) await uploadEvidence(project.id,file);
      localStorage.setItem('eliteintelia_factory_project',project.id);
      const evidence=await listEvidence(project.id);
      setResult({id:project.id,name:name.trim()||files[0]?.name||'New Engagement',evidence:evidence.count||0});
    }catch(e:any){setError(e?.message||'Intake failed')}
    finally{setBusy(false)}
  };
  return <>
    <div className="pageHead"><div><div className="crumb">Home <span>›</span> Intake Center</div><h1>Start a New Engagement</h1><p>Upload an RFI, RFP, SOW, proposal, notes or emails. The intake is stored directly in the canonical 20-stage factory as evidence.</p></div></div>
    <div className="intakeGrid">
      <div className="panel uploadPanel">
        <label className="dropzone"><input type="file" multiple accept=".pdf,.doc,.docx,.xlsx,.xls,.txt,.ppt,.pptx,.eml,.msg" onChange={e=>setFiles(Array.from(e.target.files||[]))}/><FileUp/><strong>{files.length?`${files.length} file${files.length>1?'s':''} selected`: 'Drag & drop files here or click to browse'}</strong><span>Supports PDF, DOCX, XLSX, TXT, PPTX, EML</span><button type="button" className="secondary">Upload Files</button></label>
        {files.length>0&&<div style={{marginTop:12}}>{files.map(f=><div key={f.name} className="notice"><FileUp size={15}/>{f.name}</div>)}</div>}
      </div>
      <div className="panel"><h3>Engagement context</h3><input className="textInput" value={name} onChange={e=>setName(e.target.value)} placeholder="Engagement name (e.g. Meridian Retail Bank – Enterprise Data Modernization)"/><input className="textInput" value={customer} onChange={e=>setCustomer(e.target.value)} placeholder="Customer (e.g. Meridian Retail Bank)"/><input className="textInput" value={domain} onChange={e=>setDomain(e.target.value)} placeholder="Domain (optional)"/><textarea value={text} onChange={e=>setText(e.target.value)} placeholder="Paste business intent, RFP summary, requirements or meeting notes..."/><button className="primary continue" onClick={submit} disabled={busy||(!files.length&&!text.trim())}>{busy?<><LoaderCircle className="spin"/>Ingesting evidence…</>:`Create in Factory`} <ArrowRight/></button></div>
    </div>
    {error&&<div className="notice error">{error}</div>}
    <div className="panel recent"><h3>Canonical factory intake</h3>{result?<div className="result"><CheckCircle2/><div><strong>{result.name}</strong><p>Factory project {result.id} · {result.evidence} evidence document(s)</p><span>Evidence is now attached to the same project used by the 20-stage cockpit. Nothing is created in the legacy 8-stage engagement model.</span><div className="resultActions"><Link className="primary" href="/factory">Open Factory Cockpit <ArrowRight size={16}/></Link></div></div></div>:<div className="empty"><Sparkles/>Create the engagement here, then continue in the Factory Cockpit. The next action, evidence coverage, open questions and all 20 lifecycle stages are controlled from one place.</div>}</div>
  </>;
}
