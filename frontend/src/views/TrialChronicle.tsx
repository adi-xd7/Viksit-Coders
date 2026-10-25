import React, { useState } from 'react';
import type { TrialRecord } from '../types';
import { Badge } from '../components/Badge';
import {
  History,
  ShieldCheck,
  Sword,
  Shield,
  Scale,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';

export interface TrialChronicleProps {
  trials: TrialRecord[];
  loading: boolean;
  onRefresh: () => void;
  onConveneDebate: () => void;
}

export const TrialChronicle: React.FC<TrialChronicleProps> = ({
  trials,
  loading,
  onRefresh,
  onConveneDebate,
}) => {
  const [expandedTrials, setExpandedTrials] = useState<Record<number, boolean>>({ 1: true });

  const toggleTrial = (trialNum: number) => {
    setExpandedTrials((prev) => ({
      ...prev,
      [trialNum]: !prev[trialNum],
    }));
  };

  if (loading && trials.length === 0) {
    return (
      <div className="archive-card text-center py-16 text-stone-500">
        <div className="inline-block animate-spin mb-2 text-xl">✦</div>
        <p>Unrolling Trial Chronicle Timeline...</p>
      </div>
    );
  }

  if (trials.length === 0) {
    return (
      <div className="archive-card text-center py-16 text-stone-600">
        <History size={44} className="mx-auto mb-3 text-stone-400" />
        <h3 className="text-xl font-serif mb-2">No Trial Chronicle Recorded</h3>
        <p className="text-sm text-stone-500 max-w-md mx-auto mb-4">
          No trials have been deliberated for this case. Convene the council to execute Trial 1.
        </p>
        <button type="button" onClick={onConveneDebate} className="btn btn-royal">
          <History size={15} />
          <span>Convene Initial Trial</span>
        </button>
      </div>
    );
  }

  return (
    <div>
      {/* Chronicle Header */}
      <div className="archive-card">
        <div className="card-title-row">
          <div className="card-title">
            <History size={24} />
            <span>Trial Chronicle & Audit Trace</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs font-mono text-stone-500">
              {trials.length} {trials.length === 1 ? 'trial' : 'trials'} executed
            </span>
            <button type="button" onClick={onRefresh} className="btn btn-stone btn-sm">
              Refresh Trace
            </button>
          </div>
        </div>
        <p className="text-xs text-stone-600">
          Chronological record of multi-agent debate trials, Heimdall pre-debate verification,
          Thor-Loki adversarial cross-examinations, formal concessions, and Odin's sufficiency determination.
        </p>
      </div>

      {/* Sequential Trial Timeline */}
      <div className="chronicle-timeline">
        {trials.map((trial) => {
          const isExpanded = expandedTrials[trial.trial_number] ?? false;
          const odin = trial.odin_adjudication;
          const heimdall = trial.heimdall_verification;
          const thorR1 = trial.thor_round1;
          const lokiR1 = trial.loki_round1;
          const thorR2 = trial.thor_round2;
          const lokiR2 = trial.loki_round2;

          return (
            <div key={trial.trial_number} className="chronicle-trial-card">
              <span className="chronicle-marker" aria-hidden="true" />

              {/* Trial Header Bar */}
              <div
                className="flex items-center justify-between cursor-pointer select-none pb-2 border-b border-stone-200"
                onClick={() => toggleTrial(trial.trial_number)}
              >
                <div className="flex items-center gap-3">
                  <span className="font-serif font-bold text-base text-stone-900">
                    Trial {trial.trial_number}{' '}
                    <span className="text-xs font-sans font-normal text-stone-500">
                      {trial.trial_number === 1 ? '(Initial Trial)' : `(Sufficiency Retry ${trial.trial_number - 1})`}
                    </span>
                  </span>
                  <Badge variant={trial.status === 'success' ? 'verified' : 'danger'}>
                    {trial.status.toUpperCase()}
                  </Badge>
                  {trial.is_evidence_sufficient ? (
                    <Badge variant="established">Evidence Sufficient</Badge>
                  ) : (
                    <Badge variant="contested">Gaps Identified ({trial.evidence_gaps_identified.length})</Badge>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  {trial.loop_stop_reason && (
                    <span className="text-xs font-mono bg-stone-100 text-stone-700 px-2 py-0.5 rounded border border-stone-200">
                      {trial.loop_stop_reason}
                    </span>
                  )}
                  <button type="button" className="btn-stone btn-sm p-1" aria-label="Toggle trial details">
                    {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  </button>
                </div>
              </div>

              {/* Expanded Trial Details */}
              {isExpanded && (
                <div className="mt-4 space-y-4">
                  {/* Heimdall Verification Gate */}
                  {heimdall && (
                    <div className="p-3 rounded border border-stone-200 bg-white">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-semibold uppercase text-stone-600 flex items-center gap-1">
                          <ShieldCheck size={14} className="text-green-700" />
                          <span>Heimdall Verification Gate</span>
                        </span>
                        <Badge variant={heimdall.is_verified ? 'verified' : 'danger'}>
                          {heimdall.is_verified ? 'Event Verified' : 'Gate Rejected'}
                        </Badge>
                      </div>
                      <div className="text-xs text-stone-700 font-serif mb-2">"{heimdall.summary}"</div>
                      <div className="text-xs font-mono text-stone-500 flex gap-4">
                        <span>Premises: {heimdall.premises_evaluated.length} verified</span>
                        <span>Admissible Docs: {heimdall.admissible_evidence.length}</span>
                        {heimdall.rejected_evidence.length > 0 && (
                          <span className="text-red-600">Rejected: {heimdall.rejected_evidence.length}</span>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Round 1: Advocacy Comparison */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '12px' }}>
                    {/* Thor Round 1 */}
                    <div className="p-3 rounded border border-amber-200 bg-amber-50">
                      <div className="text-xs font-semibold uppercase text-amber-900 flex items-center justify-between mb-1.5">
                        <span className="flex items-center gap-1">
                          <Sword size={13} />
                          <span>Thor — High-Exposure Advocacy</span>
                        </span>
                        <span className="font-mono text-xs font-normal">
                          {thorR1?.claims.length || 0} claims
                        </span>
                      </div>
                      <p className="text-xs text-amber-950 font-serif italic mb-2">
                        {thorR1?.summary || 'Independent investigation of upper-bound disruption severity.'}
                      </p>
                      {thorR1?.claims.slice(0, 2).map((c) => (
                        <div key={c.claim_id} className="text-xs bg-white p-1.5 rounded border border-amber-200 mb-1">
                          <span className="font-mono font-bold text-amber-800">{c.claim_id}: </span>
                          <span className="text-stone-800">{c.statement}</span>
                        </div>
                      ))}
                    </div>

                    {/* Loki Round 1 */}
                    <div className="p-3 rounded border border-stone-300 bg-stone-50">
                      <div className="text-xs font-semibold uppercase text-stone-800 flex items-center justify-between mb-1.5">
                        <span className="flex items-center gap-1">
                          <Shield size={13} />
                          <span>Loki — Low-Exposure Defense</span>
                        </span>
                        <span className="font-mono text-xs font-normal">
                          {lokiR1?.claims.length || 0} claims
                        </span>
                      </div>
                      <p className="text-xs text-stone-800 font-serif italic mb-2">
                        {lokiR1?.summary || 'Evaluating mitigating stocks, trade substitutions, and alternative corridors.'}
                      </p>
                      {lokiR1?.claims.slice(0, 2).map((c) => (
                        <div key={c.claim_id} className="text-xs bg-white p-1.5 rounded border border-stone-200 mb-1">
                          <span className="font-mono font-bold text-stone-700">{c.claim_id}: </span>
                          <span className="text-stone-800">{c.statement}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Round 2 Cross-Examinations & Concessions */}
                  <div className="p-3 rounded border border-stone-200 bg-white">
                    <div className="text-xs font-semibold uppercase text-stone-600 mb-2">
                      Round 2 Adversarial Attacks & Formal Concessions
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
                      <div>
                        <span className="font-semibold text-stone-800 block mb-1">Thor Cross-Exam & Concessions:</span>
                        <div className="font-mono text-stone-600">
                          Attacks launched: {thorR2?.attacks.length || 0} | Concessions made: {thorR2?.concessions.length || 0}
                        </div>
                      </div>
                      <div>
                        <span className="font-semibold text-stone-800 block mb-1">Loki Cross-Exam & Concessions:</span>
                        <div className="font-mono text-stone-600">
                          Attacks launched: {lokiR2?.attacks.length || 0} | Concessions made: {lokiR2?.concessions.length || 0}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Odin's Adjudication for this Trial */}
                  {odin && (
                    <div className="p-3 rounded border border-stone-300" style={{ backgroundColor: 'var(--color-warm-parchment)' }}>
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-xs font-semibold uppercase text-stone-800 flex items-center gap-1">
                          <Scale size={13} className="text-amber-800" />
                          <span>Odin's Trial Ruling</span>
                        </span>
                        <div className="flex gap-2">
                          <span className="text-xs font-mono text-green-900 font-bold">
                            {odin.established_claims.length} Established
                          </span>
                          <span className="text-xs font-mono text-amber-800 font-bold">
                            {odin.contested_claims.length} Contested
                          </span>
                          <span className="text-xs font-mono text-red-900 font-bold">
                            {odin.conceded_claims.length} Conceded
                          </span>
                        </div>
                      </div>
                      <div className="text-xs text-stone-800 font-serif">"{odin.summary}"</div>

                      {trial.evidence_gaps_identified.length > 0 && (
                        <div className="mt-2 pt-2 border-t border-stone-200">
                          <span className="text-xs font-semibold text-amber-900 block mb-1">
                            Sufficiency Gaps Identified in this Trial:
                          </span>
                          <ul className="text-xs text-stone-700 list-disc list-inside space-y-0.5">
                            {trial.evidence_gaps_identified.map((g, i) => (
                              <li key={i}>{g}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
