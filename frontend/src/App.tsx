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
import './App.css';

export const App: React.FC = () => {
  // Navigation & Modal State
  const [activeSection, setActiveSection] = useState<ActiveSection>('hall');
  const [isNewCaseModalOpen, setIsNewCaseModalOpen] = useState(false);

  // Core Data State
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [cases, setCases] = useState<CaseSummaryResponse[]>([]);
  const [casesLoading, setCasesLoading] = useState(false);

  // Selected Case State
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [selectedCaseFile, setSelectedCaseFile] = useState<CaseFile | null>(null);
  const [selectedSummary, setSelectedSummary] = useState<CaseSummaryResponse | null>(null);
  const [selectedDebateResult, setSelectedDebateResult] = useState<DebateResult | null>(null);
  const [selectedTrials, setSelectedTrials] = useState<TrialRecord[]>([]);
  const [selectedBriefing, setSelectedBriefing] = useState<ExecutiveBriefing | null>(null);

  // Loading & Execution State
  const [caseLoading, setCaseLoading] = useState(false);
  const [debateRunning, setDebateRunning] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  // 1. Fetch System Health
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

  // 2. Fetch All Registered Cases
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

  // 3. Load Selected Case Deliverables
  const loadCaseDetails = useCallback(
    async (caseId: string, availableCases: CaseSummaryResponse[]) => {
      try {
        setCaseLoading(true);
        setErrorMessage(null);
        setErrorCode(null);

        const currentSummary = availableCases.find((c) => c.case_id === caseId) || null;
        setSelectedSummary(currentSummary);

        // Fetch case file
        const file = await api.getCase(caseId);
        setSelectedCaseFile(file);

        // If debate has completed, fetch results, trials, and briefing
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
            const briefing = await api.getBriefing(caseId);
            setSelectedBriefing(briefing);
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
          setErrorMessage(`Case "${caseId}" could not be retrieved: ${err.message}`);
          setErrorCode(err.errorCode || `HTTP_${err.status}`);
        } else {
          setErrorMessage(`Error retrieving dossier for ${caseId}.`);
        }
      } finally {
        setCaseLoading(false);
      }
    },
    []
  );

  // Initial Load
  useEffect(() => {
    let isMounted = true;

    const initialize = async () => {
      setHealthLoading(true);
      try {
        const h = await api.getHealth();
        if (isMounted) setHealth(h);
      } catch {
        if (isMounted) setHealth(null);
      } finally {
        if (isMounted) setHealthLoading(false);
      }

      setCasesLoading(true);
      try {
        const loadedCases = await api.getCases();
        if (isMounted) {
          setCases(loadedCases);
          if (loadedCases.length > 0 && !selectedCaseId) {
            setSelectedCaseId(loadedCases[0].case_id);
            loadCaseDetails(loadedCases[0].case_id, loadedCases);
          }
        }
      } catch (err: unknown) {
        if (isMounted) {
          if (err instanceof ApiError) {
            setErrorMessage(`Failed to load case registry: ${err.message}`);
            setErrorCode(err.errorCode || `HTTP_${err.status}`);
          } else {
            setErrorMessage('Unable to reach the RAGNAROK Courtroom server. Ensure the backend is active.');
          }
        }
      } finally {
        if (isMounted) setCasesLoading(false);
      }
    };

    initialize();

    return () => {
      isMounted = false;
    };
  }, [loadCaseDetails, selectedCaseId]);

  // Handler: Select a Case
  const handleSelectCase = (caseId: string) => {
    setSelectedCaseId(caseId);
    loadCaseDetails(caseId, cases);
    setActiveSection('dossier');
  };

  // Handler: File New Case
  const handleCreateCase = async (req: CaseCreateRequest) => {
    try {
      setErrorMessage(null);
      await api.createCase(req);
      const updatedCases = await fetchCases();
      setSelectedCaseId(req.case_id);
      await loadCaseDetails(req.case_id, updatedCases);
      setActiveSection('dossier');
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        throw new Error(`Registration rejected (${err.status}): ${err.message}`);
      }
      throw err;
    }
  };

  // Handler: Run Debate
  const handleRunDebate = async (caseId: string, maxRetries: number) => {
    try {
      setDebateRunning(true);
      setErrorMessage(null);
      setErrorCode(null);

      // Execute multi-agent debate
      const debateResult = await api.runDebate(caseId, { max_retries: maxRetries });
      setSelectedDebateResult(debateResult);

      // Refresh case summary and list
      const updatedCases = await fetchCases();
      const summary = updatedCases.find((c) => c.case_id === caseId) || null;
      setSelectedSummary(summary);

      // Refresh trials and briefing
      try {
        const trials = await api.getTrials(caseId);
        setSelectedTrials(trials);
      } catch {
        // Ignored if trials endpoint has partial
      }

      try {
        const briefing = await api.getBriefing(caseId);
        setSelectedBriefing(briefing);
      } catch {
        // Ignored if briefing not yet generated
      }

      // Automatically transition to Council Verdict to review Odin's findings
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

      {/* Case Indicator Sub-bar */}
      {selectedCaseId && selectedCaseFile && (
        <div className="case-indicator-bar no-print">
          <div className="case-indicator-inner">
            <div className="case-indicator-left">
              <span className="case-tag">{selectedCaseFile.case_id}</span>
              <span className="case-question-preview">"{selectedCaseFile.question}"</span>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs font-mono text-stone-500">Clock: {selectedCaseFile.as_of_date}</span>
              <button
                type="button"
                onClick={() => setActiveSection('hall')}
                className="text-xs font-semibold text-amber-800 hover:underline"
              >
                Switch Case
              </button>
            </div>
          </div>
        </div>
      )}

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
