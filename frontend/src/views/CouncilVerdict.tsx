import React, { useState } from 'react';
import type { DebateResult, ClaimRuling } from '../types';
import { Badge } from '../components/Badge';
import {
  Scale,
  CheckCircle,
  AlertCircle,
  FileText,
  User,
  ShieldAlert,
  Search,
} from 'lucide-react';

export interface CouncilVerdictProps {
  result: DebateResult | null;
  loading: boolean;
  onRefresh: () => void;
  onConveneDebate: () => void;
}

export const CouncilVerdict: React.FC<CouncilVerdictProps> = ({
  result,
  loading,
  onRefresh,
  onConveneDebate,
}) => {
  const [filterRuling, setFilterRuling] = useState<'all' | 'established' | 'contested' | 'conceded'>('all');
  const [searchQuery, setSearchQuery] = useState('');

  if (loading && !result) {
    return (
      <div className="archive-card text-center py-16 text-stone-500">
        <div className="inline-block animate-spin mb-2 text-xl">✦</div>
        <p>Retrieving Odin's Judicial Verdict...</p>
      </div>
    );
  }

  if (!result || !result.odin_adjudication) {
    return (
      <div className="archive-card text-center py-16 text-stone-600">
        <Scale size={44} className="mx-auto mb-3 text-stone-400" />
        <h3 className="text-xl font-serif mb-2">No Judicial Adjudication on File</h3>
        <p className="text-sm text-stone-500 max-w-md mx-auto mb-4">
          This case has not yet completed adversarial courtroom deliberation. Convene the council to generate Odin's final ruling.
        </p>
        <button type="button" onClick={onConveneDebate} className="btn btn-royal">
          <Scale size={15} />
          <span>Convene Courtroom Council</span>
        </button>
      </div>
    );
  }

  const odin = result.odin_adjudication;
  const isSufficient = odin.is_evidence_sufficient;

  // Filter claim rulings
  const filteredRulings = odin.claim_rulings.filter((r) => {
    if (filterRuling !== 'all' && r.ruling !== filterRuling) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return (
        r.claim_id.toLowerCase().includes(q) ||
        r.claim_statement.toLowerCase().includes(q) ||
        r.reasoning.toLowerCase().includes(q) ||
        r.proponent.toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <div>
      {/* High Judicial Banner */}
      <div className="archive-card">
        <div className="card-title-row">
          <div className="card-title">
            <Scale size={24} />
            <span>Odin's High Judicial Verdict</span>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={odin.adjudication_status === 'completed' ? 'established' : 'warning'}>
              Status: {odin.adjudication_status.toUpperCase()}
            </Badge>
            <Badge variant={isSufficient ? 'verified' : 'danger'}>
              {isSufficient ? 'Evidence Sufficient' : 'Evidence Gaps Identified'}
            </Badge>
            <button type="button" onClick={onRefresh} className="btn btn-stone btn-sm ml-2">
              Refresh
            </button>
          </div>
        </div>

        {/* Adjudication Summary Narrative */}
        <div className="p-4 rounded mb-6 border" style={{ backgroundColor: 'var(--color-warm-parchment)', borderColor: 'var(--color-weathered-stone)' }}>
          <div className="text-xs font-semibold uppercase tracking-wider text-stone-500 mb-1 flex items-center gap-1">
            <Scale size={13} className="text-amber-700" />
            <span>Judicial Summary & Operational Determination</span>
          </div>
          <div className="font-serif text-base text-stone-900 leading-relaxed">
            {odin.summary}
          </div>
          {result.loop_stop_reason && (
            <div className="mt-3 text-xs font-mono text-stone-600 flex items-center gap-2">
              <span className="font-bold text-stone-800">Loop Stop Reason:</span>
              <span className="px-2 py-0.5 rounded bg-stone-200 text-stone-800">{result.loop_stop_reason}</span>
              <span className="text-stone-400">({result.total_trials} {result.total_trials === 1 ? 'trial' : 'trials'} total)</span>
            </div>
          )}
        </div>

        {/* Adjudication Metrics Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '16px' }}>
          <div className="p-3 rounded border border-stone-200 bg-white">
            <div className="text-xs uppercase font-semibold text-stone-500 mb-1">Established Claims</div>
            <div className="font-serif text-2xl font-bold text-green-900">{odin.established_claims.length}</div>
            <div className="text-xs text-stone-400 mt-1">Verified by admissible evidence</div>
          </div>

          <div className="p-3 rounded border border-stone-200 bg-white">
            <div className="text-xs uppercase font-semibold text-stone-500 mb-1">Contested Claims</div>
            <div className="font-serif text-2xl font-bold text-amber-800">{odin.contested_claims.length}</div>
            <div className="text-xs text-stone-400 mt-1">Unresolved evidentiary conflict</div>
          </div>

          <div className="p-3 rounded border border-stone-200 bg-white">
            <div className="text-xs uppercase font-semibold text-stone-500 mb-1">Conceded Claims</div>
            <div className="font-serif text-2xl font-bold text-red-900">{odin.conceded_claims.length}</div>
            <div className="text-xs text-stone-400 mt-1">Formally yielded in cross-exam</div>
          </div>

          <div className="p-3 rounded border border-stone-200 bg-white">
            <div className="text-xs uppercase font-semibold text-stone-500 mb-1">Evidence Examined</div>
            <div className="font-serif text-2xl font-bold text-stone-900">{odin.evidence_examined.length}</div>
            <div className="text-xs text-stone-400 mt-1">Runemark corpus documents</div>
          </div>
        </div>

        {/* Unresolved Disputes & Evidence Limitations (if any) */}
        {(odin.unresolved_disputes.length > 0 || odin.evidence_limitations.length > 0) && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
            {odin.unresolved_disputes.length > 0 && (
              <div className="p-4 rounded border border-amber-200 bg-amber-50">
                <div className="text-xs font-semibold uppercase text-amber-900 flex items-center gap-1 mb-2">
                  <AlertCircle size={14} />
                  <span>Unresolved Evidentiary Disputes ({odin.unresolved_disputes.length})</span>
                </div>
                <ul className="text-xs text-amber-950 space-y-1 list-disc list-inside">
                  {odin.unresolved_disputes.map((d, i) => (
                    <li key={i}>{d}</li>
                  ))}
                </ul>
              </div>
            )}

            {odin.evidence_limitations.length > 0 && (
              <div className="p-4 rounded border border-stone-300 bg-stone-50">
                <div className="text-xs font-semibold uppercase text-stone-700 flex items-center gap-1 mb-2">
                  <ShieldAlert size={14} />
                  <span>Evidentiary Limitations & Gaps ({odin.evidence_limitations.length})</span>
                </div>
                <ul className="text-xs text-stone-800 space-y-1 list-disc list-inside">
                  {odin.evidence_limitations.map((g, i) => (
                    <li key={i}>{g}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Itemized Claim Rulings */}
      <div className="archive-card">
        <div className="card-title-row">
          <div className="card-title">
            <FileText size={20} />
            <span>Adjudicated Claim Rulings</span>
          </div>
          <div className="flex items-center gap-3">
            {/* Filter buttons */}
            <div className="flex items-center gap-1">
              {(['all', 'established', 'contested', 'conceded'] as const).map((cat) => (
                <button
                  key={cat}
                  type="button"
                  onClick={() => setFilterRuling(cat)}
                  className={`btn btn-sm ${filterRuling === cat ? 'btn-royal' : 'btn-stone'}`}
                >
                  {cat.charAt(0).toUpperCase() + cat.slice(1)}
                </button>
              ))}
            </div>

            {/* Search box */}
            <div style={{ position: 'relative', width: '200px' }}>
              <input
                type="text"
                placeholder="Search claims..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ paddingLeft: '28px', fontSize: '12px', height: '30px' }}
              />
              <Search
                size={13}
                style={{ position: 'absolute', left: '9px', top: '9px', color: 'var(--color-slate-ink)' }}
              />
            </div>
          </div>
        </div>

        {filteredRulings.length === 0 ? (
          <div className="py-8 text-center text-stone-500 text-sm">
            No claim rulings match the selected filter.
          </div>
        ) : (
          <div className="space-y-4">
            {filteredRulings.map((ruling: ClaimRuling) => (
              <div
                key={ruling.claim_id}
                className="p-4 rounded border bg-white mb-3"
                style={{
                  borderColor:
                    ruling.ruling === 'established'
                      ? '#c7d6c9'
                      : ruling.ruling === 'contested'
                      ? '#e5d7be'
                      : '#e8c7c7',
                }}
              >
                <div className="flex items-start justify-between gap-4 mb-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-xs font-bold text-stone-900 bg-stone-100 px-2 py-0.5 rounded border border-stone-200">
                      {ruling.claim_id}
                    </span>
                    <span className="text-xs uppercase tracking-wider font-semibold text-stone-600 flex items-center gap-1">
                      <User size={12} />
                      <span>{ruling.proponent.toUpperCase()}</span>
                    </span>
                    <span className="text-xs text-stone-400">·</span>
                    <span className="text-xs font-mono text-stone-500">{ruling.claim_type}</span>
                  </div>

                  <div className="flex items-center gap-2">
                    <Badge variant={ruling.ruling}>
                      {ruling.ruling === 'established' && <CheckCircle size={10} className="inline mr-1" />}
                      {ruling.ruling === 'contested' && <AlertCircle size={10} className="inline mr-1" />}
                      {ruling.ruling === 'conceded' && <ShieldAlert size={10} className="inline mr-1" />}
                      {ruling.ruling.toUpperCase()}
                    </Badge>
                    <span className="font-mono text-xs text-stone-500 font-semibold" title="Calibrated judicial confidence">
                      {Math.round(ruling.confidence * 100)}% Conf
                    </span>
                  </div>
                </div>

                {/* Claim Statement */}
                <div className="font-serif text-sm font-semibold text-stone-900 mb-2">
                  "{ruling.claim_statement}"
                </div>

                {/* Adjudicated Range if present */}
                {ruling.adjudicated_range && (
                  <div className="mb-2 p-2 rounded bg-amber-50 border border-amber-200 text-xs text-stone-800 font-mono">
                    <span className="font-bold text-amber-900">Adjudicated Range:</span> {ruling.adjudicated_range.lower_bound} to {ruling.adjudicated_range.upper_bound} {ruling.adjudicated_range.unit} ({ruling.adjudicated_range.metric} for {ruling.adjudicated_range.country})
                  </div>
                )}

                {/* Judicial Reasoning */}
                <div className="text-xs text-stone-700 mb-3 bg-stone-50 p-2.5 rounded border border-stone-200">
                  <span className="font-semibold text-stone-900">Odin's Rationale: </span>
                  {ruling.reasoning}
                </div>

                {/* Citations & Evidence Breakdown */}
                <div className="flex flex-col sm:flex-row items-start justify-between gap-3 text-xs pt-2 border-t border-stone-100">
                  <div className="flex-1">
                    <span className="font-semibold text-stone-600 block mb-1">Supporting Citations:</span>
                    {ruling.supporting_citations.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {ruling.supporting_citations.map((c, idx) => (
                          <span
                            key={idx}
                            className="font-mono px-1.5 py-0.5 rounded bg-green-50 border border-green-200 text-green-900 text-xs"
                            title={c.quote_or_datapoint}
                          >
                            {c.doc_id} {c.paragraph || ''}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-stone-400 italic">None admissible</span>
                    )}
                  </div>

                  {ruling.contradicting_citations.length > 0 && (
                    <div className="flex-1">
                      <span className="font-semibold text-amber-800 block mb-1">Counter Citations:</span>
                      <div className="flex flex-wrap gap-1">
                        {ruling.contradicting_citations.map((c, idx) => (
                          <span
                            key={idx}
                            className="font-mono px-1.5 py-0.5 rounded bg-amber-50 border border-amber-200 text-amber-900 text-xs"
                            title={c.quote_or_datapoint}
                          >
                            {c.doc_id} {c.paragraph || ''}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {ruling.is_conceded && (
                    <div className="text-right">
                      <span className="px-2 py-0.5 rounded bg-red-50 border border-red-200 text-red-900 font-semibold text-xs">
                        Conceded by {ruling.conceded_by?.toUpperCase() || 'advocate'}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
