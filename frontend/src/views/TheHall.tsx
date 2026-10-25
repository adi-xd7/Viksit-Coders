import React from 'react';
import type { CaseSummaryResponse } from '../types';
import { Badge } from '../components/Badge';
import {
  Castle,
  FileText,
  Scale,
  CheckCircle,
  Plus,
  ArrowRight,
  Database,
  Scroll,
} from 'lucide-react';

export interface TheHallProps {
  cases: CaseSummaryResponse[];
  loading: boolean;
  onSelectCase: (caseId: string) => void;
  onOpenNewCaseModal: () => void;
  onRefresh: () => void;
}

export const TheHall: React.FC<TheHallProps> = ({
  cases,
  loading,
  onSelectCase,
  onOpenNewCaseModal,
  onRefresh,
}) => {
  const completedCount = cases.filter((c) => c.has_debate_result).length;
  const briefingsCount = cases.filter((c) => c.has_briefing).length;

  return (
    <div>
      {/* Strategic Header */}
      <div className="mb-6 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2">
            <Castle className="text-amber-600 inline" size={28} />
            <span>The Hall of Deliberation</span>
          </h1>
          <p className="text-stone-600 text-sm mt-1">
            Archival repository of supply chain disruptions submitted to the adversarial court of the Nine Realms.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button type="button" onClick={onRefresh} className="btn btn-stone btn-sm" disabled={loading}>
            Refresh Archive
          </button>
          <button type="button" onClick={onOpenNewCaseModal} className="btn btn-royal">
            <Plus size={15} />
            <span>Open New Dossier</span>
          </button>
        </div>
      </div>

      {/* Verified Stats Bar */}
      <div className="stats-grid">
        <div className="stat-card">
          <div>
            <div className="stat-label">Registered Cases</div>
            <div className="stat-value">{cases.length}</div>
          </div>
          <div className="stat-icon" aria-hidden="true">
            <FileText size={18} />
          </div>
        </div>

        <div className="stat-card">
          <div>
            <div className="stat-label">Adjudicated Verdicts</div>
            <div className="stat-value">{completedCount}</div>
          </div>
          <div className="stat-icon" aria-hidden="true">
            <Scale size={18} />
          </div>
        </div>

        <div className="stat-card">
          <div>
            <div className="stat-label">Executive Scrolls</div>
            <div className="stat-value">{briefingsCount}</div>
          </div>
          <div className="stat-icon" aria-hidden="true">
            <Scroll size={18} />
          </div>
        </div>

        <div className="stat-card">
          <div>
            <div className="stat-label">Archive Storage</div>
            <div className="stat-value" style={{ fontSize: '1.25rem', marginTop: '6px' }}>
              In-Memory
            </div>
          </div>
          <div className="stat-icon" aria-hidden="true">
            <Database size={18} />
          </div>
        </div>
      </div>

      {/* Case Dossiers Table */}
      <div className="archive-card">
        <div className="card-title-row">
          <div className="card-title">
            <FileText size={20} />
            <span>Active Case Registry</span>
          </div>
          <div className="text-xs text-stone-500 font-mono">
            {cases.length} {cases.length === 1 ? 'dossier' : 'dossiers'} cataloged
          </div>
        </div>

        {loading && cases.length === 0 ? (
          <div className="py-12 text-center text-stone-500">
            <div className="inline-block animate-spin mb-2">✦</div>
            <p>Accessing Royal Intelligence Registry...</p>
          </div>
        ) : cases.length === 0 ? (
          <div className="py-12 text-center text-stone-600">
            <Castle size={36} className="mx-auto mb-3 text-stone-400" />
            <p className="font-serif text-lg font-semibold text-stone-800">No Case Dossiers Cataloged</p>
            <p className="text-sm text-stone-500 max-w-md mx-auto mt-1 mb-4">
              The archive currently holds no disruption records in memory. File a new dossier to commence adversarial deliberation.
            </p>
            <button type="button" onClick={onOpenNewCaseModal} className="btn btn-royal">
              <Plus size={14} />
              <span>File Initial Dossier</span>
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table>
              <thead>
                <tr>
                  <th>Case ID</th>
                  <th>Cutoff Date</th>
                  <th>Disruption Question</th>
                  <th>Event ID</th>
                  <th>Debate Status</th>
                  <th>Evidence Sufficiency</th>
                  <th>Briefing</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {cases.map((c) => (
                  <tr key={c.case_id} style={{ cursor: 'pointer' }} onClick={() => onSelectCase(c.case_id)}>
                    <td className="font-mono font-semibold" style={{ color: 'var(--color-antique-gold-hover)' }}>
                      {c.case_id}
                    </td>
                    <td className="font-mono text-xs">{c.as_of_date}</td>
                    <td style={{ maxWidth: '380px' }}>
                      <div className="line-clamp-2" title={c.question}>
                        {c.question}
                      </div>
                    </td>
                    <td className="font-mono text-xs">{c.event_id || '—'}</td>
                    <td>
                      {c.has_debate_result ? (
                        <Badge variant="verified">
                          <CheckCircle size={10} className="inline mr-1" />
                          {c.debate_status || 'Success'}
                        </Badge>
                      ) : (
                        <Badge variant="neutral">Pending</Badge>
                      )}
                    </td>
                    <td>
                      {c.is_evidence_sufficient === true ? (
                        <Badge variant="established">Sufficient</Badge>
                      ) : c.is_evidence_sufficient === false ? (
                        <Badge variant="contested">Gaps Identified</Badge>
                      ) : (
                        <span className="text-stone-400 text-xs">—</span>
                      )}
                    </td>
                    <td>
                      {c.has_briefing ? (
                        <Badge variant="established">Available</Badge>
                      ) : (
                        <span className="text-stone-400 text-xs">Uncompiled</span>
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectCase(c.case_id);
                        }}
                        className="btn btn-stone btn-sm"
                        title="Open this case dossier"
                      >
                        <span>Inspect</span>
                        <ArrowRight size={12} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
