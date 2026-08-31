import React, { useState } from 'react'
import { Download, Sparkles, Clock, Check, Copy, Flame, Cpu } from 'lucide-react'
import { getMediaUrl } from '../api/client'

export function ShortCard({ short }) {
  const [copied, setCopied] = useState(false)
  const videoSrc = getMediaUrl(short.final_file_path || short.vertical_clip_path)
  const candidate = short.candidate || {}
  const score = candidate.score?.overall != null
    ? Math.round(candidate.score.overall * 100)
    : null

  const isAI = candidate.source_type === 'ai'
  const title = candidate.title
  const hook = candidate.viral_hook

  const handleCopyPath = async () => {
    try {
      await navigator.clipboard.writeText(short.final_file_path || '')
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback
    }
  }

  return (
    <article className="short-card" aria-label={`Short #${short.index}`}>
      <div className="short-video-wrapper">
        <video
          className="short-video"
          src={videoSrc}
          controls
          preload="metadata"
          playsInline
        />
        <div className="short-badge">Short #{short.index}</div>
        {score != null && (
          <div className="short-score-badge">
            <Sparkles size={12} style={{ display: 'inline', marginRight: '3px' }} />
            {score}% Viral Score
          </div>
        )}
      </div>

      <div className="short-details">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.82rem', color: 'var(--text-muted)' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
            <Clock size={13} />
            {candidate.start_seconds?.toFixed(1)}s &ndash; {candidate.end_seconds?.toFixed(1)}s ({candidate.duration_seconds?.toFixed(1)}s)
          </span>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '3px',
                fontSize: '0.72rem',
                padding: '2px 6px',
                borderRadius: '4px',
                background: isAI ? 'rgba(139, 92, 246, 0.15)' : 'rgba(100, 116, 139, 0.15)',
                color: isAI ? '#a78bfa' : '#94a3b8',
                fontWeight: 600,
              }}
            >
              {isAI ? <Sparkles size={11} /> : <Cpu size={11} />}
              {isAI ? 'AI Pick' : 'Heuristic'}
            </span>
            {short.framing_type === 'smart_framing' && (
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  fontSize: '0.72rem',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  background: 'rgba(56, 189, 248, 0.15)',
                  color: '#38bdf8',
                  fontWeight: 600,
                }}
              >
                Smart Framing
              </span>
            )}
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                fontSize: '0.72rem',
                padding: '2px 6px',
                borderRadius: '4px',
                background: short.captioned_clip_path ? 'rgba(16, 185, 129, 0.15)' : 'rgba(100, 116, 139, 0.15)',
                color: short.captioned_clip_path ? '#10b981' : 'var(--text-muted)',
                fontWeight: 600,
                textTransform: 'capitalize',
              }}
            >
              {short.captioned_clip_path ? `${short.caption_preset || 'Dynamic'} Captions` : 'No Captions'}
            </span>
          </div>
        </div>

        {title && (
          <div>
            <h4
              style={{
                margin: '0.35rem 0 0.2rem',
                fontSize: '0.96rem',
                fontWeight: 700,
                color: 'var(--text-primary)',
                lineHeight: 1.3,
              }}
            >
              {title}
            </h4>
          </div>
        )}

        {hook && (
          <p
            style={{
              margin: '0 0 0.35rem',
              fontSize: '0.82rem',
              color: '#f59e0b',
              fontWeight: 500,
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            <Flame size={13} />
            <span>&ldquo;{hook}&rdquo;</span>
          </p>
        )}

        {candidate.text && (
          <p className="short-transcript-snippet" title={candidate.text}>
            &ldquo;{candidate.text}&rdquo;
          </p>
        )}

        <div className="short-actions">
          <a
            href={videoSrc}
            download={`short_${short.index}.mp4`}
            className="btn-download"
            aria-label={`Download Short #${short.index}`}
          >
            <Download size={15} />
            <span>Download Short</span>
          </a>

          <button
            type="button"
            className="btn-secondary"
            onClick={handleCopyPath}
            title="Copy local file path"
            aria-label="Copy local file path"
          >
            {copied ? <Check size={15} color="#10b981" /> : <Copy size={15} />}
          </button>
        </div>
      </div>
    </article>
  )
}
