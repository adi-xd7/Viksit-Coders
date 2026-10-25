import React from 'react';
import type { HealthResponse } from '../types';
import { Database, ShieldCheck } from 'lucide-react';

export interface HealthIndicatorProps {
  health: HealthResponse | null;
  loading: boolean;
  onRefresh?: () => void;
}

export const HealthIndicator: React.FC<HealthIndicatorProps> = ({ health, loading, onRefresh }) => {
  if (loading && !health) {
    return (
      <div className="health-pill">
        <span className="status-dot degraded animate-pulse" />
        <span>Polling Courtroom...</span>
      </div>
    );
  }

  if (!health) {
    return (
      <div className="health-pill" title="Backend service unreachable at configured API URL">
        <span className="status-dot unhealthy" />
        <span>Backend Offline</span>
        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            className="text-xs text-amber-500 hover:underline ml-1"
            title="Retry connecting to API"
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  const dotClass =
    health.status === 'healthy' ? '' : health.status === 'degraded' ? 'degraded' : 'unhealthy';

  const corpusLabel = health.corpus_available ? 'Corpus E5 Active' : 'Mock Fallback';

  return (
    <div
      className="health-pill"
      title={`RAGNAROK Server v${health.version} | Storage: ${health.storage_type} | Timestamp: ${health.timestamp}`}
    >
      <span className={`status-dot ${dotClass}`} />
      <span className="flex items-center gap-1">
        <ShieldCheck size={12} className="inline mr-1 text-amber-400" />
        <span>v{health.version}</span>
      </span>
      <span className="text-stone-500">|</span>
      <span className="flex items-center gap-1 text-stone-300">
        <Database size={11} className="inline mr-1" />
        <span>{corpusLabel}</span>
      </span>
    </div>
  );
};
