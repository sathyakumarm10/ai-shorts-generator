import React, { useState } from 'react'
import { Download, Sparkles, Clock, Check, Copy, Flame, Cpu, Subtitles } from 'lucide-react'
import { getMediaUrl } from '../../api/client'

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
  const hasCaptions = Boolean(short.captioned_clip_path || short.caption_track)

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
        <div className="short-meta-header">
          <span className="short-duration-text">
            <Clock size={13} />
            {candidate.start_seconds?.toFixed(1)}s &ndash; {candidate.end_seconds?.toFixed(1)}s ({candidate.duration_seconds?.toFixed(1)}s)
          </span>

          <div className="short-tags-cluster">
            <span
              className={`short-source-tag ${isAI ? 'tag-ai' : 'tag-heuristic'}`}
            >
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

            <span
              className={`short-caption-tag ${hasCaptions ? 'caption-active' : 'caption-none'}`}
            >
              <Subtitles size={11} />
              {hasCaptions ? `${short.caption_preset || 'Dynamic'} Captions` : 'No Captions'}
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
            {copied ? <Check size={15} /> : <Copy size={15} />}
          </button>
        </div>
      </div>
    </article>
  )
}
