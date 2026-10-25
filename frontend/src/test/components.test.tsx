import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { Badge } from '../components/Badge';
import { ErrorBanner } from '../components/ErrorBanner';
import { HealthIndicator } from '../components/HealthIndicator';
import { CaseFormModal } from '../components/CaseFormModal';
import { TheHall } from '../views/TheHall';
import { CouncilVerdict } from '../views/CouncilVerdict';
import { ExecutiveScroll } from '../views/ExecutiveScroll';
import type {
  HealthResponse,
  CaseSummaryResponse,
  DebateResult,
  ExecutiveBriefing,
} from '../types';

describe('RAGNAROK Frontend UI Components', () => {
  it('renders Badge with correct variant class', () => {
    const { container } = render(<Badge variant="established">Established</Badge>);
    expect(container.querySelector('.badge-established')).toBeTruthy();
    expect(screen.getByText('Established')).toBeTruthy();
  });

  it('renders ErrorBanner with title, message, and calls onDismiss', () => {
    const onDismiss = vi.fn();
    render(
      <ErrorBanner
        title="Conflict Detected"
        message="Debate is currently active."
        errorCode="DEBATE_ACTIVE"
        onDismiss={onDismiss}
      />
    );

    expect(screen.getByText(/Conflict Detected/)).toBeTruthy();
    expect(screen.getByText('Debate is currently active.')).toBeTruthy();
    expect(screen.getByText('(DEBATE_ACTIVE)')).toBeTruthy();

    const dismissBtn = screen.getByLabelText('Dismiss error notification');
    fireEvent.click(dismissBtn);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('renders HealthIndicator when healthy with corpus active', () => {
    const health: HealthResponse = {
      status: 'healthy',
      service: 'ragnarok-ps3-courtroom',
      version: '1.0.0',
      timestamp: '2026-10-25T18:00:00Z',
      corpus_available: true,
      storage_type: 'in_memory',
    };

    render(<HealthIndicator health={health} loading={false} />);
    expect(screen.getByText('v1.0.0')).toBeTruthy();
    expect(screen.getByText('Corpus E5 Active')).toBeTruthy();
  });

  it('validates form fields in CaseFormModal', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();

    render(<CaseFormModal isOpen={true} onClose={onClose} onSubmit={onSubmit} />);

    // Check modal title
    expect(screen.getByText('Open New Disruption Dossier')).toBeTruthy();

    // Fill form
    const idInput = screen.getByLabelText(/Case Identifier/);
    const qInput = screen.getByLabelText(/Target Disruption Inquiry/);

    await act(async () => {
      fireEvent.change(idInput, { target: { value: 'CASE-TEST-1' } });
      fireEvent.change(qInput, { target: { value: 'What is the impact on grain logistics?' } });
    });

    // Submit
    const submitBtn = screen.getByText('File Case Dossier');
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        case_id: 'CASE-TEST-1',
        question: 'What is the impact on grain logistics?',
        as_of_date: '2026-10-25',
      })
    );
  });

  it('renders TheHall with case summary records', () => {
    const cases: CaseSummaryResponse[] = [
      {
        case_id: 'CASE-E5',
        question: 'What is the impact of the Tolan Strait disruption on Midgard wheat supplies?',
        as_of_date: '2026-10-25',
        event_id: 'E5',
        has_debate_result: true,
        has_briefing: true,
        debate_status: 'success',
        is_evidence_sufficient: true,
      },
    ];

    const onSelect = vi.fn();
    render(
      <TheHall
        cases={cases}
        loading={false}
        onSelectCase={onSelect}
        onOpenNewCaseModal={vi.fn()}
        onRefresh={vi.fn()}
      />
    );

    expect(screen.getByText('The Hall of Deliberation')).toBeTruthy();
    expect(screen.getByText('CASE-E5')).toBeTruthy();
    expect(screen.getByText('Sufficient')).toBeTruthy();

    const inspectBtn = screen.getByText('Inspect');
    fireEvent.click(inspectBtn);
    expect(onSelect).toHaveBeenCalledWith('CASE-E5');
  });

  it('renders CouncilVerdict with Odin rulings', () => {
    const result: DebateResult = {
      case_id: 'CASE-E5',
      as_of_date: '2026-10-25',
      run_number: 1,
      status: 'success',
      stages_executed: ['heimdall', 'thor', 'loki', 'odin'],
      total_trials: 1,
      retries_attempted: 0,
      max_retries: 2,
      loop_stop_reason: 'evidence_sufficient',
      case_file: {
        case_id: 'CASE-E5',
        question: 'Q',
        as_of_date: '2026-10-25',
        is_verified: true,
        round_number: 1,
        run_number: 1,
        claims: [],
        attacks: [],
        concessions: [],
        judicial_rulings: [],
      },
      odin_adjudication: {
        agent: 'odin',
        case_id: 'CASE-E5',
        as_of_date: '2026-10-25',
        run_number: 1,
        adjudication_status: 'completed',
        summary: 'All material disruption facts substantiated by Tier 1 official notices.',
        is_evidence_sufficient: true,
        established_claims: ['THOR-C01'],
        contested_claims: [],
        conceded_claims: [],
        unresolved_disputes: [],
        evidence_limitations: [],
        evidence_examined: ['ORV-0016'],
        claim_rulings: [
          {
            claim_id: 'THOR-C01',
            claim_statement: 'Tolan Strait traffic halted indefinitely.',
            proponent: 'thor',
            claim_type: 'sourced_fact',
            ruling: 'established',
            confidence: 0.95,
            reasoning: 'Directly confirmed by port authority circular.',
            supporting_citations: [
              {
                doc_id: 'ORV-0016',
                paragraph: 'P2',
                quote_or_datapoint: 'Strait closed to commercial navigation.',
              },
            ],
            contradicting_citations: [],
            concessions: [],
            is_conceded: false,
            evidence_gaps: [],
          },
        ],
      },
      trial_history: [],
    };

    render(
      <CouncilVerdict
        result={result}
        loading={false}
        onRefresh={vi.fn()}
        onConveneDebate={vi.fn()}
      />
    );

    expect(screen.getByText("Odin's High Judicial Verdict")).toBeTruthy();
    expect(screen.getByText('Evidence Sufficient')).toBeTruthy();
    expect(screen.getByText('THOR-C01')).toBeTruthy();
    expect(screen.getByText('"Tolan Strait traffic halted indefinitely."')).toBeTruthy();
    expect(screen.getByText('95% Conf')).toBeTruthy();
  });

  it('renders ExecutiveScroll with sections and provenance', () => {
    const briefing: ExecutiveBriefing = {
      case_id: 'CASE-E5',
      as_of_date: '2026-10-25',
      question: 'Disruption impact question',
      title: 'Tolan Strait Disruption Briefing',
      status: 'completed',
      generated_at: '2026-10-25T18:00:00Z',
      executive_summary: 'Comprehensive analysis indicates manageable regional disruption.',
      event_verified: true,
      verification_summary: 'Heimdall verified disruption via ORV-0016.',
      confirmed_disruption_facts: ['Canal traffic suspended on 2026-10-24.'],
      timeline: [
        {
          event_date: '2026-10-24',
          description: 'Official transit closure announced.',
          supporting_doc_id: 'ORV-0016',
          source_name: 'Maritime Bulletin',
          reliability_tier: 1,
        },
      ],
      affected_regions: ['Midgard', 'Tolan'],
      affected_sectors: ['Grain', 'Fertilizer'],
      affected_trade_routes: ['Tolan Maritime Corridor'],
      key_stakeholders: ['Midgard Maritime Commission'],
      exposure_table: [
        {
          country: 'Midgard',
          sector: 'Wheat',
          metric: 'net_value_loss_pct',
          unit: '%',
          period: '2026-Q4',
          thor_range: '12% - 18%',
          loki_range: '4% - 6%',
          odin_adjudicated_range: '6% - 10%',
          odin_status: 'established',
          key_assumptions: ['30-day alternative routing'],
        },
      ],
      quantitative_summary: 'Adjudicated exposure indicates moderate value loss.',
      established_claims: [],
      contested_claims: [],
      concessions: [],
      unresolved_disputes: [],
      overall_confidence: 0.88,
      confidence_assessment: 'high',
      is_evidence_sufficient: true,
      evidence_limitations: ['Pre-closure baseline volume is unindexed.'],
      key_uncertainties: ['Duration of alternative routing permits.'],
      next_quarter_outlook: 'Market conditions projected to normalize by late Q1 2027.',
      recommended_actions: ['Re-route maritime shipments via Cape corridor.'],
      recommendations_qualified: true,
      cited_sources: [
        {
          doc_id: 'ORV-0016',
          paragraph: 'P3',
          source_name: 'Maritime Bulletin',
          reliability_tier: 1,
          publication_date: '2026-10-24',
          quote_or_datapoint: 'Closure expected to persist for 3 weeks.',
        },
      ],
      total_trials: 1,
      retries_attempted: 0,
      max_retries: 2,
      trial_progression_summary: [],
    };

    render(
      <ExecutiveScroll
        briefing={briefing}
        loading={false}
        onRefresh={vi.fn()}
        onConveneDebate={vi.fn()}
      />
    );

    expect(screen.getByText('Tolan Strait Disruption Briefing')).toBeTruthy();
    expect(screen.getByText(/Comprehensive analysis indicates manageable regional disruption/)).toBeTruthy();
    expect(screen.getByText('1. Executive Summary & Foundational Verification')).toBeTruthy();
    expect(screen.getByText('2. Chronological Disruption Milestones')).toBeTruthy();
    expect(screen.getByText('3. Disruption Scope & Key Stakeholders')).toBeTruthy();
    expect(screen.getByText('4. Quantitative Exposure Comparison')).toBeTruthy();
    expect(screen.getByText('7. Evidence Provenance & Bibliography')).toBeTruthy();
    expect(screen.getAllByText('ORV-0016').length).toBeGreaterThanOrEqual(1);
  });
});
