import React, { useState } from 'react'
import { Download, Sparkles, Clock, Check, Copy } from 'lucide-react'
import { getMediaUrl } from '../api/client'

export function ShortCard({ short }) {
  const [copied, setCopied] = useState(false)
  const videoSrc = getMediaUrl(short.final_file_path || short.vertical_clip_path)
  const candidate = short.candidate || {}
  const score = candidate.score?.overall != null
    ? Math.round(candidate.score.overall * 100)
    : null

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

          <span style={{ color: short.captioned_clip_path ? '#10b981' : 'var(--text-muted)', fontWeight: 600 }}>
            {short.captioned_clip_path ? 'Captioned' : 'No Captions'}
          </span>
        </div>

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
