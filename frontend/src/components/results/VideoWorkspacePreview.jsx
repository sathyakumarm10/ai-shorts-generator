import React, { useState, useRef, useEffect } from 'react'
import {
  Download,
  AlertCircle,
  Clock,
  Sparkles,
  Cpu,
  Subtitles,
  Copy,
  Check,
  Film,
} from 'lucide-react'
import { getMediaUrl } from '../../api/client'

export function VideoWorkspacePreview({
  short,
  activeCaptionText,
  captionStyle = 'default',
  onTimeUpdate,
  videoRef,
}) {
  const [videoError, setVideoError] = useState(false)
  const [duration, setDuration] = useState(null)
  const [copied, setCopied] = useState(false)

  // Reset video error when short changes
  useEffect(() => {
    setVideoError(false)
    setDuration(null)
  }, [short?.index, short?.final_file_path])

  if (!short) {
    return (
      <div className="video-workspace-placeholder">
        <Film size={36} />
        <p>No Short Selected</p>
      </div>
    )
  }

  const isFailed = short.status === 'failed'
  const rawPath = short.final_file_path || short.vertical_clip_path
  const videoSrc = rawPath ? getMediaUrl(rawPath) : ''
  const candidate = short.candidate || {}
  const score =
    candidate.score?.overall != null
      ? Math.round(candidate.score.overall * 100)
      : null
  const isAI = candidate.source_type === 'ai'
  const effectiveDuration = duration || candidate.duration_seconds

  const handleCopyPath = async () => {
    try {
      await navigator.clipboard.writeText(rawPath || '')
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard fallback
    }
  }

  return (
    <div className="video-workspace-preview" aria-label={`Preview of Short #${short.index}`}>
      {/* 9:16 Vertical Video Player Container */}
      <div className="workspace-video-wrapper">
        {isFailed || videoError || !videoSrc ? (
          <div className="workspace-video-fallback" role="alert">
            <AlertCircle size={36} />
            <p className="fallback-title">
              {isFailed ? 'Short Video Generation Failed' : 'Video preview unavailable'}
            </p>
            <p className="fallback-desc">
              {short.error_message ||
                'The video file could not be loaded or rendered for this segment.'}
            </p>
            {videoSrc && !isFailed && (
              <a
                href={videoSrc}
                download={`short_${short.index}.mp4`}
                className="btn-download"
                style={{ marginTop: '0.5rem', width: 'auto' }}
              >
                <Download size={14} />
                <span>Try Direct Download</span>
              </a>
            )}
          </div>
        ) : (
          <div className="workspace-video-inner">
            <video
              ref={videoRef}
              className="workspace-video-element"
              src={videoSrc}
              controls
              playsInline
              preload="metadata"
              onTimeUpdate={(e) => {
                if (onTimeUpdate) {
                  onTimeUpdate(e.target.currentTime)
                }
              }}
              onLoadedMetadata={(e) => {
                if (e.target.duration && !isNaN(e.target.duration)) {
                  setDuration(e.target.duration)
                }
              }}
              onError={() => setVideoError(true)}
            />

            {/* Live Subtitle Overlay */}
            {activeCaptionText && (
              <div
                className={`live-caption-overlay preset-${(captionStyle || 'default').toLowerCase()}`}
                aria-live="polite"
              >
                <span className="live-caption-text">{activeCaptionText}</span>
              </div>
            )}
          </div>
        )}

        {/* Active Short Badge & Score */}
        <div className="workspace-short-badge">Preview #{short.index}</div>
        {score != null && (
          <div className="workspace-score-badge">
            <Sparkles size={12} style={{ display: 'inline', marginRight: '3px' }} />
            {score}% Potential
          </div>
        )}
      </div>

      {/* Metadata & Actions Bar below Video */}
      <div className="workspace-meta-bar">
        <div className="meta-left">
          {candidate.title && (
            <h4 className="workspace-short-title">Active Short: {candidate.title}</h4>
          )}

          <div className="workspace-tag-row">
            <span className="workspace-tag">
              <Clock size={12} />
              {effectiveDuration != null ? `${effectiveDuration.toFixed(1)}s` : 'Duration'}
              {candidate.start_seconds != null &&
                ` (${candidate.start_seconds.toFixed(1)}s – ${candidate.end_seconds?.toFixed(1)}s)`}
            </span>

            <span className={`workspace-tag ${isAI ? 'tag-ai' : 'tag-heuristic'}`}>
              {isAI ? <Sparkles size={11} /> : <Cpu size={11} />}
              {isAI ? 'AI Highlight' : 'Heuristic'}
            </span>

            {short.framing_type === 'smart_framing' && (
              <span className="workspace-tag">Smart Framing</span>
            )}

            <span className="workspace-tag">
              <Subtitles size={11} />
              {short.caption_track?.segments?.length
                ? `${short.caption_track.segments.length} Subtitles`
                : 'No Captions'}
            </span>
          </div>

          {candidate.viral_hook && (
            <p className="workspace-hook-text">
              Hook: &ldquo;{candidate.viral_hook}&rdquo;
            </p>
          )}
        </div>

        <div className="meta-actions">
          {videoSrc && !isFailed && (
            <a
              href={videoSrc}
              download={`short_${short.index}.mp4`}
              className="btn-download"
              aria-label={`Download active Short #${short.index}`}
            >
              <Download size={15} />
              <span>Export Short</span>
            </a>
          )}

          {rawPath && (
            <button
              type="button"
              className="btn-secondary"
              onClick={handleCopyPath}
              title="Copy file path"
              aria-label="Copy file path"
            >
              {copied ? <Check size={15} /> : <Copy size={15} />}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
