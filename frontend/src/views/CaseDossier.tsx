import React, { useState } from 'react';
import type { CaseFile, CaseSummaryResponse } from '../types';
import { Badge } from '../components/Badge';
import {
  FolderOpen,
  Calendar,
  ShieldCheck,
  Scale,
  Play,
  RotateCcw,
  CheckCircle,
  FileQuestion,
  HelpCircle,
  Sparkles,
  ArrowRight,
} from 'lucide-react';

export interface CaseDossierProps {
  caseFile: CaseFile | null;
  summary: CaseSummaryResponse | null;
  loading: boolean;
  debateRunning: boolean;
  onRunDebate: (caseId: string, maxRetries: number) => Promise<void>;
  onViewVerdict: () => void;
  onViewChronicle: () => void;
  onViewScroll: () => void;
}

export const CaseDossier: React.FC<CaseDossierProps> = ({
  caseFile,
  summary,
  loading,
  debateRunning,
  onRunDebate,
  onViewVerdict,
  onViewChronicle,
  onViewScroll,
}) => {
  const [maxRetries, setMaxRetries] = useState<number>(2);

  if (loading && !caseFile) {
    return (
      <div className="archive-card text-center py-16 text-stone-500">
        <div className="inline-block animate-spin mb-2 text-xl">✦</div>
        <p>Retrieving Case Dossier from Archive...</p>
      </div>
    );
  }

  if (!caseFile) {
    return (
      <div className="archive-card text-center py-16 text-stone-600">
        <FileQuestion size={40} className="mx-auto mb-3 text-stone-400" />
        <h3 className="text-xl font-serif mb-2">No Case Dossier Selected</h3>
        <p className="text-sm text-stone-500 max-w-md mx-auto mb-4">
          Select an active case from The Hall to inspect its parameters and convene the adversarial courtroom council.
        </p>
      </div>
    );
  }

  const hasResults = summary?.has_debate_result ?? false;

  const handleConvene = () => {
    onRunDebate(caseFile.case_id, maxRetries);
  };

  return (
    <div>
      {/* Dossier Header Card */}
      <div className="archive-card">
        <div className="card-title-row">
          <div className="card-title">
            <FolderOpen size={22} />
            <span>Dossier: {caseFile.case_id}</span>
          </div>
          <div className="flex items-center gap-2">
            {caseFile.is_verified && (
              <Badge variant="verified">
                <ShieldCheck size={11} className="inline mr-1" />
                Verified Premise
              </Badge>
            )}
            {hasResults ? (
              <Badge variant="established">Debated & Adjudicated</Badge>
            ) : (
              <Badge variant="neutral">Awaiting Convening</Badge>
            )}
          </div>
        </div>

        {/* Strategic Target Inquiry */}
        <div className="mb-6 p-4 rounded bg-stone-50 border border-stone-200" style={{ backgroundColor: 'var(--color-warm-parchment)' }}>
          <div className="text-xs font-semibold uppercase tracking-wider text-stone-500 mb-1 flex items-center gap-1">
            <HelpCircle size={13} className="text-amber-700" />
            <span>Focal Disruption Inquiry</span>
          </div>
          <div className="font-serif text-lg text-stone-900 leading-snug">
            "{caseFile.question}"
          </div>
        </div>

        {/* Dossier Metadata Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
          <div className="p-3 rounded border border-stone-200 bg-white">
            <div className="text-xs uppercase font-semibold text-stone-500 mb-1 flex items-center gap-1">
              <Calendar size={13} />
              <span>Simulated Clock Cutoff</span>
            </div>
            <div className="font-mono text-sm font-semibold text-stone-900">
              {caseFile.as_of_date}
            </div>
            <div className="text-xs text-stone-400 mt-1">Strict temporal gate enforced</div>
          </div>

          <div className="p-3 rounded border border-stone-200 bg-white">
            <div className="text-xs uppercase font-semibold text-stone-500 mb-1 flex items-center gap-1">
              <ShieldCheck size={13} />
              <span>Event Identifier</span>
            </div>
            <div className="font-mono text-sm font-semibold text-stone-900">
              {caseFile.event_id || 'Unassigned'}
            </div>
            <div className="text-xs text-stone-400 mt-1">Runemark corpus event code</div>
          </div>

          <div className="p-3 rounded border border-stone-200 bg-white">
            <div className="text-xs uppercase font-semibold text-stone-500 mb-1 flex items-center gap-1">
              <Scale size={13} />
              <span>Judicial Stages</span>
            </div>
            <div className="text-sm font-medium text-stone-900">
              Heimdall → Thor & Loki → Odin
            </div>
            <div className="text-xs text-stone-400 mt-1">Multi-trial sufficiency loop</div>
          </div>
        </div>

        {/* Action Panel: Convene Council */}
        <div
          className="p-5 rounded border border-amber-200 mt-6"
          style={{ backgroundColor: 'var(--color-antique-gold-subtle)', borderColor: '#dfcdb1' }}
        >
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div>
              <h4 className="font-serif text-base font-bold text-stone-900 flex items-center gap-2">
                <Scale size={18} className="text-amber-700" />
                <span>Convene the Courtroom Council</span>
              </h4>
              <p className="text-xs text-stone-600 mt-1 max-w-xl">
                Executes Heimdall verification, Thor advocacy, Loki counter-analysis, round 2 cross-examinations,
                formal concessions, and Odin's final judicial adjudication with bounded feedback.
              </p>
            </div>

            <div className="flex items-center gap-4 flex-wrap">
              <div className="flex items-center gap-2">
                <label htmlFor="max_retries_select" style={{ marginBottom: 0, textTransform: 'none', fontSize: '12px' }}>
                  Sufficiency Retries:
                </label>
                <select
                  id="max_retries_select"
                  value={maxRetries}
                  onChange={(e) => setMaxRetries(Number(e.target.value))}
                  disabled={debateRunning}
                  style={{ width: '80px', padding: '4px 8px', fontSize: '13px' }}
                >
                  <option value={0}>0 (Single Trial)</option>
                  <option value={1}>1 Retry</option>
                  <option value={2}>2 Retries (Standard)</option>
                  <option value={3}>3 Retries</option>
                </select>
              </div>

              <button
                type="button"
                onClick={handleConvene}
                disabled={debateRunning}
                className="btn btn-royal"
                style={{ minWidth: '190px' }}
              >
                {debateRunning ? (
                  <>
                    <RotateCcw size={15} className="animate-spin inline mr-1" />
                    <span>Council Deliberating...</span>
                  </>
                ) : (
                  <>
                    <Play size={15} />
                    <span>{hasResults ? 'Re-run Debate' : 'Convene Council'}</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {debateRunning && (
            <div className="mt-4 pt-3 border-t border-amber-200 text-xs text-stone-700 font-mono">
              <span className="font-bold text-amber-800">Deliberation in progress:</span> Running bounded multi-agent reasoning. Execution takes ~2-5s per trial in threadpool...
            </div>
          )}
        </div>
      </div>

      {/* Quick Navigation to Deliverables (if completed) */}
      {hasResults && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px' }}>
          <div className="archive-card mb-0 hover:border-amber-400 transition-all cursor-pointer" onClick={onViewVerdict}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold uppercase text-stone-500">Judicial Deliverable</span>
              <Scale size={16} className="text-amber-600" />
            </div>
            <h4 className="font-serif text-base font-bold text-stone-900 mb-1">Council Verdict</h4>
            <p className="text-xs text-stone-500 mb-3">Inspect Odin's formal ruling, claim evaluations, and evidentiary sufficiency.</p>
            <div className="text-xs font-semibold text-amber-700 flex items-center gap-1">
              <span>View Adjudication</span>
              <ArrowRight size={12} />
            </div>
          </div>

          <div className="archive-card mb-0 hover:border-amber-400 transition-all cursor-pointer" onClick={onViewChronicle}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold uppercase text-stone-500">Trial History</span>
              <CheckCircle size={16} className="text-amber-600" />
            </div>
            <h4 className="font-serif text-base font-bold text-stone-900 mb-1">Trial Chronicle</h4>
            <p className="text-xs text-stone-500 mb-3">Audit trace of trials, Loki attacks, Thor defenses, and concession rounds.</p>
            <div className="text-xs font-semibold text-amber-700 flex items-center gap-1">
              <span>Inspect Chronicle</span>
              <ArrowRight size={12} />
            </div>
          </div>

          <div className="archive-card mb-0 hover:border-amber-400 transition-all cursor-pointer" onClick={onViewScroll}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold uppercase text-stone-500">Executive Report</span>
              <Sparkles size={16} className="text-amber-600" />
            </div>
            <h4 className="font-serif text-base font-bold text-stone-900 mb-1">Executive Scroll</h4>
            <p className="text-xs text-stone-500 mb-3">Comprehensive royal intelligence briefing with exposure tables and bibliography.</p>
            <div className="text-xs font-semibold text-amber-700 flex items-center gap-1">
              <span>Read Executive Scroll</span>
              <ArrowRight size={12} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
