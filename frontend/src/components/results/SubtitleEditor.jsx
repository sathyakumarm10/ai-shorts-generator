import React, { useState, useEffect } from 'react'
import { Plus, Trash2, Save, AlertCircle, CheckCircle, Info, Clock, Play } from 'lucide-react'
import {
  validateCaptionTrack,
  checkSubtitleLineLength,
  MAX_SUBTITLE_LINE_CHARS,
} from '../../utils/subtitleValidation'

export function SubtitleEditor({
  captionTrack,
  duration,
  activeIndex = -1,
  onSeek,
  onSaveTrack,
}) {
  const [segments, setSegments] = useState([])
  const [saveStatus, setSaveStatus] = useState('idle') // 'idle' | 'saving' | 'saved' | 'error'
  const [saveMessage, setSaveMessage] = useState('')

  // Sync internal segments state whenever captionTrack changes
  useEffect(() => {
    const rawSegments = captionTrack?.segments || []
    setSegments(
      rawSegments.map((s) => ({
        start_seconds: Number(s.start_seconds) || 0,
        end_seconds: Number(s.end_seconds) || 0,
        text: s.text || '',
      }))
    )
    setSaveStatus('idle')
    setSaveMessage('')
  }, [captionTrack])

  // Run validation
  const validation = validateCaptionTrack(segments, duration)

  const handleTextChange = (idx, newText) => {
    setSegments((prev) => {
      const next = [...prev]
      next[idx] = { ...next[idx], text: newText }
      return next
    })
    if (saveStatus !== 'idle') setSaveStatus('idle')
  }

  const handleTimeChange = (idx, field, val) => {
    const numVal = parseFloat(val)
    setSegments((prev) => {
      const next = [...prev]
      next[idx] = { ...next[idx], [field]: isNaN(numVal) ? val : numVal }
      return next
    })
    if (saveStatus !== 'idle') setSaveStatus('idle')
  }

  const handleAddSegment = () => {
    const lastSeg = segments[segments.length - 1]
    const nextStart = lastSeg ? Number(lastSeg.end_seconds) : 0
    const nextEnd = Math.min(nextStart + 3.0, duration || nextStart + 3.0)

    setSegments((prev) => [
      ...prev,
      {
        start_seconds: Number(nextStart.toFixed(1)),
        end_seconds: Number(nextEnd.toFixed(1)),
        text: 'New subtitle segment',
      },
    ])
    if (saveStatus !== 'idle') setSaveStatus('idle')
  }

  const handleDeleteSegment = (idx) => {
    setSegments((prev) => prev.filter((_, i) => i !== idx))
    if (saveStatus !== 'idle') setSaveStatus('idle')
  }

  const handleSave = async () => {
    if (!validation.isValid) {
      setSaveStatus('error')
      setSaveMessage('Please fix timestamp errors and overlaps before saving.')
      return
    }

    setSaveStatus('saving')
    try {
      if (onSaveTrack) {
        await onSaveTrack({ segments })
      }
      setSaveStatus('saved')
      setSaveMessage('Subtitles updated in workspace. (Persistence requires a backend endpoint)')
    } catch (err) {
      setSaveStatus('error')
      setSaveMessage(err?.message || 'Failed to save subtitles.')
    }
  }

  const hasNoCaptions = segments.length === 0

  return (
    <div className="subtitle-editor" aria-label="Subtitle Editor">
      <div className="subtitle-editor-header">
        <div>
          <h3 className="editor-title">Subtitle Track</h3>
          <p className="editor-subtitle">
            {segments.length} {segments.length === 1 ? 'segment' : 'segments'} &bull; Synchronized
          </p>
        </div>

        <div className="editor-actions">
          <button
            type="button"
            className="btn-add-segment"
            onClick={handleAddSegment}
            title="Add new subtitle segment"
          >
            <Plus size={14} />
            <span>Add Segment</span>
          </button>

          <button
            type="button"
            className="btn-save-subtitles"
            onClick={handleSave}
            disabled={saveStatus === 'saving' || !validation.isValid}
          >
            <Save size={14} />
            <span>{saveStatus === 'saving' ? 'Saving...' : 'Save Subtitles'}</span>
          </button>
        </div>
      </div>

      {/* Save Status Banners */}
      {saveStatus === 'saved' && (
        <div className="editor-banner banner-success" role="status">
          <CheckCircle size={15} />
          <span>{saveMessage}</span>
        </div>
      )}

      {saveStatus === 'error' && (
        <div className="editor-banner banner-error" role="alert">
          <AlertCircle size={15} />
          <span>{saveMessage}</span>
        </div>
      )}

      {!validation.isValid && (
        <div className="editor-banner banner-warning" role="alert">
          <AlertCircle size={15} />
          <span>Timestamps contain errors or overlapping segments. Fix them to enable saving.</span>
        </div>
      )}

      {/* Empty State when Short has no captions */}
      {hasNoCaptions ? (
        <div className="subtitles-empty-state">
          <Info size={28} />
          <h4>No Captions Available</h4>
          <p>This Short does not currently have a synchronized subtitle track.</p>
          <button
            type="button"
            className="btn-secondary"
            onClick={handleAddSegment}
          >
            <Plus size={14} />
            <span>Add First Subtitle</span>
          </button>
        </div>
      ) : (
        <div className="subtitle-segment-list">
          {segments.map((seg, idx) => {
            const isActive = idx === activeIndex
            const segErrors = validation.segmentErrors[idx] || []
            const overlapError = validation.overlapErrors[idx]
            const lineLengthInfo = checkSubtitleLineLength(seg.text, MAX_SUBTITLE_LINE_CHARS)

            return (
              <div
                key={idx}
                className={`subtitle-segment-card ${isActive ? 'active-playback' : ''}`}
                data-active={isActive ? 'true' : 'false'}
              >
                <div className="segment-card-header">
                  <div className="segment-timing-group">
                    {onSeek && (
                      <button
                        type="button"
                        className="btn-seek"
                        onClick={() => onSeek(seg.start_seconds)}
                        title={`Seek video to ${Number(seg.start_seconds).toFixed(1)}s`}
                      >
                        <Play size={11} />
                      </button>
                    )}
                    <span className="segment-number">#{idx + 1}</span>

                    <div className="time-input-wrap">
                      <label htmlFor={`start-${idx}`}>Start</label>
                      <input
                        id={`start-${idx}`}
                        type="number"
                        step="0.1"
                        min="0"
                        className={`time-input ${segErrors.some(e => e.includes('Start')) ? 'input-error' : ''}`}
                        value={seg.start_seconds}
                        onChange={(e) => handleTimeChange(idx, 'start_seconds', e.target.value)}
                        aria-label={`Segment #${idx + 1} start time`}
                      />
                      <span className="time-unit">s</span>
                    </div>

                    <span className="time-sep">&ndash;</span>

                    <div className="time-input-wrap">
                      <label htmlFor={`end-${idx}`}>End</label>
                      <input
                        id={`end-${idx}`}
                        type="number"
                        step="0.1"
                        min="0"
                        className={`time-input ${segErrors.some(e => e.includes('End')) ? 'input-error' : ''}`}
                        value={seg.end_seconds}
                        onChange={(e) => handleTimeChange(idx, 'end_seconds', e.target.value)}
                        aria-label={`Segment #${idx + 1} end time`}
                      />
                      <span className="time-unit">s</span>
                    </div>

                    {isActive && (
                      <span className="badge-active-caption">Playing</span>
                    )}
                  </div>

                  <button
                    type="button"
                    className="btn-delete-segment"
                    onClick={() => handleDeleteSegment(idx)}
                    title="Delete segment"
                    aria-label={`Delete segment #${idx + 1}`}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>

                <div className="segment-text-wrap">
                  <input
                    type="text"
                    className="segment-text-input"
                    value={seg.text}
                    onChange={(e) => handleTextChange(idx, e.target.value)}
                    placeholder="Enter subtitle text..."
                    aria-label={`Segment #${idx + 1} text`}
                  />
                  <div className="segment-text-meta">
                    <span className={`char-counter ${lineLengthInfo.exceeds ? 'char-warning' : ''}`}>
                      {lineLengthInfo.length}/{MAX_SUBTITLE_LINE_CHARS} chars
                      {lineLengthInfo.exceeds && ' (exceeds recommended single-line limit)'}
                    </span>
                  </div>
                </div>

                {/* Validation Warnings */}
                {(segErrors.length > 0 || overlapError) && (
                  <div className="segment-validation-box">
                    {segErrors.map((err, errI) => (
                      <div key={errI} className="validation-error-item">
                        <AlertCircle size={12} />
                        <span>{err}</span>
                      </div>
                    ))}
                    {overlapError && (
                      <div className="validation-error-item">
                        <AlertCircle size={12} />
                        <span>{overlapError}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
