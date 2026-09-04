import React, { useState, useRef, useMemo } from 'react'
import { CheckCircle2, Sparkles, RefreshCw, AlertCircle, LayoutGrid, Sliders } from 'lucide-react'
import { ShortCard } from './ShortCard'
import { EmptyState } from '../ui/EmptyState'
import { VideoWorkspacePreview } from './VideoWorkspacePreview'
import { ShortNavigation } from './ShortNavigation'
import { SubtitleEditor } from './SubtitleEditor'
import { SubtitleStylePicker } from './SubtitleStylePicker'
import { findActiveSegment } from '../../utils/subtitleValidation'

export function ShortGrid({ result, jobId, onReset }) {
  const initialShorts = useMemo(() => result?.generated_shorts || [], [result])
  const candidates = result?.candidates || []
  const skippedCount = Math.max(0, candidates.length - initialShorts.length)

  // Local state for modified shorts (enabling subtitle editing & state updates)
  const [shorts, setShorts] = useState(initialShorts)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [currentTime, setCurrentTime] = useState(0)
  const [captionStyle, setCaptionStyle] = useState('default')
  const [viewMode, setViewMode] = useState('workspace') // 'workspace' | 'grid'

  const videoRef = useRef(null)

  // Sync state if initialShorts reference completely changes
  React.useEffect(() => {
    setShorts(initialShorts)
    setSelectedIndex(0)
    setCurrentTime(0)
  }, [initialShorts])

  // Active Short
  const activeShort = shorts[selectedIndex] || shorts[0] || null

  // Successfully completed count
  const completedCount = shorts.filter((s) => s.status !== 'failed').length
  const failedCount = shorts.filter((s) => s.status === 'failed').length

  // Caption segments & active segment detection
  const captionSegments = activeShort?.caption_track?.segments || []
  const { activeSegment, activeIndex } = findActiveSegment(captionSegments, currentTime)

  // Handlers
  const handleSelectShort = (index) => {
    if (index >= 0 && index < shorts.length) {
      setSelectedIndex(index)
      setCurrentTime(0)
      if (videoRef.current) {
        videoRef.current.currentTime = 0
      }
    }
  }

  const handleSeek = (seconds) => {
    if (videoRef.current && !isNaN(seconds)) {
      videoRef.current.currentTime = seconds
      setCurrentTime(seconds)
    }
  }

  const handleSaveTrack = async (updatedTrack) => {
    // Update active short in local state
    setShorts((prev) => {
      const next = [...prev]
      if (next[selectedIndex]) {
        next[selectedIndex] = {
          ...next[selectedIndex],
          caption_track: updatedTrack,
        }
      }
      return next
    })
  }

  return (
    <section className="results-section results-workspace" aria-label="Generated Shorts Results">
      {/* Workspace Header */}
      <div className="results-header">
        <div>
          <div className="results-success-badge">
            <CheckCircle2 size={18} />
            <span>Generation Complete</span>
          </div>
          <h2 className="results-title">Your Generated Shorts</h2>
          <p className="results-subtitle">
            {shorts.length} {shorts.length === 1 ? 'Short' : 'Shorts'} created and formatted for vertical viewing.
            {jobId && (
              <span style={{ marginLeft: '0.5rem', color: 'var(--text-muted)' }}>
                [Job ID: {jobId.slice(0, 8)}]
              </span>
            )}
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          {/* View Mode Toggle: Workspace vs All Grid */}
          {shorts.length > 0 && (
            <div className="view-mode-toggle" role="group" aria-label="View Mode">
              <button
                type="button"
                className={`toggle-btn ${viewMode === 'workspace' ? 'active' : ''}`}
                onClick={() => setViewMode('workspace')}
                title="Workspace Preview & Editor"
              >
                <Sliders size={14} />
                <span>Workspace</span>
              </button>
              <button
                type="button"
                className={`toggle-btn ${viewMode === 'grid' ? 'active' : ''}`}
                onClick={() => setViewMode('grid')}
                title="Grid View"
              >
                <LayoutGrid size={14} />
                <span>Grid View</span>
              </button>
            </div>
          )}

          <button
            type="button"
            className="btn-secondary btn-reset"
            onClick={onReset}
          >
            <RefreshCw size={15} />
            <span>Create More Shorts</span>
          </button>
        </div>
      </div>

      {/* Generation Summary Badges */}
      {shorts.length > 0 && (
        <div className="workspace-status-summary">
          <span className="summary-chip chip-success">
            <strong>{completedCount}</strong> Ready to Export
          </span>
          {failedCount > 0 && (
            <span className="summary-chip chip-warning">
              <strong>{failedCount}</strong> Failed Render
            </span>
          )}
          {skippedCount > 0 && (
            <span className="summary-chip chip-neutral">
              <strong>{skippedCount}</strong> Skipped Candidates
            </span>
          )}
        </div>
      )}

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
        <>
          {/* 1. Results Workspace: Active Short Interactive Studio */}
          {activeShort && (
            <div className="workspace-container">
              {/* Short Navigation Bar (Previous, Current of Total, Next, Quick Jump) */}
              <ShortNavigation
                totalCount={shorts.length}
                currentIndex={selectedIndex}
                onSelectIndex={handleSelectShort}
                shorts={shorts}
              />

              {/* 2-Column Responsive Workspace: Video on Left, Subtitles on Right */}
              <div className="workspace-studio-layout">
                {/* Left Column: Large Video Preview with Live Subtitles */}
                <div className="workspace-preview-col">
                  <VideoWorkspacePreview
                    short={activeShort}
                    activeCaptionText={activeSegment?.text}
                    captionStyle={captionStyle}
                    onTimeUpdate={(t) => setCurrentTime(t)}
                    videoRef={videoRef}
                  />
                </div>

                {/* Right Column: Subtitle Styles & Subtitle Editor */}
                <div className="workspace-editor-col">
                  <SubtitleStylePicker
                    currentStyle={captionStyle}
                    onSelectStyle={setCaptionStyle}
                  />

                  <SubtitleEditor
                    captionTrack={activeShort.caption_track}
                    duration={activeShort.candidate?.duration_seconds}
                    activeIndex={activeIndex}
                    onSeek={handleSeek}
                    onSaveTrack={handleSaveTrack}
                  />
                </div>
              </div>
            </div>
          )}

          {/* 2. All Generated Shorts Overview (Always present or toggled for direct access) */}
          <div className="all-shorts-section">
            <div className="all-shorts-header">
              <h3 className="section-title">All Generated Clips</h3>
              <span className="section-subtitle">
                Select any Short to inspect, edit its subtitles, or download.
              </span>
            </div>

            <div className="results-grid">
              {shorts.map((short, idx) => (
                <ShortCard
                  key={`${jobId || 'job'}-${short.index ?? idx}`}
                  short={short}
                  isSelected={idx === selectedIndex}
                  onSelect={() => handleSelectShort(idx)}
                />
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  )
}
