export const API_BASE=(process.env.NEXT_PUBLIC_API_BASE_URL||"http://localhost:8000").replace(/\/$/,"");

export type Engagement={id:string;title:string;customer:string;source:string;domain:string;stage:string;progress:number;total:number;description:string;status:string;date:string;platform_state?:any};
export type IntakeResult={engagement_id:string;name:string;document_type:string;status:string;extracted_summary?:string;analysis?:any;lifecycle?:any};

function formatApiError(payload:unknown,status:number):string{
  if(typeof payload === "string" && payload.trim()) return payload;
  if(payload && typeof payload === "object"){
    const p=payload as Record<string,unknown>;
    if(typeof p.message === "string" && p.message) return p.message;
    if(typeof p.detail === "string" && p.detail) return p.detail;
    if(Array.isArray(p.errors)){
      const messages=p.errors.map((e:any)=>{
        if(typeof e === "string") return e;
        const loc=Array.isArray(e?.loc)?e.loc.join("."):"request";
        const msg=typeof e?.msg === "string"?e.msg:"Invalid value";
        return `${loc}: ${msg}`;
      }).filter(Boolean);
      if(messages.length) return messages.join("; ");
    }
    try{return JSON.stringify(payload)}catch{}
  }
  return `Request failed (${status})`;
}

const TOKEN_KEY="eliteintelia_token";
export function getToken(){try{return typeof window!=="undefined"?localStorage.getItem(TOKEN_KEY):null}catch{return null}}
export function setToken(t:string|null){try{if(t)localStorage.setItem(TOKEN_KEY,t);else localStorage.removeItem(TOKEN_KEY)}catch{}}
export class UnauthorizedError extends Error{}

async function request<T>(path:string,init?:RequestInit):Promise<T>{
  let r:Response;
  const token=getToken();
  const headers=new Headers(init?.headers||{});
  if(token) headers.set("Authorization",`Bearer ${token}`);
  try{
    r=await fetch(`${API_BASE}${path}`,{...init,headers,cache:"no-store"});
  }catch(e:any){
    throw new Error(e?.message||`Unable to reach API at ${API_BASE}`);
  }

  const raw=await r.text();
  let payload:unknown=raw;
  if(raw){try{payload=JSON.parse(raw)}catch{}}
  if(r.status===401){setToken(null);throw new UnauthorizedError(formatApiError(payload,401))}
  if(!r.ok) throw new Error(formatApiError(payload,r.status));
  if(!raw) return {} as T;
  if(typeof payload === "string"){
    try{return JSON.parse(payload) as T}catch{return payload as T}
  }
  return payload as T;
}

export function getApiHealth(){return request<{status:string;product?:string;version?:string}>("/health")}
export async function getEngagements(){return request<{items:Engagement[]}>("/api/engagements")}
export async function getEngagement(id:string){return request<any>(`/api/engagements/${encodeURIComponent(id)}`)}
export async function createIntake(p:{name:string;text?:string;domain?:string;file?:File}):Promise<IntakeResult>{
  const f=new FormData();
  f.append("name",p.name||"New Engagement");
  f.append("text",p.text||"");
  f.append("domain",p.domain||"");
  if(p.file) f.append("file",p.file,p.file.name);
  return request<IntakeResult>("/api/intake",{method:"POST",body:f});
}
export type StageResult={status?:string;stage?:string;result?:any;execution_id:string;execution:any;execution_trace?:Array<{step:string;status:string;mode?:string}>;next_stage?:string;approval_required_for_downstream?:boolean;lifecycle?:any};
export async function runStage(id:string,stage:string):Promise<StageResult>{return request<StageResult>(`/api/engagements/${encodeURIComponent(id)}/stages/${encodeURIComponent(stage)}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({})})}
export async function getExecution(id:string,executionId:string){return request<any>(`/api/engagements/${encodeURIComponent(id)}/executions/${encodeURIComponent(executionId)}`)}
export async function getExecutions(id:string){return request<any>(`/api/engagements/${encodeURIComponent(id)}/executions`)}
export async function approve(id:string,type:string,comment?:string){return request<any>(`/api/engagements/${encodeURIComponent(id)}/approvals/${encodeURIComponent(type)}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({comment})})}
export async function savePlatform(id:string,cfg:any){return request<any>(`/api/engagements/${encodeURIComponent(id)}/platform`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(cfg)})}
export async function verifyPlatform(id:string){return request<any>(`/api/engagements/${encodeURIComponent(id)}/platform/verify`,{method:"POST"})}
export async function platformPlan(id:string){return request<any>(`/api/engagements/${encodeURIComponent(id)}/platform/plan`,{method:"POST"})}
export function downloadUrl(id:string,type:"pdf"|"zip"){return `${API_BASE}/api/engagements/${encodeURIComponent(id)}/${type==="pdf"?"report.pdf":"download/intake.zip"}`}

/* ---------------------------------------------------------------------------
 * Artifacts, runs and catalog. These endpoints exist on the backend but were
 * never wired into the UI, which is why generated deliverables were invisible.
 * ------------------------------------------------------------------------ */
export type ArtifactSummary={id:string;kind:string;name?:string;language?:string;created_at?:string};
export type ArtifactDetail={id:string;kind:string;name?:string;language?:string;created_at?:string;content:any};

export async function getArtifacts(id:string){
  return request<{items:ArtifactSummary[]}>(`/api/engagements/${encodeURIComponent(id)}/artifacts`);
}
export async function getArtifact(id:string,kind:string){
  return request<{artifact:ArtifactDetail}>(`/api/engagements/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(kind)}`);
}
export async function getRuns(id:string){
  return request<any>(`/api/engagements/${encodeURIComponent(id)}/runs`);
}
export async function getPlatformCatalog(){
  return request<any>("/api/catalog/platforms");
}

/* ---------------------------------------------------------------------------
 * Transformation Studio — visual pipeline compiled to dbt + PySpark.
 * ------------------------------------------------------------------------ */
export type StudioColumn={name:string;source_name?:string;type?:string;expression?:string;description?:string;tests?:string[];accepted_values?:string[];relationship_to?:string;relationship_field?:string};
export type StudioNode={id:string;type:string;name:string;layer?:string;description?:string;position:{x:number;y:number};config?:Record<string,any>;columns?:StudioColumn[]};
export type StudioEdge={id:string;source:string;target:string;targetHandle?:string};
export type Pipeline={name:string;nodes:StudioNode[];edges:StudioEdge[]};
export type CompiledModel={name:string;path:string;type:string;layer:string;sql:string};
export type Compiled={ok:boolean;errors:string[];project?:string;order:string[];models:CompiledModel[];schema_yml:string;pyspark:string;lineage:{from:string;to:string;transform:string}[];stats?:Record<string,number>};

export async function getPalette(){
  return request<{node_types:Record<string,{label:string;inputs:number;category:string;description:string}>;materializations:string[];layers:string[];column_tests:string[];starter:Pipeline}>("/api/studio/palette");
}
export async function compilePipeline(p:Pipeline){
  return request<Compiled>("/api/studio/compile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(p)});
}
export async function getPipeline(id:string){
  return request<{pipeline:Pipeline;persisted:boolean}>(`/api/engagements/${encodeURIComponent(id)}/pipeline`);
}
export async function savePipeline(id:string,p:Pipeline){
  return request<{saved:boolean;compiled:Compiled}>(`/api/engagements/${encodeURIComponent(id)}/pipeline`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(p)});
}

/* ------------------------------------------------------------------ auth */
export type AuthUser={email:string;role:string;name:string};
export async function getAuthConfig(){return request<{auth_required:boolean;roles:string[];users:number}>("/api/auth/config")}
export async function login(email:string,password:string){
  const r=await request<{token:string;user:AuthUser}>("/api/auth/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,password})});
  setToken(r.token); return r;
}
export function logout(){setToken(null)}
export async function getMe(){return request<{user:AuthUser;auth_required:boolean}>("/api/auth/me")}
export async function listUsers(){return request<{items:any[]}>("/api/auth/users")}
export async function createUser(p:{email:string;password:string;name?:string;role?:string}){
  return request<{user:AuthUser}>("/api/auth/users",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(p)});
}
export async function setUserRole(email:string,role:string){
  return request<any>(`/api/auth/users/${encodeURIComponent(email)}/role`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({role})});
}
export async function deleteUser(email:string){
  return request<any>(`/api/auth/users/${encodeURIComponent(email)}`,{method:"DELETE"});
}

/* --------------------------------------------------------- pipeline runs */
export type RunNode={model:string;layer?:string;type?:string;status:string;row_count?:number;error?:string;elapsed_ms?:number;sample?:{columns:string[];rows:any[][]}};
export type RunTest={model:string;column:string;test:string;status:string;failing_rows?:number};
export type RunResult={engine:string;ok:boolean;errors:string[];nodes:RunNode[];tests:RunTest[];elapsed_ms?:number;message?:string;seeded_tables?:string[]};
export async function runPipeline(p:Pipeline,engine:"sandbox"|"databricks"="sandbox"){
  return request<RunResult>("/api/studio/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...p,engine})});
}
export async function runEngagementPipeline(id:string,p:Pipeline,engine:"sandbox"|"databricks"="sandbox"){
  return request<RunResult>(`/api/engagements/${encodeURIComponent(id)}/pipeline/run`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...p,engine})});
}

/* ------------------------------------------- AI provider diagnostics */
export type AiStatus = {
  configured: boolean; message: string; client: string; multi_provider: boolean;
  endpoint: string; model: string; provider: string; auth_header: string;
  api_key_present: boolean; timeout_seconds: number; providers?: any[];
};
export type AiTest = {
  ok: boolean; reachable: boolean; fault?: string; elapsed_ms: number;
  provider?: string; model?: string; response_preview?: string;
  message: string; remedy?: string; configuration: AiStatus;
};
export const getAiStatus = () => request<AiStatus>("/api/ai/status");
export const runAiTest = () => request<AiTest>("/api/ai/test", {method: "POST"});
