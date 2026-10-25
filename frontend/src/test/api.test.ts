import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api, ApiError } from '../api/client';
import type {
  HealthResponse,
  CaseSummaryResponse,
  CaseCreateRequest,
  CaseFile,
  DebateResult,
  TrialRecord,
  ExecutiveBriefing,
} from '../types';

describe('RAGNAROK Frontend API Client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('getHealth() returns healthy response', async () => {
    const mockHealth: HealthResponse = {
      status: 'healthy',
      service: 'ragnarok-ps3-courtroom',
      version: '1.0.0',
      timestamp: '2026-10-25T18:00:00Z',
      corpus_available: true,
      storage_type: 'in_memory',
    };

    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => mockHealth,
    } as Response);

    const res = await api.getHealth();
    expect(res.status).toBe('healthy');
    expect(res.corpus_available).toBe(true);
    expect(res.version).toBe('1.0.0');
  });

  it('getCases() returns list of case summaries', async () => {
    const mockCases: CaseSummaryResponse[] = [
      {
        case_id: 'CASE-E5',
        question: 'Tolan Strait disruption',
        as_of_date: '2026-10-25',
        has_debate_result: true,
        has_briefing: true,
        debate_status: 'success',
        is_evidence_sufficient: true,
      },
    ];

    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => mockCases,
    } as Response);

    const res = await api.getCases();
    expect(res).toHaveLength(1);
    expect(res[0].case_id).toBe('CASE-E5');
    expect(res[0].has_debate_result).toBe(true);
  });

  it('createCase() posts CaseCreateRequest and returns CaseFile', async () => {
    const newCaseReq: CaseCreateRequest = {
      case_id: 'CASE-E6',
      question: 'Baltic transit delay impact',
      as_of_date: '2026-10-25',
      event_id: 'E6',
      is_verified: true,
    };

    const mockCreated: CaseFile = {
      case_id: 'CASE-E6',
      question: 'Baltic transit delay impact',
      as_of_date: '2026-10-25',
      is_verified: true,
      event_id: 'E6',
      round_number: 1,
      run_number: 1,
      claims: [],
      attacks: [],
      concessions: [],
      judicial_rulings: [],
    };

    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => mockCreated,
    } as Response);

    const res = await api.createCase(newCaseReq);
    expect(res.case_id).toBe('CASE-E6');
    expect(res.is_verified).toBe(true);
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/cases'),
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
    );
  });

  it('runDebate() sends debate run request and returns DebateResult', async () => {
    const mockResult = {
      case_id: 'CASE-E5',
      as_of_date: '2026-10-25',
      run_number: 1,
      status: 'success',
      stages_executed: ['heimdall', 'thor_advocacy', 'loki_advocacy', 'cross_exam', 'odin_adjudication'],
      total_trials: 1,
      retries_attempted: 0,
      max_retries: 2,
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
      trial_history: [],
    } as unknown as DebateResult;

    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => mockResult,
    } as Response);

    const res = await api.runDebate('CASE-E5', { max_retries: 2 });
    expect(res.status).toBe('success');
    expect(res.case_id).toBe('CASE-E5');
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/cases/CASE-E5/debate'),
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('throws ApiError with 409 on concurrent debate execution', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 409,
      statusText: 'Conflict',
      json: async () => ({
        detail: 'Debate is already running for case CASE-E5',
        error_code: 'DEBATE_ALREADY_ACTIVE',
        case_id: 'CASE-E5',
      }),
    } as Response);

    await expect(api.runDebate('CASE-E5')).rejects.toThrow(ApiError);
    await expect(api.runDebate('CASE-E5')).rejects.toMatchObject({
      status: 409,
      errorCode: 'DEBATE_ALREADY_ACTIVE',
    });
  });

  it('throws ApiError with 404 for unknown case ID', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: async () => ({
        detail: 'Case NONEXISTENT not found',
        error_code: 'CASE_NOT_FOUND',
      }),
    } as Response);

    await expect(api.getCase('NONEXISTENT')).rejects.toThrow(ApiError);
  });

  it('handles Pydantic validation error arrays in error response', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 422,
      statusText: 'Unprocessable Entity',
      json: async () => ({
        detail: [
          { loc: ['body', 'as_of_date'], msg: 'String should match pattern' },
        ],
      }),
    } as Response);

    try {
      await api.createCase({
        case_id: 'C1',
        question: 'Q',
        as_of_date: 'invalid-date',
      });
      expect.fail('Should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).message).toContain('body.as_of_date: String should match pattern');
    }
  });

  it('getBriefing() returns ExecutiveBriefing', async () => {
    const mockBriefing = {
      case_id: 'CASE-E5',
      as_of_date: '2026-10-25',
      question: 'Q',
      title: 'Disruption Impact Briefing',
      status: 'completed',
      generated_at: '2026-10-25T18:00:00Z',
      executive_summary: 'Summary text',
      event_verified: true,
      verification_summary: 'Event confirmed',
      confirmed_disruption_facts: ['Fact 1'],
      timeline: [],
      affected_regions: ['Midgard'],
      affected_sectors: ['Wheat'],
      affected_trade_routes: ['Tolan Strait'],
      key_stakeholders: ['AgriAuthority'],
      exposure_table: [],
      quantitative_summary: 'Quant text',
      established_claims: [],
      contested_claims: [],
      concessions: [],
      unresolved_disputes: [],
      overall_confidence: 0.85,
      confidence_assessment: 'high',
      is_evidence_sufficient: true,
      evidence_limitations: [],
      key_uncertainties: [],
      next_quarter_outlook: 'Outlook text',
      recommended_actions: ['Action 1'],
      recommendations_qualified: true,
      cited_sources: [],
      total_trials: 1,
      retries_attempted: 0,
      max_retries: 2,
      trial_progression_summary: [],
    } as unknown as ExecutiveBriefing;

    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => mockBriefing,
    } as Response);

    const res = await api.getBriefing('CASE-E5');
    expect(res.title).toBe('Disruption Impact Briefing');
    expect(res.confidence_assessment).toBe('high');
    expect(res.event_verified).toBe(true);
  });

  it('getTrials() returns list of TrialRecords', async () => {
    const mockTrials = [
      {
        trial_number: 1,
        status: 'success',
        is_evidence_sufficient: true,
        evidence_gaps_identified: [],
      },
    ] as unknown as TrialRecord[];

    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => mockTrials,
    } as Response);

    const res = await api.getTrials('CASE-E5');
    expect(res).toHaveLength(1);
    expect(res[0].trial_number).toBe(1);
    expect(res[0].is_evidence_sufficient).toBe(true);
  });
});
