import React from 'react'
import { X, Clock, CheckCircle2, AlertCircle, Film } from 'lucide-react'

export function JobHistoryModal({ isOpen, onClose, history, onSelectJob, onClearHistory }) {
  if (!isOpen) return null

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true" aria-label="Job History">
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
          <h2 style={{ fontSize: '1.4rem' }}>Past Projects & Jobs</h2>
          <button
            type="button"
            onClick={onClose}
            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
            aria-label="Close modal"
          >
            <X size={20} />
          </button>
        </div>

        {history.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '2rem 1rem', color: 'var(--text-muted)' }}>
            <Film size={32} style={{ margin: '0 auto 0.75rem', opacity: 0.5 }} />
            <p>No previous generation jobs saved yet.</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
            {history.map((item) => {
              const isCompleted = item.status === 'completed'
              const isFailed = item.status === 'failed'

              return (
                <div
                  key={item.job_id}
                  style={{
                    padding: '1rem',
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-sm)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                  onClick={() => {
                    onSelectJob(item)
                    onClose()
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '0.95rem', marginBottom: '0.2rem' }}>
                      {item.sourceName || `Job ${item.job_id.slice(0, 8)}`}
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                      <Clock size={12} />
                      <span>{new Date(item.created_at).toLocaleString()}</span>
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span
                      style={{
                        padding: '0.25rem 0.6rem',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '0.72rem',
                        fontWeight: 600,
                        textTransform: 'uppercase',
                        background: isCompleted ? 'rgba(16, 185, 129, 0.12)' : isFailed ? 'rgba(239, 68, 68, 0.12)' : 'rgba(255, 255, 255, 0.08)',
                        color: isCompleted ? '#10B981' : isFailed ? '#EF4444' : '#FFFFFF',
                        border: `1px solid ${isCompleted ? 'rgba(16, 185, 129, 0.25)' : isFailed ? 'rgba(239, 68, 68, 0.25)' : '#333333'}`,
                      }}
                    >
                      {item.status}
                    </span>
                  </div>
                </div>
              )
            })}

            <button
              type="button"
              className="btn-secondary"
              onClick={onClearHistory}
              style={{ marginTop: '1rem', alignSelf: 'flex-start', fontSize: '0.85rem' }}
            >
              Clear Project History
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
