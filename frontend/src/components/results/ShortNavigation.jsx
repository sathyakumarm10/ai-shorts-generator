import React from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

export function ShortNavigation({
  totalCount,
  currentIndex,
  onSelectIndex,
  shorts = [],
}) {
  const hasPrevious = currentIndex > 0
  const hasNext = currentIndex < totalCount - 1
  const displayCurrent = totalCount > 0 ? currentIndex + 1 : 0

  return (
    <div className="short-navigation" aria-label="Short Navigation Controls">
      <div className="nav-controls-main">
        <button
          type="button"
          className="btn-nav btn-prev"
          onClick={() => hasPrevious && onSelectIndex(currentIndex - 1)}
          disabled={!hasPrevious}
          aria-label="Previous Short"
        >
          <ChevronLeft size={16} />
          <span>Previous</span>
        </button>

        <span className="nav-indicator-text" aria-live="polite">
          Short {displayCurrent} of {totalCount}
        </span>

        <button
          type="button"
          className="btn-nav btn-next"
          onClick={() => hasNext && onSelectIndex(currentIndex + 1)}
          disabled={!hasNext}
          aria-label="Next Short"
        >
          <span>Next</span>
          <ChevronRight size={16} />
        </button>
      </div>

      {/* Quick Jump Selector Pills */}
      {totalCount > 1 && (
        <div className="nav-pills-row" role="tablist" aria-label="Select Short">
          {shorts.map((s, idx) => {
            const isSelected = idx === currentIndex
            const isFailed = s.status === 'failed'

            return (
              <button
                key={s.index ?? idx}
                type="button"
                role="tab"
                aria-selected={isSelected}
                className={`nav-pill-btn ${isSelected ? 'active' : ''} ${isFailed ? 'pill-failed' : ''}`}
                onClick={() => onSelectIndex(idx)}
                title={`Jump to Short #${s.index ?? idx + 1}${isFailed ? ' (Failed)' : ''}`}
              >
                #{s.index ?? idx + 1}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
