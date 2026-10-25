/**
 * TypeScript Type Definitions for RAGNAROK PS3 Frontend Layer
 * Exactly matches backend Pydantic models.
 */

export interface HealthResponse {
  status: 'healthy' | 'degraded' | 'unhealthy';
  service: string;
  version: string;
  timestamp: string;
  corpus_available: boolean;
  storage_type: string;
}

export interface CaseCreateRequest {
  case_id: string;
  question: string;
  as_of_date: string;
  event_id?: string | null;
  is_verified?: boolean;
}

export interface DebateRunRequest {
  max_retries?: number | null;
}

export interface CaseSummaryResponse {
  case_id: string;
  question: string;
  as_of_date: string;
  event_id?: string | null;
  has_debate_result: boolean;
  has_briefing: boolean;
  debate_status?: string | null;
  is_evidence_sufficient?: boolean | null;
}

export interface ErrorResponse {
  detail: string;
  error_code?: string | null;
  case_id?: string | null;
}

export interface EvidenceReference {
  doc_id: string;
  paragraph?: string | null;
  source_name?: string | null;
  reliability_tier?: number | null;
  publication_date?: string | null;
  pub_time?: string | null;
  quote_or_datapoint: string;
  is_off_runemark?: boolean;
}

export interface ExposureEstimate {
  country: string;
  sector: string;
  metric: string;
  unit: string;
  period: string;
  lower_bound: number;
  upper_bound: number;
  point_estimate?: number | null;
  baseline_or_denominator?: string | null;
  calculation_methodology?: string | null;
  assumptions?: string[];
}

export interface Claim {
  claim_id: string;
  proponent: 'loki' | 'thor' | 'heimdall' | 'odin' | 'unknown';
  statement: string;
  claim_type: 'sourced_fact' | 'inference';
  citations: EvidenceReference[];
  exposure_estimate?: ExposureEstimate | null;
  is_contested?: boolean;
  is_conceded?: boolean;
}

export interface CrossExamination {
  attack_id: string;
  attacker: 'loki' | 'thor';
  target_claim_id: string;
  attack_type: string;
  argument: string;
  counter_citations: EvidenceReference[];
}

export interface Concession {
  concession_id: string;
  advocate: 'loki' | 'thor';
  target_claim_id: string;
  action: 'concede' | 'defend' | 'adjust_range';
  reason: string;
  adjusted_range?: ExposureEstimate | null;
}

export interface ClaimRuling {
  claim_id: string;
  claim_statement: string;
  proponent: 'loki' | 'thor' | 'heimdall' | 'odin' | 'unknown';
  claim_type: 'sourced_fact' | 'inference';
  ruling: 'established' | 'contested' | 'conceded';
  confidence: number;
  reasoning: string;
  supporting_citations: EvidenceReference[];
  contradicting_citations: EvidenceReference[];
  loki_position?: string | null;
  thor_position?: string | null;
  concessions: Concession[];
  is_conceded: boolean;
  conceded_by?: 'loki' | 'thor' | null;
  evidence_gaps: string[];
  discrepancy_notes?: string | null;
  adjudicated_range?: ExposureEstimate | null;
}

export interface PremiseVerification {
  premise_id?: string;
  premise: string;
  status?: 'verified' | 'contradicted' | 'unverified' | 'inadmissible';
  confidence?: number;
  reasoning: string;
  citations?: EvidenceReference[];
  contradicting_citations?: EvidenceReference[];
  discrepancy_notes?: string | null;
}

export interface HeimdallVerificationResult {
  agent: 'heimdall';
  case_id: string;
  as_of_date: string;
  event_id?: string | null;
  is_event_real?: boolean;
  verification_status?: 'verified' | 'contradicted' | 'unverified' | 'error';
  premises?: PremiseVerification[];
  unverified_premises?: string[];
  contradicted_premises?: string[];
  evidence_examined?: string[];
  summary: string;
  error_message?: string | null;
  is_verified?: boolean;
  premises_evaluated?: PremiseVerification[];
}

export interface LokiResult {
  agent: 'loki';
  case_id: string;
  round_number: number;
  claims: Claim[];
  attacks: CrossExamination[];
  concessions: Concession[];
  summary: string;
}

export interface ThorResult {
  agent: 'thor';
  case_id: string;
  round_number: number;
  claims: Claim[];
  attacks: CrossExamination[];
  concessions: Concession[];
  summary: string;
}

export interface OdinResult {
  agent: 'odin';
  case_id: string;
  as_of_date: string;
  run_number: number;
  adjudication_status: 'completed' | 'insufficient_evidence' | 'error';
  claim_rulings: ClaimRuling[];
  established_claims: string[];
  contested_claims: string[];
  conceded_claims: string[];
  unresolved_disputes: string[];
  evidence_limitations: string[];
  evidence_examined: string[];
  is_evidence_sufficient: boolean;
  summary: string;
  error_message?: string | null;
}

export interface CaseFile {
  case_id: string;
  question: string;
  as_of_date: string;
  is_verified: boolean;
  event_id?: string | null;
  round_number: number;
  run_number: number;
  claims: Claim[];
  attacks: CrossExamination[];
  concessions: Concession[];
  judicial_rulings: Record<string, unknown>[];
}

export interface TrialRecord {
  trial_number: number;
  status: 'success' | 'partial' | 'error';
  failed_stage?: string | null;
  error_message?: string | null;
  heimdall_verification?: HeimdallVerificationResult | null;
  loki_round1?: LokiResult | null;
  thor_round1?: ThorResult | null;
  loki_round2?: LokiResult | null;
  thor_round2?: ThorResult | null;
  odin_adjudication?: OdinResult | null;
  is_evidence_sufficient: boolean;
  evidence_gaps_identified?: string[];
  unresolved_disputes?: string[];
  loop_stop_reason?: string | null;
  gap_resolution_summary?: string | null;
}

export interface DebateResult {
  case_id: string;
  as_of_date: string;
  run_number: number;
  status: 'success' | 'partial' | 'error';
  failed_stage?: string | null;
  error_message?: string | null;
  heimdall_verification?: HeimdallVerificationResult | null;
  loki_round1?: LokiResult | null;
  thor_round1?: ThorResult | null;
  loki_round2?: LokiResult | null;
  thor_round2?: ThorResult | null;
  odin_adjudication?: OdinResult | null;
  case_file: CaseFile;
  stages_executed: string[];
  total_trials: number;
  retries_attempted: number;
  max_retries: number;
  loop_stop_reason?: string | null;
  trial_history: TrialRecord[];
}

export interface TimelineEvent {
  event_date: string;
  description: string;
  supporting_doc_id?: string | null;
  source_name?: string | null;
  reliability_tier?: number | null;
}

export interface ExposureComparisonRow {
  country: string;
  sector: string;
  metric: string;
  unit: string;
  period: string;
  thor_range?: string | null;
  loki_range?: string | null;
  odin_adjudicated_range?: string | null;
  odin_status: 'established' | 'contested' | 'conceded' | 'unsupported';
  baseline_or_denominator?: string | null;
  calculation_methodology?: string | null;
  key_assumptions: string[];
}

export interface ConcessionSummary {
  concession_id: string;
  advocate: 'loki' | 'thor';
  target_claim_id: string;
  action: 'concede' | 'defend' | 'adjust_range';
  reason: string;
  adjusted_range_str?: string | null;
}

export interface CitedSourceProvenance {
  doc_id: string;
  paragraph?: string | null;
  source_name?: string | null;
  reliability_tier?: number | null;
  publication_date?: string | null;
  pub_time?: string | null;
  quote_or_datapoint: string;
  is_off_runemark?: boolean;
}

export interface ExecutiveBriefing {
  case_id: string;
  as_of_date: string;
  event_id?: string | null;
  question: string;
  title: string;
  status: 'completed' | 'insufficient_evidence' | 'insufficient_input' | 'error';
  generated_at: string;
  executive_summary: string;
  event_verified: boolean;
  verification_summary: string;
  confirmed_disruption_facts: string[];
  timeline: TimelineEvent[];
  affected_regions: string[];
  affected_sectors: string[];
  affected_trade_routes: string[];
  key_stakeholders: string[];
  exposure_table: ExposureComparisonRow[];
  quantitative_summary: string;
  established_claims: ClaimRuling[];
  contested_claims: ClaimRuling[];
  concessions: ConcessionSummary[];
  unresolved_disputes: string[];
  overall_confidence: number;
  confidence_assessment: 'high' | 'moderate' | 'low' | 'unsubstantiated';
  is_evidence_sufficient: boolean;
  evidence_limitations: string[];
  key_uncertainties: string[];
  next_quarter_outlook: string;
  recommended_actions: string[];
  recommendations_qualified: boolean;
  cited_sources: CitedSourceProvenance[];
  total_trials: number;
  retries_attempted: number;
  max_retries: number;
  loop_stop_reason?: string | null;
  trial_progression_summary: string[];
  error_message?: string | null;
}

export type ActiveSection = 'hall' | 'dossier' | 'verdict' | 'chronicle' | 'scroll';
