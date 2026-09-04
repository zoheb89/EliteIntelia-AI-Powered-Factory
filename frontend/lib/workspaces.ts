/**
 * Workspace metadata. Previously all 9 workspace routes rendered one generic
 * page, so the UI could not express what each stage actually produces. Each
 * entry now declares its backend stage, the artifact kinds it surfaces, its
 * execution pipeline and the personas that own it.
 */
export type WorkspaceDef = {
  route: string;
  nav: string;
  title: string;
  blurb: string;
  stage: string;                       // backend stage id for POST /stages/{stage}
  artifactKinds: string[];             // artifact kinds to surface
  pipeline: [string, string, string][]; // [id, label, description]
  requires?: string;                   // upstream stage that must be complete
  approvalKind?: string;               // artifact type needing human approval
  owners: string[];                    // persona role ids
  metrics?: {label: string; key: string}[];
};

export const WORKSPACES: Record<string, WorkspaceDef> = {
  '/discovery': {
    route: '/discovery',
    nav: 'Discovery & Assess',
    title: 'Discovery & Assessment',
    blurb: 'Turn sparse business intent, documents and interviews into structured, evidence-backed discovery facts.',
    stage: 'discovery',
    artifactKinds: ['discovery', 'intake_pack'],
    pipeline: [['discovery', 'Discovery', 'Extract objectives, actors, systems, sources, requirements and unknowns from the evidence.']],
    owners: ['consultant', 'business_analyst', 'architect'],
  },
  '/architecture': {
    route: '/architecture',
    nav: 'Architecture',
    title: 'Solution Architecture',
    blurb: 'Generate a platform-neutral blueprint, compare target platforms and capture architecture decisions.',
    stage: 'architecture',
    artifactKinds: ['blueprint', 'assessment', 'environment_assessment', 'architecture'],
    pipeline: [
      ['environment_assessment', 'Environment Assessment', 'Evaluate customer platform, environment, access, capabilities and provisioning evidence.'],
      ['assessment', 'Current-State Assessment', 'Build the evidence-based readiness, maturity, risks, dependencies and unknowns.'],
      ['blueprint', 'Solution Blueprint', 'Generate the target architecture, platform fit, data flow, security and operating model.'],
    ],
    requires: 'discovery',
    approvalKind: 'blueprint',
    owners: ['architect', 'consultant', 'platform_engineer'],
  },
  '/platform': {
    route: '/platform',
    nav: 'Platform & Environment',
    title: 'Platform & Environment',
    blurb: 'Select the governed target platform, verify connectivity and prepare the provisioning plan.',
    stage: 'platform',
    artifactKinds: ['platform', 'environment_assessment'],
    pipeline: [['platform', 'Platform Readiness', 'Confirm the target platform, connection evidence and provisioning path.']],
    requires: 'blueprint',
    owners: ['platform_engineer', 'architect', 'devops'],
  },
  '/engineering': {
    route: '/engineering',
    nav: 'Data & Engineering',
    title: 'AI Engineering Factory',
    blurb: 'Generate resumable ingestion, Bronze/Silver/Gold transformations and data-quality components.',
    stage: 'engineering',
    artifactKinds: ['engineering', 'metadata'],
    pipeline: [
      ['metadata', 'Engineering Metadata', 'Generate canonical metadata from the approved Solution Blueprint.'],
      ['engineering', 'Data Engineering', 'Generate resumable Bronze/Silver/Gold, quality, orchestration and testing components.'],
    ],
    requires: 'blueprint',
    owners: ['data_engineer', 'ai_engineer', 'architect'],
  },
  '/studio': {
    route: '/studio',
    nav: 'Transformation Studio',
    title: 'Transformation Studio',
    blurb: 'Design pipelines visually; dbt models, tests and PySpark are generated from the DAG.',
    stage: 'engineering',
    artifactKinds: ['pipeline', 'dbt_project', 'pyspark_job', 'column_lineage'],
    pipeline: [],
    owners: ['data_engineer', 'ai_engineer', 'analytics', 'bi_developer', 'architect'],
  },
  '/ai-analytics': {
    route: '/ai-analytics',
    nav: 'AI & Analytics',
    title: 'AI & Analytics',
    blurb: 'Create governed semantic products, BI-ready datasets, GenAI patterns and agent-ready interfaces.',
    stage: 'bi',
    artifactKinds: ['bi', 'application'],
    pipeline: [['bi', 'AI & BI Products', 'Generate semantic models, KPI definitions, BI datasets and GenAI/agent patterns.']],
    requires: 'engineering',
    owners: ['bi_developer', 'analytics', 'ai_engineer', 'product_owner'],
  },
  '/validation': {
    route: '/validation',
    nav: 'Validation & QA',
    title: 'Validation & Quality Gates',
    blurb: 'Validate data quality, reconciliation, business rules, lineage and acceptance evidence.',
    stage: 'qa',
    artifactKinds: ['qa', 'validation', 'full_qa'],
    pipeline: [['qa', 'Quality Gates', 'Run data-quality, reconciliation, business-rule and lineage validation.']],
    requires: 'engineering',
    owners: ['qa', 'data_engineer', 'delivery_manager'],
  },
  '/deploy': {
    route: '/deploy',
    nav: 'Deploy & Activate',
    title: 'Deploy & Activate',
    blurb: 'Prepare deployment plans, approvals, environment checks and production activation.',
    stage: 'full_qa',
    artifactKinds: ['full_qa', 'platform'],
    pipeline: [['full_qa', 'Deployment Readiness', 'Consolidate quality, approval and environment evidence for release.']],
    requires: 'qa',
    owners: ['devops', 'platform_engineer', 'delivery_manager'],
  },
  '/monitoring': {
    route: '/monitoring',
    nav: 'Monitoring',
    title: 'Monitoring & Operations',
    blurb: 'Monitor pipelines, data quality, model health, freshness and business outcomes.',
    stage: 'full_qa',
    artifactKinds: ['full_qa', 'qa'],
    pipeline: [],
    owners: ['devops', 'platform_engineer', 'analytics', 'delivery_manager'],
  },
  '/knowledge': {
    route: '/knowledge',
    nav: 'Knowledge Center',
    title: 'Knowledge Center',
    blurb: 'Reusable patterns, architecture decisions, evidence and delivery assets across the portfolio.',
    stage: 'full_qa',
    artifactKinds: [],
    pipeline: [],
    owners: ['consultant', 'architect', 'project_manager'],
  },
};

export const STAGE_ORDER = [
  'intake', 'discovery', 'environment_assessment', 'assessment',
  'blueprint', 'platform', 'metadata', 'engineering', 'qa', 'bi', 'full_qa',
];
