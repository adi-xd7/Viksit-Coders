import React, { useState } from 'react';
import type { TrialRecord, Claim, CrossExamination, Concession, ClaimRuling } from '../types';
import { Badge } from '../components/Badge';
import {
  History,
  ShieldCheck,
  Sword,
  Shield,
  Scale,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Target,
  FileText,
  CheckCircle,
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
  const [activeTabPerTrial, setActiveTabPerTrial] = useState<Record<number, 'all' | 'r1' | 'r2' | 'concessions' | 'odin'>>({});
  const [odinRulingFilter, setOdinRulingFilter] = useState<'all' | 'established' | 'contested' | 'conceded'>('all');

  const toggleTrial = (trialNum: number) => {
    setExpandedTrials((prev) => ({
      ...prev,
      [trialNum]: !prev[trialNum],
    }));
  };

  const setTrialTab = (trialNum: number, tab: 'all' | 'r1' | 'r2' | 'concessions' | 'odin') => {
    setActiveTabPerTrial((prev) => ({
      ...prev,
      [trialNum]: tab,
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
            <span>Trial Chronicle & Adversarial Debate Transcript</span>
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
          Chronological, evidence-grounded courtroom record of Thor's high-exposure advocacy, Loki's mitigating defense,
          Round 2 cross-examination challenges, formal concessions, and Odin's final judicial determination.
        </p>
      </div>

      {/* Sequential Trial Timeline */}
      <div className="chronicle-timeline">
        {trials.map((trial) => {
          const isExpanded = expandedTrials[trial.trial_number] ?? true;
          const activeTab = activeTabPerTrial[trial.trial_number] ?? 'all';
          const odin = trial.odin_adjudication;
          const heimdall = trial.heimdall_verification;
          const thorR1 = trial.thor_round1;
          const lokiR1 = trial.loki_round1;
          const thorR2 = trial.thor_round2;
          const lokiR2 = trial.loki_round2;

          const thorClaims: Claim[] = thorR1?.claims || [];
          const lokiClaims: Claim[] = lokiR1?.claims || [];

          // Map all claims for instant lookup during cross-examination & concessions
          const claimsMap = new Map<string, Claim>();
          [...thorClaims, ...lokiClaims].forEach((c) => claimsMap.set(c.claim_id, c));

          // Map Odin rulings by claim_id
          const rulingsMap = new Map<string, ClaimRuling>();
          (odin?.claim_rulings || []).forEach((r) => rulingsMap.set(r.claim_id, r));

          // Combine attacks from Thor and Loki
          const thorAttacks: CrossExamination[] = thorR2?.attacks || [];
          const lokiAttacks: CrossExamination[] = lokiR2?.attacks || [];
          const allAttacks = [...thorAttacks, ...lokiAttacks];

          // Combine concessions from Thor and Loki
          const thorConcessions: Concession[] = thorR2?.concessions || [];
          const lokiConcessions: Concession[] = lokiR2?.concessions || [];
          const allConcessions = [...thorConcessions, ...lokiConcessions];

          const gapsList = trial.evidence_gaps_identified || [];
          const isRealEvent = heimdall?.is_event_real ?? heimdall?.is_verified ?? true;
          const premises = heimdall?.premises || heimdall?.premises_evaluated || [];
          const evidenceExamined = heimdall?.evidence_examined || [];

          return (
            <div key={trial.trial_number} className="chronicle-trial-card">
              <span className="chronicle-marker" aria-hidden="true" />

              {/* Trial Header Bar */}
              <div
                className="flex items-center justify-between cursor-pointer select-none pb-3 border-b border-stone-200"
                onClick={() => toggleTrial(trial.trial_number)}
              >
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="font-serif font-bold text-lg text-stone-900">
                    Trial {trial.trial_number}{' '}
                    <span className="text-xs font-sans font-normal text-stone-500">
                      {trial.trial_number === 1 ? '(Initial Hearing)' : `(Sufficiency Loop Trial ${trial.trial_number})`}
                    </span>
                  </span>
                  <Badge variant={trial.status === 'success' ? 'verified' : 'danger'}>
                    {(trial.status || 'SUCCESS').toUpperCase()}
                  </Badge>
                  {trial.is_evidence_sufficient ? (
                    <Badge variant="established">Evidence Sufficient</Badge>
                  ) : (
                    <Badge variant="contested">Gaps Identified ({gapsList.length})</Badge>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  {(trial.loop_stop_reason || trial.gap_resolution_summary) && (
                    <span className="text-xs font-mono bg-stone-100 text-stone-700 px-2.5 py-1 rounded border border-stone-200">
                      {trial.loop_stop_reason || trial.gap_resolution_summary}
                    </span>
                  )}
                  <button type="button" className="btn-stone btn-sm p-1" aria-label="Toggle trial details">
                    {isExpanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                  </button>
                </div>
              </div>

              {/* Expanded Trial Details */}
              {isExpanded && (
                <div className="mt-5 space-y-6">
                  {/* Stage Navigation Filter Chips */}
                  <div className="flex items-center gap-2 flex-wrap pb-2 border-b border-stone-200">
                    <span className="text-xs font-semibold uppercase text-stone-500 mr-1">View Stages:</span>
                    <button
                      type="button"
                      onClick={() => setTrialTab(trial.trial_number, 'all')}
                      className={`btn btn-sm ${activeTab === 'all' ? 'btn-royal' : 'btn-stone'}`}
                    >
                      Full Proceeding
                    </button>
                    <button
                      type="button"
                      onClick={() => setTrialTab(trial.trial_number, 'r1')}
                      className={`btn btn-sm ${activeTab === 'r1' ? 'btn-royal' : 'btn-stone'}`}
                    >
                      Round 1 Advocacy ({thorClaims.length + lokiClaims.length})
                    </button>
                    <button
                      type="button"
                      onClick={() => setTrialTab(trial.trial_number, 'r2')}
                      className={`btn btn-sm ${activeTab === 'r2' ? 'btn-royal' : 'btn-stone'}`}
                    >
                      Round 2 Attacks ({allAttacks.length})
                    </button>
                    <button
                      type="button"
                      onClick={() => setTrialTab(trial.trial_number, 'concessions')}
                      className={`btn btn-sm ${activeTab === 'concessions' ? 'btn-royal' : 'btn-stone'}`}
                    >
                      Concessions ({allConcessions.length})
                    </button>
                    <button
                      type="button"
                      onClick={() => setTrialTab(trial.trial_number, 'odin')}
                      className={`btn btn-sm ${activeTab === 'odin' ? 'btn-royal' : 'btn-stone'}`}
                    >
                      Odin Verdict
                    </button>
                  </div>

                  {/* STAGE 0: Heimdall Verification Gate */}
                  {(activeTab === 'all' || activeTab === 'r1') && heimdall && (
                    <div className="debate-stage-box">
                      <div className="stage-header">
                        <div className="stage-title">
                          <ShieldCheck size={20} className="text-emerald-700" />
                          <span>Stage 0: Heimdall Pre-Trial Verification Gate</span>
                        </div>
                        <Badge variant={isRealEvent ? 'verified' : 'danger'}>
                          {isRealEvent ? 'Disruption Event Verified' : 'Gate Rejected'}
                        </Badge>
                      </div>

                      <div className="gate-status-banner">
                        <div className="flex items-center gap-2">
                          <CheckCircle size={16} className="text-emerald-700" />
                          <span className="text-xs font-bold text-emerald-950 uppercase tracking-wide">
                            {isRealEvent ? 'Disruption Event Cleared For Courtroom Debate' : 'Event Verification Failed'}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 text-xs font-mono text-stone-600">
                          <span><strong>{premises.length}</strong> Premises Verified</span>
                          <span>·</span>
                          <span><strong>{evidenceExamined.length}</strong> Corpus Documents Examined</span>
                        </div>
                      </div>

                      {premises.length > 0 && (
                        <div className="space-y-2 mt-3">
                          <span className="text-xs font-semibold uppercase text-stone-600 block">
                            Evaluated Foundational Premises ({premises.length}):
                          </span>
                          {premises.map((p, idx) => (
                            <div key={idx} className="p-3 rounded bg-white border border-stone-200 text-xs">
                              <div className="flex items-center justify-between mb-1.5 flex-wrap gap-2">
                                <div className="flex items-center gap-2">
                                  <span className="font-mono font-bold text-stone-800 bg-stone-100 px-2 py-0.5 rounded border border-stone-200">
                                    {p.premise_id || `PREMISE-${idx + 1}`}
                                  </span>
                                  {p.confidence != null && (
                                    <span className="font-mono text-stone-500 font-semibold">
                                      {Math.round(p.confidence * 100)}% Conf
                                    </span>
                                  )}
                                </div>
                                <Badge variant={p.status === 'verified' ? 'verified' : p.status === 'contradicted' ? 'danger' : 'warning'}>
                                  {(p.status || 'VERIFIED').toUpperCase()}
                                </Badge>
                              </div>

                              <div className="font-serif text-sm font-semibold text-stone-900 mb-1 leading-snug">
                                "{p.premise}"
                              </div>

                              <div className="text-stone-700 text-xs mb-2 leading-relaxed">
                                {p.reasoning}
                              </div>

                              {p.citations && p.citations.length > 0 && (
                                <div className="citation-callout-list">
                                  {p.citations.map((c, ci) => (
                                    <div key={ci} className="citation-callout-item">
                                      <div className="flex items-center justify-between mb-0.5">
                                        <span className="citation-doc-tag">
                                          {c.doc_id} {c.paragraph || ''}
                                        </span>
                                        <span className="text-xs text-stone-500 font-mono">
                                          {c.source_name ? `${c.source_name} · ` : ''}Tier {c.reliability_tier || 1}
                                        </span>
                                      </div>
                                      {c.quote_or_datapoint && (
                                        <div className="italic text-stone-700">"{c.quote_or_datapoint}"</div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}

                      {heimdall.summary && (
                        <details className="verbatim-disclosure">
                          <summary>📜 View Full Heimdall Gate Audit Report</summary>
                          <div className="verbatim-content-box">
                            {heimdall.summary}
                          </div>
                        </details>
                      )}
                    </div>
                  )}

                  {/* STAGE 1: Round 1 Sourced Advocacy Duel */}
                  {(activeTab === 'all' || activeTab === 'r1') && (
                    <div className="debate-stage-box">
                      <div className="stage-header">
                        <div className="stage-title">
                          <Scale size={20} className="text-amber-700" />
                          <span>Stage 1: Round 1 Sourced Advocacy Duel</span>
                        </div>
                        <span className="text-xs text-stone-500 font-mono">
                          Thor ({thorClaims.length} high-exposure claims) vs. Loki ({lokiClaims.length} mitigating claims)
                        </span>
                      </div>

                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px' }}>
                        {/* Thor Podia (High-Exposure Assertions) */}
                        <div className="agent-podium-thor">
                          <div className="podium-header">
                            <div className="podium-agent-tag agent-thor-color">
                              <Sword size={18} />
                              <span>Thor — High-Exposure Advocate</span>
                            </div>
                            <span className="font-mono text-xs font-semibold px-2 py-0.5 rounded bg-amber-100 text-amber-900 border border-amber-200">
                              {thorClaims.length} Claims
                            </span>
                          </div>

                          <p className="text-xs text-stone-700 mb-3 leading-relaxed">
                            <strong>Prosecuting Stance:</strong> Independent investigation proving structural collapse, upper-bound trade value loss, supply deficits, and infrastructure bottlenecks.
                          </p>

                          <div className="space-y-3">
                            {thorClaims.map((claim) => {
                              const est = claim.exposure_estimate || claim.adjudicated_range;
                              const lowerVal = est?.lower_bound ?? est?.min_estimate;
                              const upperVal = est?.upper_bound ?? est?.max_estimate;
                              const ruling = rulingsMap.get(claim.claim_id);

                              return (
                                <div key={claim.claim_id} className="claim-card">
                                  <div className="claim-meta-row">
                                    <span className="font-mono font-bold text-xs text-amber-900 bg-amber-50 px-2 py-0.5 rounded border border-amber-200">
                                      {claim.claim_id}
                                    </span>
                                    <div className="flex items-center gap-1.5 flex-wrap">
                                      <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-stone-100 text-stone-600 border border-stone-200">
                                        {claim.claim_type === 'sourced_fact' ? 'Sourced Fact' : 'Inference'}
                                      </span>
                                      {ruling && (
                                        <Badge variant={ruling.ruling}>
                                          Ruling: {ruling.ruling.toUpperCase()}
                                        </Badge>
                                      )}
                                    </div>
                                  </div>

                                  <div className="claim-statement-text">
                                    "{claim.statement}"
                                  </div>

                                  {est && (
                                    <div className="claim-exposure-chip">
                                      <span>Asserted Exposure:</span>
                                      <strong>
                                        {lowerVal != null ? `${lowerVal}%` : ''}
                                        {lowerVal != null && upperVal != null ? ' – ' : ''}
                                        {upperVal != null ? `${upperVal}%` : ''} {est.unit}
                                      </strong>
                                      <span className="text-stone-500 font-normal">
                                        ({est.country} {est.sector} {est.period || ''})
                                      </span>
                                    </div>
                                  )}

                                  {/* Supporting Citations */}
                                  {claim.citations && claim.citations.length > 0 && (
                                    <div className="citation-callout-list">
                                      {claim.citations.map((c, ci) => (
                                        <div key={ci} className="citation-callout-item">
                                          <div className="flex items-center justify-between mb-0.5">
                                            <span className="citation-doc-tag">
                                              {c.doc_id} {c.paragraph || ''}
                                            </span>
                                            <span className="text-xs text-stone-500 font-mono">
                                              {c.source_name ? `${c.source_name} · ` : ''}Tier {c.reliability_tier || 1}
                                            </span>
                                          </div>
                                          <div className="italic text-stone-700">"{c.quote_or_datapoint}"</div>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </div>

                        {/* Loki Podia (Low-Exposure Mitigations) */}
                        <div className="agent-podium-loki">
                          <div className="podium-header">
                            <div className="podium-agent-tag agent-loki-color">
                              <Shield size={18} />
                              <span>Loki — Low-Exposure Defense</span>
                            </div>
                            <span className="font-mono text-xs font-semibold px-2 py-0.5 rounded bg-green-100 text-green-900 border border-green-200">
                              {lokiClaims.length} Claims
                            </span>
                          </div>

                          <p className="text-xs text-stone-700 mb-3 leading-relaxed">
                            <strong>Defense Stance:</strong> Counter-analysis establishing commercial cushions, inventory buffers, contract delayed terms, and overland trade substitutions.
                          </p>

                          <div className="space-y-3">
                            {lokiClaims.map((claim) => {
                              const est = claim.exposure_estimate || claim.adjudicated_range;
                              const lowerVal = est?.lower_bound ?? est?.min_estimate;
                              const upperVal = est?.upper_bound ?? est?.max_estimate;
                              const ruling = rulingsMap.get(claim.claim_id);

                              return (
                                <div key={claim.claim_id} className="claim-card">
                                  <div className="claim-meta-row">
                                    <span className="font-mono font-bold text-xs text-emerald-900 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                                      {claim.claim_id}
                                    </span>
                                    <div className="flex items-center gap-1.5 flex-wrap">
                                      <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-stone-100 text-stone-600 border border-stone-200">
                                        {claim.claim_type === 'sourced_fact' ? 'Sourced Fact' : 'Inference'}
                                      </span>
                                      {ruling && (
                                        <Badge variant={ruling.ruling}>
                                          Ruling: {ruling.ruling.toUpperCase()}
                                        </Badge>
                                      )}
                                    </div>
                                  </div>

                                  <div className="claim-statement-text">
                                    "{claim.statement}"
                                  </div>

                                  {est && (
                                    <div className="claim-exposure-chip" style={{ backgroundColor: '#eef4f0', borderColor: '#c3d8ca', color: '#1f482d' }}>
                                      <span>Mitigated Exposure:</span>
                                      <strong>
                                        {lowerVal != null ? `${lowerVal}%` : ''}
                                        {lowerVal != null && upperVal != null ? ' – ' : ''}
                                        {upperVal != null ? `${upperVal}%` : ''} {est.unit}
                                      </strong>
                                      <span className="text-stone-500 font-normal">
                                        ({est.country} {est.sector} {est.period || ''})
                                      </span>
                                    </div>
                                  )}

                                  {/* Supporting Citations */}
                                  {claim.citations && claim.citations.length > 0 && (
                                    <div className="citation-callout-list">
                                      {claim.citations.map((c, ci) => (
                                        <div key={ci} className="citation-callout-item">
                                          <div className="flex items-center justify-between mb-0.5">
                                            <span className="citation-doc-tag">
                                              {c.doc_id} {c.paragraph || ''}
                                            </span>
                                            <span className="text-xs text-stone-500 font-mono">
                                              {c.source_name ? `${c.source_name} · ` : ''}Tier {c.reliability_tier || 1}
                                            </span>
                                          </div>
                                          <div className="italic text-stone-700">"{c.quote_or_datapoint}"</div>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* STAGE 2: Round 2 Cross-Examination Attacks */}
                  {(activeTab === 'all' || activeTab === 'r2') && (
                    <div className="debate-stage-box">
                      <div className="stage-header">
                        <div className="stage-title">
                          <Target size={20} className="text-rose-700" />
                          <span>Stage 2: Round 2 Adversarial Cross-Examination Attacks</span>
                        </div>
                        <span className="text-xs text-stone-500 font-mono">
                          {allAttacks.length} formal challenges launched
                        </span>
                      </div>

                      {allAttacks.length === 0 ? (
                        <div className="py-6 text-center text-stone-500 text-xs italic">
                          No cross-examination attacks recorded in this trial.
                        </div>
                      ) : (
                        <div className="space-y-4">
                          {allAttacks.map((attack, ai) => {
                            const challenger = (attack.challenger || attack.attacker || 'advocate').toLowerCase();
                            const challengeId = attack.challenge_id || attack.attack_id || `ATTACK-${ai + 1}`;
                            const challengeType = attack.challenge_type || attack.attack_type || 'challenge';
                            const objection = attack.objection || 'Objection to opponent factual premise';
                            const reasoning = attack.reasoning || attack.argument || '';
                            const counterCitations = attack.counter_citations || [];

                            const isThorChallenger = challenger === 'thor';
                            const targetClaim = claimsMap.get(attack.target_claim_id);

                            return (
                              <div key={challengeId} className="attack-card">
                                <div className="attack-header">
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <span className="font-mono font-bold text-xs px-2.5 py-1 rounded bg-stone-900 text-white">
                                      {challengeId}
                                    </span>
                                    <span className={`text-xs font-bold uppercase tracking-wider ${isThorChallenger ? 'text-amber-800' : 'text-emerald-800'}`}>
                                      {isThorChallenger ? '⚡ THOR CHALLENGES LOKI' : '🐍 LOKI CHALLENGES THOR'}
                                    </span>
                                    <span className="text-stone-400">➔</span>
                                    <span className="attack-target-badge">
                                      Target: {attack.target_claim_id}
                                    </span>
                                  </div>

                                  <span className="font-mono text-xs px-2.5 py-0.5 rounded bg-rose-100 text-rose-900 border border-rose-200 font-semibold uppercase">
                                    {challengeType.replace(/_/g, ' ')}
                                  </span>
                                </div>

                                {/* Target Claim Context Box */}
                                {targetClaim && (
                                  <div className="attack-target-quote-box">
                                    <div className="font-bold text-stone-700 text-xs mb-1">
                                      🎯 Contested Proposition ({targetClaim.claim_id}):
                                    </div>
                                    <div className="italic font-serif text-stone-900">"{targetClaim.statement}"</div>
                                  </div>
                                )}

                                <div className="attack-objection-box">
                                  <div className="text-xs uppercase font-sans tracking-wider text-rose-900 mb-1 font-semibold">
                                    Formal Objection:
                                  </div>
                                  <div className="font-serif text-base text-rose-950 font-bold leading-snug">
                                    "{objection}"
                                  </div>
                                </div>

                                <div className="attack-reasoning-body">
                                  <strong className="text-stone-900 block mb-1 font-sans uppercase text-xs tracking-wider">
                                    Detailed Evidentiary Argument:
                                  </strong>
                                  <p className="m-0 leading-relaxed">{reasoning}</p>
                                </div>

                                {counterCitations.length > 0 ? (
                                  <div className="mt-3">
                                    <span className="text-xs font-semibold text-rose-900 block mb-1.5 uppercase tracking-wide">
                                      Counter-Evidence Proving Flaw ({counterCitations.length}):
                                    </span>
                                    <div className="citation-callout-list">
                                      {counterCitations.map((cc, cci) => (
                                        <div key={cci} className="citation-callout-item" style={{ borderColor: '#f1d2c6' }}>
                                          <div className="flex items-center justify-between mb-0.5">
                                            <span className="citation-doc-tag" style={{ backgroundColor: '#fbece7', color: '#872e12' }}>
                                              {cc.doc_id} {cc.paragraph || ''}
                                            </span>
                                            <span className="text-xs text-stone-500 font-mono">
                                              {cc.source_name ? `${cc.source_name} · ` : ''}Tier {cc.reliability_tier || 2} · {cc.publication_date || ''}
                                            </span>
                                          </div>
                                          <div className="italic text-stone-800">"{cc.quote_or_datapoint}"</div>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                ) : (
                                  <div className="text-xs font-mono text-stone-500 bg-stone-50 p-2 rounded border border-stone-200">
                                    ✓ No contradictory counter-evidence found in corpus; claim accepted as factual.
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}

                  {/* STAGE 3: Formal Concessions & Defense Positions */}
                  {(activeTab === 'all' || activeTab === 'concessions') && (
                    <div className="debate-stage-box">
                      <div className="stage-header">
                        <div className="stage-title">
                          <FileText size={20} className="text-stone-800" />
                          <span>Stage 3: Formal Courtroom Concessions & Yielded Positions</span>
                        </div>
                        <span className="text-xs text-stone-500 font-mono">
                          {allConcessions.length} formal responses entered into record
                        </span>
                      </div>

                      {allConcessions.length === 0 ? (
                        <div className="py-6 text-center text-stone-500 text-xs italic">
                          No formal concessions or defensive responses recorded in this trial.
                        </div>
                      ) : (
                        <div className="space-y-4">
                          {allConcessions.map((conc) => {
                            const agentName = (conc.agent || conc.advocate || 'advocate').toLowerCase();
                            const isLoki = agentName === 'loki';
                            const action = conc.action || 'concede';
                            const isConcede = action === 'concede';
                            const isDefend = action === 'defend';
                            const adjustedList = conc.adjusted_estimates || (conc.adjusted_range ? [conc.adjusted_range] : []);
                            const targetClaim = claimsMap.get(conc.target_claim_id);

                            const cardClass = isConcede
                              ? 'concession-card concession-card-concede'
                              : isDefend
                              ? 'concession-card concession-card-defend'
                              : 'concession-card concession-card-adjust';

                            return (
                              <div key={conc.concession_id} className={cardClass}>
                                <div className="concession-header">
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <span className="font-mono font-bold text-xs px-2.5 py-1 rounded bg-stone-800 text-white">
                                      {conc.concession_id}
                                    </span>
                                    <span className={`text-xs font-bold uppercase tracking-wider ${isConcede ? 'text-red-900' : isDefend ? 'text-emerald-900' : 'text-amber-900'}`}>
                                      {isConcede
                                        ? `${isLoki ? '🐍 LOKI' : '⚡ THOR'} FORMALLY CONCEDES POSITION`
                                        : isDefend
                                        ? `${isLoki ? '🐍 LOKI' : '⚡ THOR'} DEFENDS ORIGINAL POSITION`
                                        : `${isLoki ? '🐍 LOKI' : '⚡ THOR'} ADJUSTS EXPOSURE BOUNDS`}
                                    </span>
                                    <span className="text-stone-400 mx-1">➔</span>
                                    <span className="font-mono text-xs px-2 py-0.5 rounded bg-stone-100 text-stone-800 border border-stone-200">
                                      On Claim {conc.target_claim_id}
                                    </span>
                                    {conc.target_challenge_id && (
                                      <span className="text-xs text-stone-500 font-mono">
                                        (under challenge {conc.target_challenge_id})
                                      </span>
                                    )}
                                  </div>

                                  <Badge variant={isConcede ? 'conceded' : isDefend ? 'verified' : 'contested'}>
                                    ACTION: {action.toUpperCase()}
                                  </Badge>
                                </div>

                                {/* Target Claim Context */}
                                {targetClaim && (
                                  <div className="attack-target-quote-box">
                                    <div className="font-bold text-stone-700 text-xs mb-1">
                                      Subject Claim ({targetClaim.claim_id}):
                                    </div>
                                    <div className="italic font-serif text-stone-900">"{targetClaim.statement}"</div>
                                  </div>
                                )}

                                <div className="concession-reason-box">
                                  <div className="font-bold text-stone-900 text-xs mb-1.5 uppercase tracking-wide">
                                    {isConcede
                                      ? 'Evidence-Grounded Concession Rationale:'
                                      : isDefend
                                      ? 'Evidence-Grounded Defense Rationale:'
                                      : 'Adjustment Rationale:'}
                                  </div>
                                  <p className="m-0 leading-relaxed italic text-stone-900">"{conc.reason}"</p>
                                </div>

                                {adjustedList.length > 0 && (
                                  <div className="mt-2.5 p-3 rounded bg-amber-50/70 border border-amber-200 text-xs font-mono text-amber-950">
                                    <strong className="text-amber-900 block mb-1">Revised Quantitative Exposure Bounds:</strong>
                                    {adjustedList.map((adj, adji) => (
                                      <div key={adji} className="flex gap-2">
                                        <span>• {adj.country} {adj.sector} ({adj.metric}):</span>
                                        <strong>
                                          {adj.lower_bound ?? adj.min_estimate}% – {adj.upper_bound ?? adj.max_estimate}% {adj.unit}
                                        </strong>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}

                  {/* STAGE 4: Odin's Final Judicial Adjudication for this Trial */}
                  {(activeTab === 'all' || activeTab === 'odin') && odin && (
                    <div className="debate-stage-box" style={{ borderColor: 'var(--color-antique-gold)', backgroundColor: 'var(--color-aged-ivory)' }}>
                      <div className="stage-header">
                        <div className="stage-title">
                          <Scale size={20} className="text-amber-800" />
                          <span>Stage 4: Odin's Judicial Determination & Ruling</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <Badge variant={trial.is_evidence_sufficient ? 'established' : 'warning'}>
                            {trial.is_evidence_sufficient ? 'Evidence Sufficient' : 'Sufficiency Gaps Identified'}
                          </Badge>
                        </div>
                      </div>

                      {/* Odin Metrics Banner */}
                      <div className="grid grid-cols-3 gap-3 text-center mb-4 font-mono text-xs" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px' }}>
                        <div className="p-3 rounded bg-green-50 border border-green-200 text-green-950">
                          <div className="text-2xl font-bold font-serif">{(odin.established_claims || []).length}</div>
                          <div className="text-xs uppercase font-sans font-semibold">Established Claims</div>
                          <div className="text-stone-500 text-xs mt-0.5">Verified beyond doubt</div>
                        </div>
                        <div className="p-3 rounded bg-amber-50 border border-amber-200 text-amber-950">
                          <div className="text-2xl font-bold font-serif">{(odin.contested_claims || []).length}</div>
                          <div className="text-xs uppercase font-sans font-semibold">Contested Claims</div>
                          <div className="text-stone-500 text-xs mt-0.5">Balanced conflicting proof</div>
                        </div>
                        <div className="p-3 rounded bg-red-50 border border-red-200 text-red-950">
                          <div className="text-2xl font-bold font-serif">{(odin.conceded_claims || []).length}</div>
                          <div className="text-xs uppercase font-sans font-semibold">Conceded Claims</div>
                          <div className="text-stone-500 text-xs mt-0.5">Withdrawn under challenge</div>
                        </div>
                      </div>

                      {/* Itemized Claim Rulings */}
                      {(odin.claim_rulings || []).length > 0 && (
                        <div className="mb-4">
                          <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
                            <span className="text-xs font-semibold uppercase text-stone-700">
                              Itemized Claim Rulings ({(odin.claim_rulings || []).length}):
                            </span>
                            <div className="flex items-center gap-1">
                              {(['all', 'established', 'contested', 'conceded'] as const).map((f) => (
                                <button
                                  key={f}
                                  type="button"
                                  onClick={() => setOdinRulingFilter(f)}
                                  className={`btn btn-sm ${odinRulingFilter === f ? 'btn-royal' : 'btn-stone'}`}
                                  style={{ padding: '2px 8px', fontSize: '11px' }}
                                >
                                  {f.charAt(0).toUpperCase() + f.slice(1)}
                                </button>
                              ))}
                            </div>
                          </div>

                          <div className="space-y-3">
                            {(odin.claim_rulings || [])
                              .filter((r) => odinRulingFilter === 'all' || r.ruling === odinRulingFilter)
                              .map((ruling) => (
                                <div key={ruling.claim_id} className="odin-ruling-card">
                                  <div className="flex items-center justify-between mb-1.5 flex-wrap gap-2">
                                    <div className="flex items-center gap-2">
                                      <span className="font-mono font-bold text-xs text-stone-900 bg-stone-100 px-2 py-0.5 rounded border border-stone-200">
                                        {ruling.claim_id}
                                      </span>
                                      <span className="text-xs font-bold text-stone-600">
                                        {ruling.proponent?.toUpperCase() === 'THOR' ? '⚡ THOR' : '🐍 LOKI'}
                                      </span>
                                    </div>
                                    <div className="flex items-center gap-2">
                                      <Badge variant={ruling.ruling}>
                                        {ruling.ruling.toUpperCase()}
                                      </Badge>
                                      <span className="font-mono text-xs text-stone-500 font-semibold">
                                        {Math.round(ruling.confidence * 100)}% Conf
                                      </span>
                                    </div>
                                  </div>

                                  <div className="font-serif text-sm font-semibold text-stone-900 mb-1 leading-snug">
                                    "{ruling.claim_statement}"
                                  </div>

                                  {ruling.adjudicated_range && (
                                    <div className="mb-2 p-2 rounded bg-amber-50 border border-amber-200 text-xs text-stone-800 font-mono">
                                      <span className="font-bold text-amber-900">Adjudicated Range: </span>
                                      {ruling.adjudicated_range.lower_bound ?? ruling.adjudicated_range.min_estimate}% – {ruling.adjudicated_range.upper_bound ?? ruling.adjudicated_range.max_estimate}% {ruling.adjudicated_range.unit}
                                    </div>
                                  )}

                                  <div className="text-xs text-stone-700 bg-stone-50 p-2.5 rounded border border-stone-200 leading-relaxed mb-2">
                                    <strong className="text-stone-900">Odin's Rationale: </strong>
                                    {ruling.reasoning}
                                  </div>

                                  {ruling.supporting_citations && ruling.supporting_citations.length > 0 && (
                                    <div className="flex flex-wrap gap-1 mt-1">
                                      <span className="text-xs font-semibold text-stone-500 mr-1">Citations:</span>
                                      {ruling.supporting_citations.map((c, ci) => (
                                        <span key={ci} className="citation-doc-tag" title={c.quote_or_datapoint}>
                                          {c.doc_id} {c.paragraph || ''}
                                        </span>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              ))}
                          </div>
                        </div>
                      )}

                      {gapsList.length > 0 && (
                        <div className="p-3.5 rounded border border-amber-200 bg-amber-50/70 text-xs text-amber-950 mb-3">
                          <strong className="uppercase tracking-wider text-amber-900 block mb-1.5 flex items-center gap-1">
                            <AlertTriangle size={14} />
                            <span>Evidentiary Gaps Triggering Feedback Loop ({gapsList.length}):</span>
                          </strong>
                          <ul className="list-disc list-inside space-y-1">
                            {gapsList.map((g, gi) => (
                              <li key={gi}>{g}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {odin.summary && (
                        <details className="verbatim-disclosure">
                          <summary>📜 View Full Verbatim Judicial Ruling</summary>
                          <div className="verbatim-content-box">
                            {odin.summary}
                          </div>
                        </details>
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
