import React, { useState } from 'react'
import { Film, Sparkles, Clock, CheckCircle2 } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { EmptyState } from '../components/ui/EmptyState'
import { ShortCard } from '../components/results/ShortCard'

export function MyShortsPage({
  history = [],
  onSelectJob,
  onNavigateCreate,
}) {
  const [selectedFilter, setSelectedFilter] = useState('all') // 'all' | 'completed'

  // Extract all shorts across completed history jobs
  const allShorts = history.flatMap((job) => {
    const shorts = job.result?.generated_shorts || []
    return shorts.map((short) => ({
      ...short,
      parentJobId: job.job_id,
      sourceName: job.sourceName || 'Video',
    }))
  })

  return (
    <div className="my-shorts-page">
      <PageHeader
        title="My Generated Shorts"
        subtitle="Browse, preview, and download all short-form videos created by the pipeline."
      />

      {/* Filter Chips */}
      <div className="filter-chips-row">
        <button
          type="button"
          className={`filter-chip ${selectedFilter === 'all' ? 'active' : ''}`}
          onClick={() => setSelectedFilter('all')}
        >
          All Shorts ({allShorts.length})
        </button>
        <button
          type="button"
          className={`filter-chip ${selectedFilter === 'completed' ? 'active' : ''}`}
          onClick={() => setSelectedFilter('completed')}
        >
          Past Jobs ({history.length})
        </button>
      </div>

      {selectedFilter === 'all' ? (
        allShorts.length === 0 ? (
          <EmptyState
            icon={Film}
            title="No shorts generated yet"
            description="When your generation jobs complete, all individual vertical clips with synchronized subtitles will appear here."
            actionLabel="Generate Shorts Now"
            onAction={onNavigateCreate}
          />
        ) : (
          <div className="results-grid">
            {allShorts.map((short, idx) => (
              <ShortCard key={`${short.parentJobId}-${short.index || idx}`} short={short} />
            ))}
          </div>
        )
      ) : (
        /* Jobs view */
        history.length === 0 ? (
          <EmptyState
            icon={Film}
            title="No past jobs found"
            description="Start a generation job to see processing history."
            actionLabel="Start Job"
            onAction={onNavigateCreate}
          />
        ) : (
          <div className="recent-jobs-list">
            {history.map((job) => (
              <div
                key={job.job_id}
                className="recent-job-item"
                onClick={() => onSelectJob(job)}
                role="button"
                tabIndex={0}
              >
                <div className="job-item-main">
                  <div className="job-item-title">{job.sourceName || `Job ${job.job_id}`}</div>
                  <div className="job-item-meta">
                    <span className="job-date">
                      <Clock size={12} />
                      {new Date(job.created_at || Date.now()).toLocaleString()}
                    </span>
                    <span className="job-shorts-count">
                      {job.result?.generated_shorts?.length || 0} shorts
                    </span>
                  </div>
                </div>
                <span className={`job-status-tag status-${job.status}`}>
                  {job.status}
                </span>
              </div>
            ))}
          </div>
        )
      )}
    </div>
  )
}
