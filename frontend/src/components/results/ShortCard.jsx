import React, { useState, useRef } from 'react'
import {
  Download,
  Sparkles,
  Clock,
  Check,
  Copy,
  Flame,
  Cpu,
  Subtitles,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  Maximize2,
} from 'lucide-react'
import { getMediaUrl } from '../../api/client'

export function ShortCard({ short, onSelect, isSelected = false }) {
  const [copied, setCopied] = useState(false)
  const [showSubtitles, setShowSubtitles] = useState(false)
  const [videoError, setVideoError] = useState(false)
  const [duration, setDuration] = useState(null)
  const videoRef = useRef(null)

  const isFailed = short.status === 'failed'
  const rawPath = short.final_file_path || short.vertical_clip_path
  const videoSrc = rawPath ? getMediaUrl(rawPath) : ''
  const candidate = short.candidate || {}
  const score =
    candidate.score?.overall != null
      ? Math.round(candidate.score.overall * 100)
      : null

  const isAI = candidate.source_type === 'ai'
  const title = candidate.title
  const hook = candidate.viral_hook
  const hasBurnedCaptions = Boolean(short.captioned_clip_path)
  const captionTrack = short.caption_track
  const captionSegments = captionTrack?.segments || []
  const hasCaptions = Boolean(hasBurnedCaptions || captionSegments.length > 0)

  const handleCopyPath = async (e) => {
    e.stopPropagation()
    try {
      await navigator.clipboard.writeText(rawPath || '')
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback
    }
  }

  const effectiveDuration = duration || candidate.duration_seconds

  return (
    <article
      className={`short-card ${isSelected ? 'short-card-active' : ''} ${isFailed ? 'short-card-failed' : ''}`}
      aria-label={`Short #${short.index}`}
    >
      <div className="short-video-wrapper">
        {isFailed || videoError || !videoSrc ? (
          <div
            style={{
              width: '100%',
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '1.5rem',
              textAlign: 'center',
              background: '#0D0D0D',
              color: '#888888',
              gap: '0.6rem',
            }}
          >
            <AlertCircle size={32} color="#777777" />
            <span style={{ fontSize: '0.85rem', color: '#E5E5E5', fontWeight: 600 }}>
              {isFailed ? 'Short Generation Failed' : 'Video preview unavailable'}
            </span>
            <span style={{ fontSize: '0.75rem', color: '#777777' }}>
              {short.error_message || 'Download below to view the rendered MP4 file.'}
            </span>
          </div>
        ) : (
          <video
            ref={videoRef}
            className="short-video"
            src={videoSrc}
            controls
            preload="metadata"
            playsInline
            onLoadedMetadata={(e) => {
              if (e.target.duration && !isNaN(e.target.duration)) {
                setDuration(e.target.duration)
              }
            }}
            onError={() => setVideoError(true)}
          />
        )}
        <div className="short-badge">Short #{short.index}</div>
        {score != null && (
          <div className="short-score-badge">
            <Sparkles size={12} style={{ display: 'inline', marginRight: '3px' }} />
            {score}% Viral Score
          </div>
        )}

        {isFailed && (
          <div className="short-failed-badge">
            Failed
          </div>
        )}
      </div>

      <div className="short-details">
        <div className="short-meta-header">
          <span className="short-duration-text">
            <Clock size={13} />
            {candidate.start_seconds != null ? `${candidate.start_seconds.toFixed(1)}s` : '0.0s'} &ndash; {candidate.end_seconds != null ? `${candidate.end_seconds.toFixed(1)}s` : ''}
            {effectiveDuration != null && ` (${effectiveDuration.toFixed(1)}s)`}
          </span>

          <div className="short-tags-cluster">
            <span className={`short-source-tag ${isAI ? 'tag-ai' : 'tag-heuristic'}`}>
              {isAI ? <Sparkles size={11} /> : <Cpu size={11} />}
              {isAI ? 'AI Pick' : 'Heuristic'}
            </span>

            {short.framing_type === 'smart_framing' && (
              <span className="short-framing-tag">
                Smart Framing
              </span>
            )}

            {short.is_karaoke && (
              <span className="short-fx-tag">
                Karaoke FX
              </span>
            )}

            <span className={`short-caption-tag ${hasCaptions ? 'caption-active' : 'caption-none'}`}>
              <Subtitles size={11} />
              {hasBurnedCaptions ? `${short.caption_preset || 'Dynamic'} Captions` : (hasCaptions ? 'Synchronized Track' : 'No Captions')}
            </span>
          </div>
        </div>

        {title && (
          <h4 className="short-title">
            {title}
          </h4>
        )}

        {hook && (
          <p className="short-hook-text">
            <Flame size={13} />
            <span>&ldquo;{hook}&rdquo;</span>
          </p>
        )}

        {/* Highlight Transcript Window for this Short */}
        {candidate.text && (
          <p className="short-transcript-snippet" title={candidate.text}>
            &ldquo;{candidate.text}&rdquo;
          </p>
        )}

        {/* Per-Short Subtitle Track Segments Inspector */}
        {captionSegments.length > 0 && (
          <div style={{ marginTop: '0.25rem', marginBottom: '0.5rem' }}>
            <button
              type="button"
              onClick={() => setShowSubtitles(!showSubtitles)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
                background: 'transparent',
                border: 'none',
                color: 'var(--text-secondary)',
                fontSize: '0.78rem',
                fontWeight: 600,
                cursor: 'pointer',
                padding: '0.2rem 0',
              }}
            >
              <Subtitles size={13} />
              <span>{showSubtitles ? 'Hide Subtitles' : `View Synchronized Subtitles (${captionSegments.length})`}</span>
              {showSubtitles ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>

            {showSubtitles && (
              <div
                style={{
                  maxHeight: '140px',
                  overflowY: 'auto',
                  marginTop: '0.4rem',
                  padding: '0.5rem 0.65rem',
                  background: '#F8F9FA',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.35rem',
                }}
              >
                {captionSegments.map((seg, sIdx) => (
                  <div
                    key={sIdx}
                    style={{
                      display: 'flex',
                      alignItems: 'baseline',
                      gap: '0.5rem',
                      fontSize: '0.75rem',
                      lineHeight: 1.35,
                    }}
                  >
                    <span
                      style={{
                        color: 'var(--text-muted)',
                        fontFamily: 'monospace',
                        flexShrink: 0,
                        fontSize: '0.7rem',
                      }}
                    >
                      {Number(seg.start_seconds).toFixed(1)}s &ndash; {Number(seg.end_seconds).toFixed(1)}s:
                    </span>
                    <span style={{ color: 'var(--text-primary)' }}>&ldquo;{seg.text}&rdquo;</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="short-actions">
          {onSelect && (
            <button
              type="button"
              className={`btn-workspace-select ${isSelected ? 'btn-workspace-active' : ''}`}
              onClick={() => onSelect(short)}
              title="Open and edit in workspace"
            >
              <Maximize2 size={14} />
              <span>{isSelected ? 'Active Short' : 'Open in Workspace'}</span>
            </button>
          )}

          {videoSrc && !isFailed && (
            <a
              href={videoSrc}
              download={`short_${short.index}.mp4`}
              className="btn-download"
              aria-label={`Download Short #${short.index}`}
            >
              <Download size={15} />
              <span>Download</span>
            </a>
          )}

          {rawPath && (
            <button
              type="button"
              className="btn-secondary"
              onClick={handleCopyPath}
              title="Copy local file path"
              aria-label="Copy local file path"
            >
              {copied ? <Check size={15} /> : <Copy size={15} />}
            </button>
          )}
        </div>
      </div>
    </article>
  )
}
