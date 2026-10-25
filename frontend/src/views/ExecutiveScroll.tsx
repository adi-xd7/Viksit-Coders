import React from 'react';
import type { ExecutiveBriefing } from '../types';
import { Badge } from '../components/Badge';
import {
  Scroll,
  Printer,
  ShieldCheck,
  TrendingUp,
  AlertTriangle,
  Lightbulb,
  BookOpen,
  Clock,
  Globe,
} from 'lucide-react';

export interface ExecutiveScrollProps {
  briefing: ExecutiveBriefing | null;
  loading: boolean;
  onRefresh: () => void;
  onConveneDebate: () => void;
}

export const ExecutiveScroll: React.FC<ExecutiveScrollProps> = ({
  briefing,
  loading,
  onRefresh,
  onConveneDebate,
}) => {
  if (loading && !briefing) {
    return (
      <div className="archive-card text-center py-16 text-stone-500">
        <div className="inline-block animate-spin mb-2 text-xl">✦</div>
        <p>Unfurling Executive Briefing Scroll...</p>
      </div>
    );
  }

  if (!briefing) {
    return (
      <div className="archive-card text-center py-16 text-stone-600">
        <Scroll size={44} className="mx-auto mb-3 text-stone-400" />
        <h3 className="text-xl font-serif mb-2">Executive Scroll Not Yet Generated</h3>
        <p className="text-sm text-stone-500 max-w-md mx-auto mb-4">
          The executive briefing is compiled only upon successful judicial adjudication by Odin. Convene the council to generate the scroll.
        </p>
        <button type="button" onClick={onConveneDebate} className="btn btn-royal">
          <Scroll size={15} />
          <span>Convene Courtroom Council</span>
        </button>
      </div>
    );
  }

  const handlePrint = () => {
    window.print();
  };

  return (
    <div>
      {/* Scroll Controls (hidden in print) */}
      <div className="flex items-center justify-between mb-4 no-print">
        <div className="text-xs text-stone-500 font-mono">
          Case Dossier: <span className="font-bold text-stone-800">{briefing.case_id}</span> · Generated: {briefing.generated_at}
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={onRefresh} className="btn btn-stone btn-sm">
            Refresh Scroll
          </button>
          <button type="button" onClick={handlePrint} className="btn btn-royal btn-sm">
            <Printer size={13} />
            <span>Print Royal Scroll</span>
          </button>
        </div>
      </div>

      {/* The Parchment Scroll Document */}
      <article className="scroll-document" aria-label="Executive Briefing Document">
        {/* Crest & Document Header */}
        <header className="scroll-crest-banner">
          <div className="scroll-classification">
            Court of the Nine Realms · Strategic Intelligence Briefing
          </div>
          <h1 className="scroll-title">{briefing.title}</h1>
          <div className="scroll-meta">
            <span><strong>Case ID:</strong> {briefing.case_id}</span>
            <span>·</span>
            <span><strong>As-Of Clock:</strong> {briefing.as_of_date}</span>
            <span>·</span>
            <span><strong>Confidence:</strong> {briefing.confidence_assessment.toUpperCase()} ({Math.round(briefing.overall_confidence * 100)}%)</span>
            <span>·</span>
            <span>
              <Badge variant={briefing.status === 'completed' ? 'established' : 'warning'}>
                {briefing.status.toUpperCase()}
              </Badge>
            </span>
          </div>
        </header>

        {/* Section 1: Executive Summary & Foundational Verification */}
        <section className="scroll-section">
          <h2 className="scroll-section-title">
            <ShieldCheck size={20} />
            <span>1. Executive Summary & Foundational Verification</span>
          </h2>
          <div className="font-serif text-base text-stone-900 leading-relaxed mb-4 p-4 rounded bg-stone-50 border border-stone-200">
            {briefing.executive_summary}
          </div>

          <div className="p-3 rounded border border-green-200 bg-green-50/50 mb-3 text-xs text-stone-800">
            <span className="font-bold text-green-900 uppercase">Heimdall Foundational Gate: </span>
            {briefing.verification_summary}
          </div>

          {briefing.confirmed_disruption_facts.length > 0 && (
            <div className="mt-3">
              <span className="text-xs uppercase font-semibold text-stone-600 block mb-2">
                Confirmed Disruption Facts (Admissible Provenance):
              </span>
              <ul className="text-xs text-stone-800 list-disc list-inside space-y-1 pl-1">
                {briefing.confirmed_disruption_facts.map((fact, idx) => (
                  <li key={idx}>{fact}</li>
                ))}
              </ul>
            </div>
          )}
        </section>

        {/* Section 2: Chronological Timeline */}
        {briefing.timeline.length > 0 && (
          <section className="scroll-section">
            <h2 className="scroll-section-title">
              <Clock size={20} />
              <span>2. Chronological Disruption Milestones</span>
            </h2>
            <div className="overflow-x-auto">
              <table>
                <thead>
                  <tr>
                    <th style={{ width: '130px' }}>Date</th>
                    <th>Verified Disruption Milestone</th>
                    <th style={{ width: '120px' }}>Corroborating Doc</th>
                    <th style={{ width: '150px' }}>Publisher / Source</th>
                    <th style={{ width: '80px' }}>Credibility</th>
                  </tr>
                </thead>
                <tbody>
                  {briefing.timeline.map((event, idx) => (
                    <tr key={idx}>
                      <td className="font-mono text-xs font-semibold text-stone-900">{event.event_date}</td>
                      <td>{event.description}</td>
                      <td className="font-mono text-xs text-amber-800">{event.supporting_doc_id || '—'}</td>
                      <td className="text-xs text-stone-600">{event.source_name || '—'}</td>
                      <td>
                        {event.reliability_tier ? (
                          <span className="font-mono text-xs font-semibold text-stone-700">
                            Tier {event.reliability_tier}
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Section 3: Disruption Scope & Stakeholders */}
        <section className="scroll-section">
          <h2 className="scroll-section-title">
            <Globe size={20} />
            <span>3. Disruption Scope & Key Stakeholders</span>
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
            <div className="p-3 rounded border border-stone-200 bg-white">
              <span className="font-semibold text-stone-700 block mb-1 uppercase tracking-wider">Affected Regions:</span>
              <div className="flex flex-wrap gap-1">
                {briefing.affected_regions.length > 0 ? (
                  briefing.affected_regions.map((r, i) => (
                    <span key={i} className="px-2 py-0.5 rounded bg-stone-100 border border-stone-200 text-stone-800">
                      {r}
                    </span>
                  ))
                ) : (
                  <span className="text-stone-400">None documented</span>
                )}
              </div>
            </div>

            <div className="p-3 rounded border border-stone-200 bg-white">
              <span className="font-semibold text-stone-700 block mb-1 uppercase tracking-wider">Affected Sectors & Commodities:</span>
              <div className="flex flex-wrap gap-1">
                {briefing.affected_sectors.length > 0 ? (
                  briefing.affected_sectors.map((s, i) => (
                    <span key={i} className="px-2 py-0.5 rounded bg-amber-50 border border-amber-200 text-amber-900 font-medium">
                      {s}
                    </span>
                  ))
                ) : (
                  <span className="text-stone-400">None documented</span>
                )}
              </div>
            </div>

            <div className="p-3 rounded border border-stone-200 bg-white">
              <span className="font-semibold text-stone-700 block mb-1 uppercase tracking-wider">Corridors & Maritime Routes:</span>
              <div className="flex flex-wrap gap-1">
                {briefing.affected_trade_routes.length > 0 ? (
                  briefing.affected_trade_routes.map((tr, i) => (
                    <span key={i} className="px-2 py-0.5 rounded bg-stone-100 border border-stone-200 text-stone-800">
                      {tr}
                    </span>
                  ))
                ) : (
                  <span className="text-stone-400">None documented</span>
                )}
              </div>
            </div>

            <div className="p-3 rounded border border-stone-200 bg-white">
              <span className="font-semibold text-stone-700 block mb-1 uppercase tracking-wider">Major Commercial Stakeholders:</span>
              <div className="flex flex-wrap gap-1">
                {briefing.key_stakeholders.length > 0 ? (
                  briefing.key_stakeholders.map((ks, i) => (
                    <span key={i} className="px-2 py-0.5 rounded bg-stone-100 border border-stone-200 text-stone-800">
                      {ks}
                    </span>
                  ))
                ) : (
                  <span className="text-stone-400">None documented</span>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* Section 4: Quantitative Exposure Comparison */}
        <section className="scroll-section">
          <h2 className="scroll-section-title">
            <TrendingUp size={20} />
            <span>4. Quantitative Exposure Comparison</span>
          </h2>
          <div className="text-xs text-stone-700 mb-3 bg-stone-50 p-3 rounded border border-stone-200">
            {briefing.quantitative_summary}
          </div>

          {briefing.exposure_table.length > 0 ? (
            <div className="overflow-x-auto mb-4">
              <table>
                <thead>
                  <tr>
                    <th>Country</th>
                    <th>Sector</th>
                    <th>Impact Metric</th>
                    <th>Unit</th>
                    <th>Period</th>
                    <th>Thor High-Exposure</th>
                    <th>Loki Low-Exposure</th>
                    <th>Odin Adjudicated Range</th>
                    <th>Ruling</th>
                  </tr>
                </thead>
                <tbody>
                  {briefing.exposure_table.map((row, idx) => (
                    <tr key={idx}>
                      <td className="font-semibold text-stone-900">{row.country}</td>
                      <td>{row.sector}</td>
                      <td className="font-mono text-xs">{row.metric}</td>
                      <td className="font-mono text-xs">{row.unit}</td>
                      <td className="font-mono text-xs">{row.period}</td>
                      <td className="font-mono text-xs text-amber-900">{row.thor_range || '—'}</td>
                      <td className="font-mono text-xs text-stone-700">{row.loki_range || '—'}</td>
                      <td className="font-mono text-xs font-bold text-green-950 bg-green-50/50">
                        {row.odin_adjudicated_range || 'Contested'}
                      </td>
                      <td>
                        <Badge variant={row.odin_status === 'established' ? 'established' : row.odin_status === 'contested' ? 'contested' : 'conceded'}>
                          {row.odin_status.toUpperCase()}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-stone-500 italic">No quantitative metrics established in trial.</p>
          )}
        </section>

        {/* Section 5: Evidentiary Confidence & Limitations */}
        <section className="scroll-section">
          <h2 className="scroll-section-title">
            <AlertTriangle size={20} />
            <span>5. Evidentiary Confidence & Limitations</span>
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs mb-3" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
            <div className="p-3 rounded border border-stone-200 bg-white">
              <span className="font-semibold text-stone-800 block mb-2 uppercase tracking-wider">Identified Data Limitations:</span>
              <ul className="list-disc list-inside space-y-1 text-stone-700">
                {briefing.evidence_limitations.length > 0 ? (
                  briefing.evidence_limitations.map((lim, i) => <li key={i}>{lim}</li>)
                ) : (
                  <li className="text-stone-400 italic">No material evidentiary limitations identified.</li>
                )}
              </ul>
            </div>

            <div className="p-3 rounded border border-amber-200 bg-amber-50">
              <span className="font-semibold text-amber-900 block mb-2 uppercase tracking-wider">Key Commercial Uncertainties:</span>
              <ul className="list-disc list-inside space-y-1 text-amber-950">
                {briefing.key_uncertainties.length > 0 ? (
                  briefing.key_uncertainties.map((unc, i) => <li key={i}>{unc}</li>)
                ) : (
                  <li className="text-stone-400 italic">None noted.</li>
                )}
              </ul>
            </div>
          </div>
        </section>

        {/* Section 6: Forward Outlook & Qualified Recommendations */}
        <section className="scroll-section">
          <h2 className="scroll-section-title">
            <Lightbulb size={20} />
            <span>6. Forward Outlook & Qualified Recommendations</span>
          </h2>

          <div className="p-4 rounded border border-stone-300 bg-white mb-4">
            <div className="text-xs font-semibold uppercase text-stone-600 mb-1">
              Operational Next-Quarter Outlook (Projected Model — Not Historical Fact):
            </div>
            <div className="font-serif text-sm text-stone-900 leading-relaxed">
              {briefing.next_quarter_outlook}
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs uppercase font-semibold text-stone-700">
                Strategic Recommendations:
              </span>
              {briefing.recommendations_qualified && (
                <span className="text-xs font-mono text-amber-800 bg-amber-100/70 px-2 py-0.5 rounded">
                  Qualified by Available Evidence
                </span>
              )}
            </div>
            <ol className="list-decimal list-inside space-y-1.5 text-xs text-stone-800 pl-1">
              {briefing.recommended_actions.map((act, i) => (
                <li key={i} className="pl-1 leading-relaxed">
                  {act}
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Section 7: Bibliography & Evidence Provenance */}
        <section className="scroll-section mb-0">
          <h2 className="scroll-section-title">
            <BookOpen size={20} />
            <span>7. Evidence Provenance & Bibliography</span>
          </h2>
          <div className="overflow-x-auto">
            <table>
              <thead>
                <tr>
                  <th style={{ width: '120px' }}>Doc ID</th>
                  <th style={{ width: '80px' }}>Paragraph</th>
                  <th>Source Outlet / Publisher</th>
                  <th style={{ width: '70px' }}>Tier</th>
                  <th style={{ width: '110px' }}>Date</th>
                  <th>Corroborated Excerpt or Datapoint</th>
                </tr>
              </thead>
              <tbody>
                {briefing.cited_sources.map((src, idx) => (
                  <tr key={idx}>
                    <td className="font-mono text-xs font-bold text-amber-900">{src.doc_id}</td>
                    <td className="font-mono text-xs text-stone-600">{src.paragraph || '—'}</td>
                    <td className="text-xs text-stone-800 font-medium">{src.source_name || '—'}</td>
                    <td className="font-mono text-xs">
                      {src.reliability_tier ? `Tier ${src.reliability_tier}` : '—'}
                    </td>
                    <td className="font-mono text-xs text-stone-500">{src.publication_date || '—'}</td>
                    <td className="text-xs text-stone-700 italic">"{src.quote_or_datapoint}"</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Footer Audit Stamp */}
        <footer className="mt-12 pt-6 border-t-2 border-stone-200 text-center text-xs text-stone-500 font-mono">
          RAGNAROK Multi-Agent Courtroom Engine · Trial Audit: {briefing.total_trials} {briefing.total_trials === 1 ? 'trial' : 'trials'} ({briefing.retries_attempted} retries) · Stop Reason: {briefing.loop_stop_reason || 'evidence_sufficient'}
        </footer>
      </article>
    </div>
  );
};
