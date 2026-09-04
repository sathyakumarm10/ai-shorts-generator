import React from 'react'
import { Sparkles, PlusCircle, Film, CheckCircle2, Clock, Play } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { EmptyState } from '../components/ui/EmptyState'

export function DashboardPage({
  onNavigateCreate,
  history = [],
  onSelectJob,
  currentJob,
}) {
  const completedJobs = history.filter((j) => j.status === 'completed')
  const totalShorts = completedJobs.reduce((acc, job) => {
    return acc + (job.result?.generated_shorts?.length || 0)
  }, 0)

  return (
    <div className="dashboard-page">
      <PageHeader
        badge={
          <span className="badge-pill">
            <Sparkles size={13} />
            <span>AI Multi-Short Generation Pipeline</span>
          </span>
        }
        title="Dashboard"
        subtitle="Turn podcasts, lectures, and landscape videos into viral 9:16 Shorts with automated smart framing and synchronized subtitles."
        actions={
          <button
            type="button"
            className="btn-primary"
            onClick={onNavigateCreate}
          >
            <PlusCircle size={16} />
            <span>Create New Short</span>
          </button>
        }
      />

      {/* Metrics Row */}
      <section className="metrics-grid" aria-label="Generation Statistics">
        <div className="metric-card">
          <div className="metric-icon-wrap">
            <Film size={20} />
          </div>
          <div className="metric-details">
            <span className="metric-value">{history.length}</span>
            <span className="metric-label">Total Jobs Processed</span>
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-icon-wrap">
            <CheckCircle2 size={20} />
          </div>
          <div className="metric-details">
            <span className="metric-value">{completedJobs.length}</span>
            <span className="metric-label">Completed Jobs</span>
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-icon-wrap">
            <Sparkles size={20} />
          </div>
          <div className="metric-details">
            <span className="metric-value">{totalShorts}</span>
            <span className="metric-label">Total Shorts Generated</span>
          </div>
        </div>
      </section>

      {/* Recent Generation Projects */}
      <section className="dashboard-recent-section" aria-label="Recent Projects">
        <div className="section-header-row">
          <h2 className="section-title">Recent Generation Jobs</h2>
          {history.length > 0 && (
            <span className="section-count">{history.length} jobs found</span>
          )}
        </div>

        {history.length === 0 ? (
          <EmptyState
            icon={Film}
            title="No generation jobs yet"
            description="Upload a source video to generate up to 15 synchronized vertical shorts with AI highlight detection."
            actionLabel="Create Your First Short"
            onAction={onNavigateCreate}
          />
        ) : (
          <div className="recent-jobs-list">
            {history.slice(0, 6).map((job) => {
              const isCompleted = job.status === 'completed'
              const isFailed = job.status === 'failed'
              const shortsCount = job.result?.generated_shorts?.length || 0

              return (
                <div
                  key={job.job_id}
                  className="recent-job-item"
                  onClick={() => onSelectJob(job)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && onSelectJob(job)}
                >
                  <div className="job-item-main">
                    <div className="job-item-title">
                      {job.sourceName || `Job ${job.job_id.slice(0, 8)}`}
                    </div>
                    <div className="job-item-meta">
                      <span className="job-date">
                        <Clock size={12} />
                        {new Date(job.created_at || Date.now()).toLocaleDateString(undefined, {
                          month: 'short',
                          day: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </span>
                      {shortsCount > 0 && (
                        <span className="job-shorts-count">
                          {shortsCount} {shortsCount === 1 ? 'short' : 'shorts'}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="job-item-actions">
                    <span
                      className={`job-status-tag ${
                        isCompleted ? 'status-completed' : isFailed ? 'status-failed' : 'status-processing'
                      }`}
                    >
                      {job.status}
                    </span>
                    <button
                      type="button"
                      className="btn-view-job"
                      aria-label="View generation results"
                    >
                      <Play size={14} />
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}
