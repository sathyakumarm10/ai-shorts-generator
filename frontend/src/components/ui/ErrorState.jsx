import React from 'react'
import { AlertCircle, RefreshCw, X } from 'lucide-react'

export function ErrorState({
  title = 'An error occurred',
  message,
  onRetry = null,
  onDismiss = null,
}) {
  return (
    <div className="error-state-card" role="alert">
      <div className="error-state-icon-wrapper">
        <AlertCircle size={22} className="error-state-icon" />
      </div>
      <div className="error-state-content">
        <h4 className="error-state-title">{title}</h4>
        <p className="error-state-message">{message}</p>
      </div>
      <div className="error-state-actions">
        {onRetry && (
          <button
            type="button"
            className="btn-retry"
            onClick={onRetry}
            aria-label="Retry operation"
          >
            <RefreshCw size={14} />
            <span>Retry</span>
          </button>
        )}
        {onDismiss && (
          <button
            type="button"
            className="btn-dismiss"
            onClick={onDismiss}
            aria-label="Dismiss error"
          >
            <X size={16} />
          </button>
        )}
      </div>
    </div>
  )
}
