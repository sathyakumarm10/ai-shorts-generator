import React from 'react'
import { CheckCircle2, Sparkles, RefreshCw } from 'lucide-react'
import { ShortCard } from './ShortCard'

export function ResultsGrid({ result, onReset }) {
  const shorts = result?.generated_shorts || []

  return (
    <section className="results-section" aria-label="Generated Shorts Results">
      <div className="results-header">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#10b981', fontWeight: 600, fontSize: '0.9rem', marginBottom: '0.3rem' }}>
            <CheckCircle2 size={18} />
            <span>Generation Complete</span>
          </div>
          <h2 style={{ fontSize: '1.75rem' }}>Your Generated Shorts</h2>
        </div>

        <button
          type="button"
          className="btn-secondary"
          onClick={onReset}
          style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <RefreshCw size={15} />
          <span>Create More Shorts</span>
        </button>
      </div>

      {shorts.length === 0 ? (
        <div className="glass-card" style={{ textAlign: 'center', padding: '3rem 1.5rem' }}>
          <Sparkles size={36} color="var(--text-muted)" style={{ margin: '0 auto 1rem' }} />
          <h3 style={{ marginBottom: '0.5rem' }}>No highlights found</h3>
          <p style={{ color: 'var(--text-secondary)', maxWidth: '480px', margin: '0 auto 1.5rem' }}>
            The speech transcript did not meet highlight threshold criteria for the requested duration.
          </p>
          <button type="button" className="btn-primary" onClick={onReset} style={{ maxWidth: '240px', margin: '0 auto' }}>
            Try With Another Video
          </button>
        </div>
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
