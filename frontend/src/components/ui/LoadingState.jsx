import React from 'react'

export function LoadingState({ message = 'Loading...', submessage = null }) {
  return (
    <div className="loading-state-container" role="status" aria-live="polite">
      <div className="loading-spinner-ring" aria-hidden="true" />
      <div className="loading-state-title">{message}</div>
      {submessage && <div className="loading-state-submessage">{submessage}</div>}
    </div>
  )
}
