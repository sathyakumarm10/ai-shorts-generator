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

export function GenerationProgress({ job, onCancel }) {
  const currentStatus = (job?.status || 'queued').toLowerCase()
  const progressPercent = Math.min(100, Math.max(0, job?.progress_percent || 0))
  const message = job?.message || 'Processing your video...'

  const activeStageIndex = PIPELINE_STAGES.findIndex((s) => s.key === currentStatus)
  const effectiveIndex = activeStageIndex === -1 ? 0 : activeStageIndex

  // Determine counts if available
  const requestedCount = job?.request?.number_of_clips || 10
  const generatedShorts = job?.result?.generated_shorts?.length || 0

  return (
    <div className="glass-card progress-card" role="region" aria-label="Job Processing Status">
      <div className="progress-header">
        <div className="progress-spinner-ring" aria-hidden="true" />
        <h2 className="progress-title">Creating Your Shorts</h2>
        <p className="progress-message">{message}</p>
      </div>

      {/* Progress Meta Chips */}
      <div className="progress-chips-row">
        <div className="progress-chip">
          <span className="chip-label">Target Shorts:</span>
          <span className="chip-val">{requestedCount}</span>
        </div>
        {generatedShorts > 0 && (
          <div className="progress-chip">
            <span className="chip-label">Rendered:</span>
            <span className="chip-val">{generatedShorts}</span>
          </div>
        )}
        <div className="progress-chip">
          <span className="chip-label">Status:</span>
          <span className="chip-val chip-status">{currentStatus}</span>
        </div>
      </div>

      <div className="progress-bar-container" aria-label={`Overall progress: ${progressPercent}%`}>
        <div
          className="progress-bar-fill"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      <div className="progress-meta-row">
        <span>Stage {effectiveIndex + 1} of {PIPELINE_STAGES.length}</span>
        <span className="progress-percentage-val">{Math.round(progressPercent)}%</span>
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

              <div className="stage-text-container">
                <div className="stage-label-text">
                  {stage.label}
                </div>
              </div>

              <div className="stage-percent-tag">
                {stage.targetPercent}%
              </div>
            </div>
          )
        })}
      </div>

      {onCancel && (
        <div style={{ textAlign: 'center', marginTop: '1.5rem' }}>
          <button
            type="button"
            className="btn-secondary"
            onClick={onCancel}
            style={{ fontSize: '0.85rem' }}
          >
            Cancel or Start Over
          </button>
        </div>
      )}
    </div>
  )
}
