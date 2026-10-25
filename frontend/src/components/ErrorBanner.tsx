import React from 'react';
import { AlertTriangle, X } from 'lucide-react';

export interface ErrorBannerProps {
  title?: string;
  message: string;
  errorCode?: string | null;
  onDismiss?: () => void;
}

export const ErrorBanner: React.FC<ErrorBannerProps> = ({
  title = 'Deliberation / System Notice',
  message,
  errorCode,
  onDismiss,
}) => {
  if (!message) return null;

  return (
    <div className="error-banner" role="alert" aria-live="assertive">
      <div className="error-banner-content">
        <AlertTriangle size={20} />
        <div>
          <div className="error-title">
            {title}
            {errorCode && <span className="font-mono text-xs ml-2">({errorCode})</span>}
          </div>
          <div className="error-detail">{message}</div>
        </div>
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="btn-stone btn-sm"
          aria-label="Dismiss error notification"
        >
          <X size={14} />
        </button>
      )}
    </div>
  );
};
