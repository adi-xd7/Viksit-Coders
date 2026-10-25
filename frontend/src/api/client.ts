/**
 * RAGNAROK Courtroom Analysis API Client
 * Centralized HTTP service interacting with FastAPI endpoints.
 */

import type {
  HealthResponse,
  CaseSummaryResponse,
  CaseCreateRequest,
  CaseFile,
  DebateRunRequest,
  DebateResult,
  ExecutiveBriefing,
  TrialRecord,
  ErrorResponse,
} from '../types';

export class ApiError extends Error {
  public status: number;
  public errorCode?: string | null;
  public caseId?: string | null;

  constructor(status: number, message: string, errorCode?: string | null, caseId?: string | null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.errorCode = errorCode;
    this.caseId = caseId;
  }
}

const getBaseUrl = (): string => {
  const envUrl = import.meta.env.VITE_API_BASE_URL;
  if (envUrl) {
    // Strip trailing slashes
    return envUrl.replace(/\/+$/, '');
  }
  return '';
};

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorDetail = `HTTP ${res.status}: ${res.statusText}`;
    let errorCode: string | null = null;
    let caseId: string | null = null;

    try {
      const data = await res.json();
      if (data && typeof data === 'object') {
        const errResp = data as ErrorResponse;
        if (errResp.detail) {
          if (typeof errResp.detail === 'string') {
            errorDetail = errResp.detail;
          } else if (Array.isArray(errResp.detail)) {
            // Pydantic validation error array
            errorDetail = (errResp.detail as Array<{ msg?: string; loc?: string[] }>)
              .map((d) => `${d.loc ? d.loc.join('.') + ': ' : ''}${d.msg || JSON.stringify(d)}`)
              .join('; ');
          } else {
            errorDetail = JSON.stringify(errResp.detail);
          }
        }
        errorCode = errResp.error_code || null;
        caseId = errResp.case_id || null;
      }
    } catch {
      // Body not JSON
    }

    throw new ApiError(res.status, errorDetail, errorCode, caseId);
  }

  return (await res.json()) as T;
}

export const api = {
  /**
   * Check the health of the backend API and corpus status.
   */
  async getHealth(): Promise<HealthResponse> {
    const res = await fetch(`${getBaseUrl()}/health`);
    return handleResponse<HealthResponse>(res);
  },

  /**
   * List all registered cases and their execution statuses.
   */
  async getCases(): Promise<CaseSummaryResponse[]> {
    const res = await fetch(`${getBaseUrl()}/cases`);
    return handleResponse<CaseSummaryResponse[]>(res);
  },

  /**
   * Retrieve a single case file by ID.
   */
  async getCase(caseId: string): Promise<CaseFile> {
    const res = await fetch(`${getBaseUrl()}/cases/${encodeURIComponent(caseId)}`);
    return handleResponse<CaseFile>(res);
  },

  /**
   * Register a new disruption case dossier.
   */
  async createCase(request: CaseCreateRequest): Promise<CaseFile> {
    const res = await fetch(`${getBaseUrl()}/cases`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    return handleResponse<CaseFile>(res);
  },

  /**
   * Execute the multi-agent debate orchestrator with bounded sufficiency feedback.
   */
  async runDebate(caseId: string, request: DebateRunRequest = {}): Promise<DebateResult> {
    const res = await fetch(`${getBaseUrl()}/cases/${encodeURIComponent(caseId)}/debate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    return handleResponse<DebateResult>(res);
  },

  /**
   * Retrieve stored debate results for a case.
   */
  async getResults(caseId: string): Promise<DebateResult> {
    const res = await fetch(`${getBaseUrl()}/cases/${encodeURIComponent(caseId)}/results`);
    return handleResponse<DebateResult>(res);
  },

  /**
   * Retrieve or generate the executive briefing for a case.
   */
  async getBriefing(caseId: string): Promise<ExecutiveBriefing> {
    const res = await fetch(`${getBaseUrl()}/cases/${encodeURIComponent(caseId)}/briefing`);
    return handleResponse<ExecutiveBriefing>(res);
  },

  /**
   * Retrieve chronological trial history records for a case.
   */
  async getTrials(caseId: string): Promise<TrialRecord[]> {
    const res = await fetch(`${getBaseUrl()}/cases/${encodeURIComponent(caseId)}/trials`);
    return handleResponse<TrialRecord[]>(res);
  },
};
