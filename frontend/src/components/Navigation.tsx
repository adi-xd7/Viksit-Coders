import React from 'react';
import type { ActiveSection, HealthResponse } from '../types';
import { HealthIndicator } from './HealthIndicator';
import {
  Castle,
  FolderOpen,
  Scale,
  History,
  Scroll,
  Plus,
} from 'lucide-react';

export interface NavigationProps {
  activeSection: ActiveSection;
  onSelectSection: (section: ActiveSection) => void;
  health: HealthResponse | null;
  healthLoading: boolean;
  onRefreshHealth: () => void;
  onOpenNewCaseModal: () => void;
  hasSelectedCase: boolean;
}

export const Navigation: React.FC<NavigationProps> = ({
  activeSection,
  onSelectSection,
  health,
  healthLoading,
  onRefreshHealth,
  onOpenNewCaseModal,
  hasSelectedCase,
}) => {
  return (
    <header className="archive-header-bar">
      <div className="header-inner">
        {/* Brand Identity */}
        <div className="brand-section">
          <div className="brand-crest" aria-hidden="true">
            <Scale size={20} />
          </div>
          <div className="brand-title-wrap">
            <div className="brand-title">
              Ragna<span>rok</span>
            </div>
            <div className="brand-subtitle">Trial of the Nine Realms · Courtroom Archive</div>
          </div>
        </div>

        {/* Five Core Archival Sections */}
        <nav className="archive-nav" aria-label="Archive Navigation">
          <button
            type="button"
            className={`nav-item ${activeSection === 'hall' ? 'active' : ''}`}
            onClick={() => onSelectSection('hall')}
            aria-current={activeSection === 'hall' ? 'page' : undefined}
          >
            <Castle className="nav-icon" />
            <span>The Hall</span>
          </button>

          <button
            type="button"
            className={`nav-item ${activeSection === 'dossier' ? 'active' : ''}`}
            onClick={() => onSelectSection('dossier')}
            aria-current={activeSection === 'dossier' ? 'page' : undefined}
            title={hasSelectedCase ? 'View active case dossier' : 'Select a case to inspect dossier'}
          >
            <FolderOpen className="nav-icon" />
            <span>Case Dossier</span>
          </button>

          <button
            type="button"
            className={`nav-item ${activeSection === 'verdict' ? 'active' : ''}`}
            onClick={() => onSelectSection('verdict')}
            aria-current={activeSection === 'verdict' ? 'page' : undefined}
            title={hasSelectedCase ? "View Odin's judicial ruling" : 'Select a case to inspect verdict'}
          >
            <Scale className="nav-icon" />
            <span>Council Verdict</span>
          </button>

          <button
            type="button"
            className={`nav-item ${activeSection === 'chronicle' ? 'active' : ''}`}
            onClick={() => onSelectSection('chronicle')}
            aria-current={activeSection === 'chronicle' ? 'page' : undefined}
            title={hasSelectedCase ? 'View chronological trial records' : 'Select a case to inspect trial history'}
          >
            <History className="nav-icon" />
            <span>Trial Chronicle</span>
          </button>

          <button
            type="button"
            className={`nav-item ${activeSection === 'scroll' ? 'active' : ''}`}
            onClick={() => onSelectSection('scroll')}
            aria-current={activeSection === 'scroll' ? 'page' : undefined}
            title={hasSelectedCase ? 'View executive briefing report' : 'Select a case to view executive briefing'}
          >
            <Scroll className="nav-icon" />
            <span>Executive Scroll</span>
          </button>
        </nav>

        {/* Right Header Controls */}
        <div className="header-actions">
          <HealthIndicator health={health} loading={healthLoading} onRefresh={onRefreshHealth} />
          <button
            type="button"
            onClick={onOpenNewCaseModal}
            className="btn btn-royal btn-sm"
            title="Open a new disruption case dossier"
          >
            <Plus size={14} />
            <span>Open Dossier</span>
          </button>
        </div>
      </div>
    </header>
  );
};
