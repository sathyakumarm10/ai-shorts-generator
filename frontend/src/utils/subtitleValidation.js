/**
 * Subtitle Validation and Time Utilities for the AI Shorts Generator Results Workspace.
 *
 * Enforces rules from dynamic caption service:
 * - Start time >= 0
 * - End time > Start time
 * - Timestamps within Short duration (if duration provided)
 * - Subtitle segments must not overlap chronologically
 * - Maximum recommended line length (default 32 characters)
 */

export const MAX_SUBTITLE_LINE_CHARS = 32

/**
 * Validates an individual subtitle segment.
 * @param {Object} segment { start_seconds, end_seconds, text }
 * @param {number|null} duration Total duration of the Short in seconds
 * @returns {string[]} Array of error messages for this segment
 */
export function validateSegment(segment, duration = null) {
  const errors = []
  const start = Number(segment.start_seconds)
  const end = Number(segment.end_seconds)

  if (isNaN(start) || start < 0) {
    errors.push('Start time must be greater than or equal to 0.0s.')
  }

  if (isNaN(end) || end <= start) {
    errors.push('End time must be strictly greater than start time.')
  }

  if (duration != null && duration > 0) {
    if (start > duration) {
      errors.push(`Start time (${start.toFixed(1)}s) exceeds Short duration (${duration.toFixed(1)}s).`)
    }
    if (end > duration) {
      errors.push(`End time (${end.toFixed(1)}s) exceeds Short duration (${duration.toFixed(1)}s).`)
    }
  }

  return errors
}

/**
 * Validates a list of caption segments for chronological ordering and overlap.
 * @param {Array} segments Array of { start_seconds, end_seconds, text }
 * @param {number|null} duration Short duration in seconds
 * @returns {{ isValid: boolean, segmentErrors: Object, overlapErrors: Object, generalErrors: string[] }}
 */
export function validateCaptionTrack(segments = [], duration = null) {
  const segmentErrors = {}
  const overlapErrors = {}
  const generalErrors = []

  if (!Array.isArray(segments) || segments.length === 0) {
    return { isValid: true, segmentErrors, overlapErrors, generalErrors }
  }

  // 1. Validate individual segment fields
  segments.forEach((seg, index) => {
    const errs = validateSegment(seg, duration)
    if (errs.length > 0) {
      segmentErrors[index] = errs
    }
  })

  // 2. Check for chronological overlaps
  // Subtitle segments must not overlap: seg[i].start_seconds < seg[i-1].end_seconds
  for (let i = 1; i < segments.length; i++) {
    const prev = segments[i - 1]
    const curr = segments[i]

    const prevEnd = Number(prev.end_seconds)
    const currStart = Number(curr.start_seconds)

    if (!isNaN(prevEnd) && !isNaN(currStart) && currStart < prevEnd) {
      const msg = `Overlap detected: Segment #${i + 1} starts at ${currStart.toFixed(1)}s before Segment #${i} ends at ${prevEnd.toFixed(1)}s.`
      overlapErrors[i] = msg
      overlapErrors[i - 1] = msg
    }
  }

  const isValid =
    Object.keys(segmentErrors).length === 0 &&
    Object.keys(overlapErrors).length === 0 &&
    generalErrors.length === 0

  return {
    isValid,
    segmentErrors,
    overlapErrors,
    generalErrors,
  }
}

/**
 * Check if subtitle text exceeds recommended max character length per line.
 * @param {string} text
 * @param {number} maxChars
 * @returns {{ exceeds: boolean, length: number, maxChars: number }}
 */
export function checkSubtitleLineLength(text = '', maxChars = MAX_SUBTITLE_LINE_CHARS) {
  const length = (text || '').trim().length
  return {
    exceeds: length > maxChars,
    length,
    maxChars,
  }
}

/**
 * Find the active caption segment for the given playback time.
 * @param {Array} segments
 * @param {number} currentTime
 * @returns {{ activeSegment: Object|null, activeIndex: number }}
 */
export function findActiveSegment(segments = [], currentTime = 0) {
  if (!Array.isArray(segments) || segments.length === 0) {
    return { activeSegment: null, activeIndex: -1 }
  }

  const activeIndex = segments.findIndex((seg) => {
    const start = Number(seg.start_seconds)
    const end = Number(seg.end_seconds)
    return currentTime >= start && currentTime <= end
  })

  return {
    activeSegment: activeIndex >= 0 ? segments[activeIndex] : null,
    activeIndex,
  }
}
