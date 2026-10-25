import React, { useState, useEffect, useCallback } from 'react';
import type {
  ActiveSection,
  HealthResponse,
  CaseSummaryResponse,
  CaseFile,
  DebateResult,
  TrialRecord,
  ExecutiveBriefing,
  CaseCreateRequest,
} from './types';
import { api, ApiError } from './api/client';
import { Navigation } from './components/Navigation';
import { ErrorBanner } from './components/ErrorBanner';
import { CaseFormModal } from './components/CaseFormModal';
import { TheHall } from './views/TheHall';
import { CaseDossier } from './views/CaseDossier';
import { CouncilVerdict } from './views/CouncilVerdict';
import { TrialChronicle } from './views/TrialChronicle';
import { ExecutiveScroll } from './views/ExecutiveScroll';

// Team Forensic Pipeline Imports
import { CaseForm } from './components/CaseForm';
import { Alert, Skeleton, ViewHead } from './components/layout';
import type { OpenRef } from './components/marks';
import { pipeline, Rail, TopBar } from './components/Shell';
import { useRoute, VIEW_LABEL } from './lib/route';
import { useCase } from './useCase';
import { EvidenceView, type DocTarget } from './views/EvidenceView';
import { ExposureView } from './views/ExposureView';
import { TraceView } from './views/TraceView';
import { TrialView } from './views/TrialView';
import './App.css';

const INTRO: Record<string, string> = {
  exposure: 'Low and high estimates per country and sector on one shared scale. Trade exposure is not a loss estimate.',
  evidence: 'Documents by publication date. Anything after the as-of date is blocked in code and logged.',
  trace: 'What Odin sent back, what changed between runs and why, and every recorded event.',
};

export const App: React.FC = () => {
  // Mode: Royal Archive (medieval) vs Forensic Pipeline (raw telemetry)
  const [mode, setMode] = useState<'archive' | 'forensic'>(() => {
    return window.location.hash.includes('view=') ? 'forensic' : 'archive';
  });

  // ----------------------------------------------------
  // Royal Archive State
  // ----------------------------------------------------
  const [activeSection, setActiveSection] = useState<ActiveSection>('hall');
  const [isNewCaseModalOpen, setIsNewCaseModalOpen] = useState(false);

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [cases, setCases] = useState<CaseSummaryResponse[]>([]);
  const [casesLoading, setCasesLoading] = useState(false);

  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [selectedCaseFile, setSelectedCaseFile] = useState<CaseFile | null>(null);
  const [selectedSummary, setSelectedSummary] = useState<CaseSummaryResponse | null>(null);
  const [selectedDebateResult, setSelectedDebateResult] = useState<DebateResult | null>(null);
  const [selectedTrials, setSelectedTrials] = useState<TrialRecord[]>([]);
  const [selectedBriefing, setSelectedBriefing] = useState<ExecutiveBriefing | null>(null);

  const [caseLoading, setCaseLoading] = useState(false);
  const [debateRunning, setDebateRunning] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  // ----------------------------------------------------
  // Forensic Pipeline State
  // ----------------------------------------------------
  const [route, go] = useRoute();
  const { caseId: forensicCaseId, view } = route;
  const [target, setTarget] = useState<DocTarget | null>(null);
  const { status, events, error: forensicError, trial, loaded } = useCase(forensicCaseId);

  useEffect(() => setTarget(null), [forensicCaseId]);
  useEffect(() => {
    if (mode === 'forensic') {
      document.title = forensicCaseId ? `${VIEW_LABEL[view]} · ${forensicCaseId} · Ragnarok` : 'Ragnarok';
    } else {
      document.title = 'RAGNAROK — Trial of the Nine Realms | Royal Intelligence Archive';
    }
  }, [mode, forensicCaseId, view]);

  const openDocRef: OpenRef = (r) => {
    setTarget({ doc_id: r.doc_id, paragraph_ref: r.paragraph_ref ?? null, row_id: r.row_id ?? null });
    if (view !== 'evidence') {
      go({ view: 'evidence' });
      window.scrollTo({ top: 0 });
    }
  };
  const onSelectForensicCase = (id: string) => go({ caseId: id, view: 'trial' });
  const finished = !!status && status.status !== 'running';
  const briefing = status?.results?.briefing ?? null;
  const failed = status?.status === 'failed';

  // ----------------------------------------------------
  // Royal Archive Actions
  // ----------------------------------------------------
  const fetchHealth = useCallback(async () => {
    try {
      setHealthLoading(true);
      const data = await api.getHealth();
      setHealth(data);
    } catch {
      setHealth(null);
    } finally {
      setHealthLoading(false);
    }
  }, []);

  const fetchCases = useCallback(async () => {
    try {
      setCasesLoading(true);
      const data = await api.getCases();
      setCases(data);
      return data;
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setErrorMessage(`Failed to load case registry: ${err.message}`);
        setErrorCode(err.errorCode || `HTTP_${err.status}`);
      } else {
        setErrorMessage('Unable to reach the RAGNAROK Courtroom server. Ensure the backend is active.');
      }
      return [];
    } finally {
      setCasesLoading(false);
    }
  }, []);

  const loadCaseDetails = useCallback(
    async (caseId: string, availableCases: CaseSummaryResponse[]) => {
      try {
        setCaseLoading(true);
        setErrorMessage(null);
        setErrorCode(null);

        const currentSummary = availableCases.find((c) => c.case_id === caseId) || null;
        setSelectedSummary(currentSummary);

        const file = await api.getCase(caseId);
        setSelectedCaseFile(file);

        if (currentSummary?.has_debate_result) {
          try {
            const results = await api.getResults(caseId);
            setSelectedDebateResult(results);
          } catch {
            setSelectedDebateResult(null);
          }

          try {
            const trials = await api.getTrials(caseId);
            setSelectedTrials(trials);
          } catch {
            setSelectedTrials([]);
          }

          try {
            const brief = await api.getBriefing(caseId);
            setSelectedBriefing(brief);
          } catch {
            setSelectedBriefing(null);
          }
        } else {
          setSelectedDebateResult(null);
          setSelectedTrials([]);
          setSelectedBriefing(null);
        }
      } catch (err: unknown) {
        if (err instanceof ApiError) {
          setErrorMessage(`Failed to load case dossier "${caseId}": ${err.message}`);
          setErrorCode(err.errorCode || `HTTP_${err.status}`);
        } else {
          setErrorMessage(`Error loading details for case "${caseId}".`);
        }
      } finally {
        setCaseLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    fetchHealth();
    fetchCases();
  }, [fetchHealth, fetchCases]);

  const handleSelectCase = (caseId: string) => {
    setSelectedCaseId(caseId);
    loadCaseDetails(caseId, cases);
    setActiveSection('dossier');
  };

  const handleCreateCase = async (req: CaseCreateRequest) => {
    try {
      const created = await api.createCase(req);
      setIsNewCaseModalOpen(false);
      const updatedCases = await fetchCases();
      setSelectedCaseId(created.case_id);
      loadCaseDetails(created.case_id, updatedCases);
      setActiveSection('dossier');
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setErrorMessage(`Case registration rejected: ${err.message}`);
        setErrorCode(err.errorCode || `HTTP_${err.status}`);
      } else {
        setErrorMessage('Failed to create case. Please verify connection and format.');
      }
    }
  };

  const handleRunDebate = async (caseId: string, maxRetries: number) => {
    try {
      setDebateRunning(true);
      setErrorMessage(null);
      setErrorCode(null);

      const result = await api.runDebate(caseId, { max_retries: maxRetries });
      setSelectedDebateResult(result);

      const [trialsData, briefingData, updatedCases] = await Promise.all([
        api.getTrials(caseId).catch(() => []),
        api.getBriefing(caseId).catch(() => null),
        fetchCases(),
      ]);

      setSelectedTrials(trialsData);
      setSelectedBriefing(briefingData);

      const updatedSummary = updatedCases.find((c) => c.case_id === caseId) || null;
      setSelectedSummary(updatedSummary);

      setActiveSection('verdict');
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        let explanation = err.message;
        if (err.status === 409) {
          explanation = `Conflict (409): A debate is already actively running for case "${caseId}". Please wait for it to complete.`;
        } else if (err.status === 404) {
          explanation = `Not Found (404): Case "${caseId}" was not found in active in-memory storage.`;
        } else if (err.status === 422) {
          explanation = `Validation Error (422): Invalid debate parameters provided: ${err.message}`;
        } else if (err.status === 500) {
          explanation = `Orchestration Failure (500): The multi-agent debate encountered an internal engine error: ${err.message}`;
        }
        setErrorMessage(explanation);
        setErrorCode(err.errorCode || `HTTP_${err.status}`);
      } else {
        setErrorMessage('Unexpected network or execution error during deliberation.');
      }
    } finally {
      setDebateRunning(false);
    }
  };

  // ----------------------------------------------------
  // Render Forensic Pipeline Suite
  // ----------------------------------------------------
  if (mode === 'forensic') {
    let forensicBody: React.ReactNode;
    if (!forensicCaseId) {
      forensicBody = (
        <>
          <ViewHead title="New investigation">
            Ask a question and pick an as-of date. Heimdall investigates, Thor and Loki argue, Odin rules. Or open a saved case.
          </ViewHead>
          <CaseForm onCase={onSelectForensicCase} />
        </>
      );
    } else if (forensicError && !status) {
      forensicBody = <Alert tone="bad" title="Case unavailable">{forensicError}. Check the case ID, or that the API is running.</Alert>;
    } else if (!loaded) {
      forensicBody = <><ViewHead title={VIEW_LABEL[view]} /><Skeleton rows={6} label="Loading case" /></>;
    } else {
      forensicBody = (
        <>
          <ViewHead title={VIEW_LABEL[view]}>{view === 'trial' ? undefined : INTRO[view]}</ViewHead>
          {failed && (
            <Alert tone="bad" title={status?.stage === 'FAILED' ? 'This case failed. No briefing was produced.' : 'This case was interrupted before it finished.'}>
              {(status?.notes ?? []).slice(-3).map((n, i) => <span key={i} className="block">{n}</span>)}
              <span className="block">Partial results recorded before the failure are shown below.</span>
              {status?.limitations && (
                <details className="mt-1"><summary className="cursor-pointer">Limitation report</summary>
                  <pre className="m-0 mt-1 whitespace-pre-wrap font-mono text-xs">{status.limitations}</pre></details>
              )}
            </Alert>
          )}
          {status?.stop_reason && <Alert title="The trial stopped">{status.stop_reason}</Alert>}
          {forensicError && <Alert tone="bad" title="Live status unavailable">{forensicError}. Showing what was recorded so far.</Alert>}
          {view === 'trial' && <TrialView t={trial} open={openDocRef} question={status?.question} finished={finished} />}
          {view === 'exposure' && <ExposureView table={briefing?.exposure_table} t={trial} open={openDocRef} finished={finished} />}
          {view === 'evidence' && <EvidenceView asOf={status?.as_of} caseId={forensicCaseId} t={trial} target={target} open={openDocRef} />}
          {view === 'trace' && <TraceView t={trial} events={events} briefing={briefing} md={status?.results?.briefing_markdown}
            open={openDocRef} status={status?.status} />}
        </>
      );
    }

    return (
      <div className="min-h-screen bg-[#F6F7F8] text-[#15181C]">
        {/* Top Control Bar to Return to Royal Archive */}
        <div className="bg-[#191A18] text-[#FFFCF5] px-4 py-2 flex items-center justify-between text-xs border-b border-[#A8874A]">
          <div className="flex items-center gap-2 font-mono">
            <span className="text-[#A8874A] font-bold">RAGNAROK FORENSIC SUITE</span>
            <span>·</span>
            <span>Telemetry & Trace Mode</span>
          </div>
          <button
            type="button"
            onClick={() => setMode('archive')}
            className="px-3 py-1 bg-[#A8874A] text-[#191A18] font-bold rounded hover:bg-[#8E7039] transition-colors"
          >
            ← Return to Royal Archive
          </button>
        </div>

        <div className="px-0 pb-10 pt-0 sm:px-4 sm:pt-5">
          <div className="mx-auto max-w-[1180px] overflow-hidden border-[#D3D8DD] bg-white sm:rounded-md sm:border shadow-sm">
            <TopBar status={status} caseId={forensicCaseId} trial={trial} onCase={onSelectForensicCase} />
            <div className="grid min-h-[640px] grid-cols-1 md:grid-cols-[200px_minmax(0,1fr)]">
              <Rail view={view} onView={(v) => go({ view: v })} stages={forensicCaseId && loaded ? pipeline(status, trial) : null} />
              <main key={view} className="view-in min-w-0 px-4 pb-8 pt-5 md:px-7 md:pb-10 md:pt-6">{forensicBody}</main>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ----------------------------------------------------
  // Render Royal Intelligence Archive (Default)
  // ----------------------------------------------------
  return (
    <div className="app-shell">
      {/* Top Header & Navigation Rail */}
      <Navigation
        activeSection={activeSection}
        onSelectSection={setActiveSection}
        health={health}
        healthLoading={healthLoading}
        onRefreshHealth={fetchHealth}
        onOpenNewCaseModal={() => setIsNewCaseModalOpen(true)}
        hasSelectedCase={!!selectedCaseId}
      />

      {/* Case Indicator Sub-bar & Mode Switcher */}
      <div className="case-indicator-bar no-print">
        <div className="case-indicator-inner">
          <div className="case-indicator-left">
            {selectedCaseId && selectedCaseFile ? (
              <>
                <span className="case-tag">{selectedCaseFile.case_id}</span>
                <span className="case-question-preview">"{selectedCaseFile.question}"</span>
              </>
            ) : (
              <span className="text-xs font-serif italic text-stone-600">Select or file a case in The Hall to begin deliberation</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {selectedCaseFile && (
              <span className="text-xs font-mono text-stone-500">Clock: {selectedCaseFile.as_of_date}</span>
            )}
            <button
              type="button"
              onClick={() => {
                if (selectedCaseId) {
                  onSelectForensicCase(selectedCaseId);
                }
                setMode('forensic');
              }}
              className="text-xs font-mono font-medium px-2.5 py-1 rounded bg-[#232522] text-[#A8874A] border border-[#A8874A]/40 hover:bg-[#A8874A] hover:text-[#191A18] transition-colors"
            >
              Forensic Telemetry →
            </button>
          </div>
        </div>
      </div>

      {/* Main Content Area */}
      <main className="main-content">
        {/* Error Notification Banner */}
        {errorMessage && (
          <ErrorBanner
            title="Adversarial Deliberation Notice"
            message={errorMessage}
            errorCode={errorCode}
            onDismiss={() => {
              setErrorMessage(null);
              setErrorCode(null);
            }}
          />
        )}

        {/* View Switching */}
        {activeSection === 'hall' && (
          <TheHall
            cases={cases}
            loading={casesLoading}
            onSelectCase={handleSelectCase}
            onOpenNewCaseModal={() => setIsNewCaseModalOpen(true)}
            onRefresh={fetchCases}
          />
        )}

        {activeSection === 'dossier' && (
          <CaseDossier
            caseFile={selectedCaseFile}
            summary={selectedSummary}
            loading={caseLoading}
            debateRunning={debateRunning}
            onRunDebate={handleRunDebate}
            onViewVerdict={() => setActiveSection('verdict')}
            onViewChronicle={() => setActiveSection('chronicle')}
            onViewScroll={() => setActiveSection('scroll')}
          />
        )}

        {activeSection === 'verdict' && (
          <CouncilVerdict
            result={selectedDebateResult}
            loading={caseLoading}
            onRefresh={() => selectedCaseId && loadCaseDetails(selectedCaseId, cases)}
            onConveneDebate={() => setActiveSection('dossier')}
          />
        )}

        {activeSection === 'chronicle' && (
          <TrialChronicle
            trials={selectedTrials && selectedTrials.length > 0 ? selectedTrials : (selectedDebateResult?.trial_history || [])}
            loading={caseLoading}
            onRefresh={() => selectedCaseId && loadCaseDetails(selectedCaseId, cases)}
            onConveneDebate={() => setActiveSection('dossier')}
          />
        )}

        {activeSection === 'scroll' && (
          <ExecutiveScroll
            briefing={selectedBriefing}
            loading={caseLoading}
            onRefresh={() => selectedCaseId && loadCaseDetails(selectedCaseId, cases)}
            onConveneDebate={() => setActiveSection('dossier')}
          />
        )}
      </main>

      {/* Case Registration Modal */}
      <CaseFormModal
        isOpen={isNewCaseModalOpen}
        onClose={() => setIsNewCaseModalOpen(false)}
        onSubmit={handleCreateCase}
      />
    </div>
  );
};

export default App;
