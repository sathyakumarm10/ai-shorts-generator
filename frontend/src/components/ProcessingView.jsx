import React from 'react'
import {
  Clock,
  DownloadCloud,
  FileSearch,
  Headphones,
  Sparkles,
  Scissors,
  Smartphone,
  Subtitles,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react'

const PIPELINE_STAGES = [
  { key: 'queued', label: 'Queued in background', icon: Clock, targetPercent: 0 },
  { key: 'ingesting', label: 'Ingesting source video', icon: DownloadCloud, targetPercent: 10 },
  { key: 'extracting_metadata', label: 'Extracting video metadata', icon: FileSearch, targetPercent: 20 },
  { key: 'transcribing', label: 'Transcribing speech with AI', icon: Headphones, targetPercent: 35 },
  { key: 'finding_highlights', label: 'Detecting highlight moments', icon: Sparkles, targetPercent: 50 },
  { key: 'generating_clips', label: 'Rendering trimmed clips', icon: Scissors, targetPercent: 65 },
  { key: 'converting_vertical', label: 'Converting to 9:16 vertical video', icon: Smartphone, targetPercent: 80 },
  { key: 'adding_captions', label: 'Burning styled synchronized captions', icon: Subtitles, targetPercent: 90 },
  { key: 'completed', label: 'Shorts Generation Complete', icon: CheckCircle2, targetPercent: 100 },
]

export function ProcessingView({ job, onCancel }) {
  const currentStatus = (job?.status || 'queued').toLowerCase()
  const progressPercent = Math.min(100, Math.max(0, job?.progress_percent || 0))
  const message = job?.message || 'Processing your video...'

  // Find active stage index
  const activeStageIndex = PIPELINE_STAGES.findIndex(s => s.key === currentStatus)
  const effectiveIndex = activeStageIndex === -1 ? 0 : activeStageIndex

  return (
    <div className="glass-card progress-card" role="region" aria-label="Job Processing Status">
      <div className="progress-header">
        <div className="progress-spinner-ring" aria-hidden="true" />
        <h2 style={{ fontSize: '1.8rem', marginBottom: '0.5rem' }}>Creating Your Shorts</h2>
        <p style={{ color: 'var(--text-secondary)' }}>{message}</p>
      </div>

      <div className="progress-bar-container" aria-label={`Overall progress: ${progressPercent}%`}>
        <div
          className="progress-bar-fill"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1.5rem', fontSize: '0.9rem', color: 'var(--text-muted)' }}>
        <span>Stage {effectiveIndex + 1} of {PIPELINE_STAGES.length}</span>
        <span style={{ fontWeight: 700, color: 'var(--accent-primary)' }}>{Math.round(progressPercent)}%</span>
      </div>

      <div className="stage-stepper">
        {PIPELINE_STAGES.map((stage, idx) => {
          const Icon = stage.icon
          let stepClass = 'pending'

          if (idx < effectiveIndex) {
            stepClass = 'completed'
          } else if (idx === effectiveIndex) {
            stepClass = 'active'
          }

          return (
            <div key={stage.key} className={`stage-step ${stepClass}`}>
              <div className="stage-icon">
                {stepClass === 'completed' ? (
                  <CheckCircle2 size={16} />
                ) : (
                  <Icon size={15} />
                )}
              </div>

              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: '0.92rem' }}>
                  {stage.label}
                </div>
              </div>

              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                {stage.targetPercent}%
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
