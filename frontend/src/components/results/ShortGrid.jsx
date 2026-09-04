import React from 'react'
import { CheckCircle2, Sparkles, RefreshCw, AlertCircle } from 'lucide-react'
import { ShortCard } from './ShortCard'
import { EmptyState } from '../ui/EmptyState'

export function ShortGrid({ result, jobId, onReset }) {
  const shorts = result?.generated_shorts || []
  const candidates = result?.candidates || []
  const skippedCount = Math.max(0, candidates.length - shorts.length)

  return (
    <section className="results-section" aria-label="Generated Shorts Results">
      <div className="results-header">
        <div>
          <div className="results-success-badge">
            <CheckCircle2 size={18} />
            <span>Generation Complete</span>
          </div>
          <h2 className="results-title">Your Generated Shorts</h2>
          <p className="results-subtitle">
            {shorts.length} {shorts.length === 1 ? 'Short' : 'Shorts'} created and formatted for vertical viewing.
            {jobId && <span style={{ marginLeft: '0.5rem', color: 'var(--text-muted)' }}>[Job ID: {jobId.slice(0, 8)}]</span>}
          </p>
        </div>

        <button
          type="button"
          className="btn-secondary btn-reset"
          onClick={onReset}
        >
          <RefreshCw size={15} />
          <span>Create More Shorts</span>
        </button>
      </div>

      {/* Non-blocking Notice if some candidate highlights were skipped */}
      {skippedCount > 0 && shorts.length > 0 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.6rem',
            padding: '0.75rem 1rem',
            marginBottom: '1.5rem',
            background: '#F9FAFB',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.82rem',
            color: 'var(--text-secondary)',
          }}
        >
          <AlertCircle size={16} color="var(--text-muted)" />
          <span>
            {skippedCount} highlight {skippedCount === 1 ? 'candidate' : 'candidates'} lacked sufficient audio/visual clarity or failed rendering and {skippedCount === 1 ? 'was' : 'were'} safely skipped. The remaining {shorts.length} shorts are ready below.
          </span>
        </div>
      )}

      {shorts.length === 0 ? (
        <EmptyState
          icon={Sparkles}
          title="No highlights found"
          description="The speech transcript did not meet highlight threshold criteria for the requested duration."
          actionLabel="Try With Another Video"
          onAction={onReset}
        />
      ) : (
        <div className="results-grid">
          {shorts.map((short) => (
            <ShortCard key={`${jobId || 'job'}-${short.index}`} short={short} />
          ))}
        </div>
      )}
    </section>
  )
}
