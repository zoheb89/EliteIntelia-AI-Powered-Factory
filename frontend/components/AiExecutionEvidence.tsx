'use client';
/**
 * AI Execution Evidence.
 *
 * "Is the AI being used? There is no evidence." — a stage that says COMPLETE
 * proves nothing about how it was produced. This panel answers that from
 * recorded fields only: every value shown is one the backend stamped on the
 * run. Nothing is inferred, and nothing is displayed when it was not recorded,
 * because an invented confidence score is worse than no score at all.
 */
import {BadgeCheck, ShieldAlert, Cpu, Clock, FileSearch} from 'lucide-react';

type Artifact = Record<string, any> | null | undefined;

const COUNTABLE = ['requirements', 'objectives', 'processes', 'actors', 'systems',
                   'sources', 'unknowns', 'assumptions', 'constraints', 'risks',
                   'next_steps', 'components', 'decisions', 'findings', 'questions'];

export function AiExecutionEvidence(
  {artifact, executionId, elapsedSeconds}:
  {artifact: Artifact; executionId?: string; elapsedSeconds?: number},
) {
  if (!artifact || typeof artifact !== 'object') return null;

  const mode = String(artifact.generation_mode || '');
  const degraded = mode === 'deterministic_evidence_only'
    || artifact.ai_enrichment === 'unavailable'
    || artifact.ai_enrichment === 'not_available_for_this_run';
  const isAi = mode === 'ai' && !degraded;

  // Nothing was recorded either way — say nothing rather than guess.
  if (!mode && !degraded) return null;

  const reason = artifact.ai_enrichment_reason || artifact.reason || '';
  const rows: [string, string][] = [];
  const push = (k: string, v: any) => {
    if (v !== undefined && v !== null && String(v).trim()) rows.push([k, String(v)]);
  };
  push('Execution', executionId);
  push('Provider', artifact.ai_provider);
  push('Model', artifact.ai_model);
  push('Client', artifact.ai_client);
  if (artifact.ai_elapsed_ms) push('Model time', `${(artifact.ai_elapsed_ms / 1000).toFixed(1)}s`);
  else if (elapsedSeconds) push('Stage time', `${elapsedSeconds}s`);

  const produced = COUNTABLE
    .map(k => [k, Array.isArray(artifact[k]) ? artifact[k].length : 0] as [string, number])
    .filter(([, n]) => n > 0);

  return (
    <section className={`aiEv ${isAi ? 'ok' : 'deg'}`}>
      <header>
        {isAi ? <BadgeCheck size={16} /> : <ShieldAlert size={16} />}
        <h4>{isAi ? 'AI generated — verified' : 'Deterministic fallback — no AI analysis'}</h4>
        <span className={`aiEvTag ${isAi ? 't-ai' : 't-det'}`}>
          {isAi ? 'AI_GENERATED' : 'EVIDENCE_ONLY'}
        </span>
      </header>

      <p className="aiEvLead">
        {isAi
          ? 'A model request was issued, a response was received and validated, and the output below was persisted from it.'
          : 'No model output was applied. Everything below comes from the supplied documents alone.'}
      </p>

      {!isAi && reason && <code className="aiEvReason">{String(reason)}</code>}

      {rows.length > 0 && (
        <dl className="aiEvGrid">
          {rows.map(([k, v]) => (
            <div key={k}>
              <dt>{k === 'Model' ? <Cpu size={11} /> : k === 'Execution'
                    ? <FileSearch size={11} /> : <Clock size={11} />} {k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      )}

      {produced.length > 0 && (
        <div className="aiEvCounts">
          <strong>Produced</strong>
          {produced.map(([k, n]) => (
            <span key={k}>{n} {k.replace(/_/g, ' ')}</span>
          ))}
        </div>
      )}
    </section>
  );
}
