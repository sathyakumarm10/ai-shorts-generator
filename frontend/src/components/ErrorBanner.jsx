import React from 'react'
import { AlertCircle, RefreshCw, X } from 'lucide-react'

export function ErrorBanner({ message, onRetry, onDismiss }) {
  if (!message) return null

  return (
    <div className="alert-error" role="alert">
      <AlertCircle size={20} style={{ flexShrink: 0, marginTop: '2px' }} />
      <div style={{ flex: 1 }}>
        <strong style={{ display: 'block', marginBottom: '0.2rem' }}>Processing Error</strong>
        <span style={{ fontSize: '0.92rem' }}>{message}</span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        {onRetry && (
          <button
            type="button"
            className="btn-secondary"
            onClick={onRetry}
            style={{ padding: '0.35rem 0.75rem', fontSize: '0.8rem' }}
          >
            <RefreshCw size={13} />
            <span>Retry</span>
          </button>
        )}
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            style={{ background: 'transparent', border: 'none', color: '#fca5a5', cursor: 'pointer', padding: '0.2rem' }}
            aria-label="Dismiss error"
          >
            <X size={18} />
          </button>
        )}
      </div>
    </div>
  )
}
