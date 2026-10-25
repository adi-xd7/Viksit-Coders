import React, { useState } from 'react';
import type { CaseCreateRequest } from '../types';
import { X, ShieldAlert, FolderPlus } from 'lucide-react';

export interface CaseFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (request: CaseCreateRequest) => Promise<void>;
}

export const CaseFormModal: React.FC<CaseFormModalProps> = ({ isOpen, onClose, onSubmit }) => {
  const [caseId, setCaseId] = useState('');
  const [question, setQuestion] = useState('');
  const [asOfDate, setAsOfDate] = useState('2026-10-25');
  const [eventId, setEventId] = useState('E5');
  const [isVerified, setIsVerified] = useState(true);

  const [loading, setLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    // Client-side validation matching backend regex & rules
    if (!caseId.trim()) {
      setFormError('Case Identifier is required (e.g., CASE-E5).');
      return;
    }
    if (!question.trim()) {
      setFormError('Disruption inquiry question is required.');
      return;
    }
    const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
    if (!dateRegex.test(asOfDate.trim())) {
      setFormError('As-of Date must strictly follow YYYY-MM-DD format.');
      return;
    }

    try {
      setLoading(true);
      await onSubmit({
        case_id: caseId.trim(),
        question: question.trim(),
        as_of_date: asOfDate.trim(),
        event_id: eventId.trim() || null,
        is_verified: isVerified,
      });
      onClose();
      // Reset form
      setCaseId('');
      setQuestion('');
    } catch (err: unknown) {
      if (err instanceof Error) {
        setFormError(err.message);
      } else {
        setFormError('An unexpected error occurred while registering the case.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div className="modal-card">
        <div className="modal-header">
          <div className="card-title" id="modal-title">
            <FolderPlus size={20} />
            <span>Open New Disruption Dossier</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="btn-stone btn-sm"
            aria-label="Close dialog"
            disabled={loading}
          >
            <X size={16} />
          </button>
        </div>

        {formError && (
          <div className="error-banner mb-4">
            <div className="error-banner-content">
              <ShieldAlert size={18} />
              <div className="error-detail">{formError}</div>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="case_id">Case Identifier *</label>
            <input
              id="case_id"
              type="text"
              required
              placeholder="e.g. CASE-E5"
              value={caseId}
              onChange={(e) => setCaseId(e.target.value)}
              disabled={loading}
            />
            <div className="form-help">
              Unique dossier identifier recognized across Heimdall, Thor, Loki, and Odin.
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="question">Target Disruption Inquiry *</label>
            <textarea
              id="question"
              required
              rows={3}
              placeholder="e.g. What is the impact of the Tolan Strait disruption on Midgard wheat supplies and Q4 market pricing?"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={loading}
            />
            <div className="form-help">
              The focal strategic question to be adjudicated by the multi-agent council.
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <div className="form-group">
              <label htmlFor="as_of_date">As-Of Cutoff Date (YYYY-MM-DD) *</label>
              <input
                id="as_of_date"
                type="date"
                required
                value={asOfDate}
                onChange={(e) => setAsOfDate(e.target.value)}
                disabled={loading}
              />
              <div className="form-help">
                Simulated clock cutoff; evidence published post-cutoff will be rejected.
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="event_id">Event Identifier (Optional)</label>
              <input
                id="event_id"
                type="text"
                placeholder="e.g. E5"
                value={eventId}
                onChange={(e) => setEventId(e.target.value)}
                disabled={loading}
              />
              <div className="form-help">Associated Runemark event ID, e.g. E5.</div>
            </div>
          </div>

          <div className="form-group">
            <div className="checkbox-wrap">
              <input
                id="is_verified"
                type="checkbox"
                checked={isVerified}
                onChange={(e) => setIsVerified(e.target.checked)}
                disabled={loading}
              />
              <label htmlFor="is_verified" style={{ marginBottom: 0, textTransform: 'none', fontWeight: 500 }}>
                Initial Verification Presumption (Subject to Heimdall Verification Gate)
              </label>
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" onClick={onClose} className="btn btn-stone" disabled={loading}>
              Cancel
            </button>
            <button type="submit" className="btn btn-royal" disabled={loading}>
              {loading ? 'Filing Dossier...' : 'File Case Dossier'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
