import React from 'react'
import { CheckCircle2, Sparkles, RefreshCw } from 'lucide-react'
import { ShortCard } from './ShortCard'
import { EmptyState } from '../ui/EmptyState'

export function ShortGrid({ result, onReset }) {
  const shorts = result?.generated_shorts || []

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
            <ShortCard key={short.index} short={short} />
          ))}
        </div>
      )}
    </section>
  )
}
