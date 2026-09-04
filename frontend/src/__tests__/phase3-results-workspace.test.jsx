import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ShortGrid } from '../components/results/ShortGrid'
import { SubtitleEditor } from '../components/results/SubtitleEditor'
import { SubtitleStylePicker } from '../components/results/SubtitleStylePicker'
import { ShortNavigation } from '../components/results/ShortNavigation'
import { VideoWorkspacePreview } from '../components/results/VideoWorkspacePreview'
import {
  validateCaptionTrack,
  validateSegment,
  findActiveSegment,
  checkSubtitleLineLength,
} from '../utils/subtitleValidation'

describe('Phase 3 - Subtitle Validation Utilities', () => {
  it('validates segment start and end timestamps', () => {
    // Valid segment
    expect(validateSegment({ start_seconds: 0, end_seconds: 2.5 }, 10.0)).toEqual([])

    // Start >= 0 error
    expect(validateSegment({ start_seconds: -1, end_seconds: 2.5 }, 10.0)).toContain(
      'Start time must be greater than or equal to 0.0s.'
    )

    // End <= start error
    expect(validateSegment({ start_seconds: 4.0, end_seconds: 3.5 }, 10.0)).toContain(
      'End time must be strictly greater than start time.'
    )

    // Exceeds short duration error
    expect(validateSegment({ start_seconds: 2.0, end_seconds: 15.0 }, 10.0)).toContain(
      'End time (15.0s) exceeds Short duration (10.0s).'
    )
  })

  it('detects and prevents overlapping subtitle segments', () => {
    const overlappingSegments = [
      { start_seconds: 0.0, end_seconds: 3.0, text: 'First line' },
      { start_seconds: 2.5, end_seconds: 5.0, text: 'Overlapping line' },
    ]

    const result = validateCaptionTrack(overlappingSegments, 10.0)
    expect(result.isValid).toBe(false)
    expect(result.overlapErrors[1]).toMatch(/Overlap detected/i)
  })

  it('validates recommended maximum subtitle line length (32 chars)', () => {
    const shortLine = checkSubtitleLineLength('Short punchy line', 32)
    expect(shortLine.exceeds).toBe(false)
    expect(shortLine.length).toBe(17)

    const longLine = checkSubtitleLineLength(
      'This is an excessively long subtitle line that goes way beyond the thirty two character limit',
      32
    )
    expect(longLine.exceeds).toBe(true)
  })

  it('correctly identifies active subtitle segment for current playback timestamp', () => {
    const segments = [
      { start_seconds: 0.0, end_seconds: 2.0, text: 'Segment 1' },
      { start_seconds: 2.0, end_seconds: 4.5, text: 'Segment 2' },
      { start_seconds: 4.5, end_seconds: 8.0, text: 'Segment 3' },
    ]

    expect(findActiveSegment(segments, 1.2).activeSegment?.text).toBe('Segment 1')
    expect(findActiveSegment(segments, 3.0).activeSegment?.text).toBe('Segment 2')
    expect(findActiveSegment(segments, 7.5).activeSegment?.text).toBe('Segment 3')
    expect(findActiveSegment(segments, 9.0).activeSegment).toBeNull()
  })
})

describe('Phase 3 - ShortNavigation Component', () => {
  it('renders current position indicator and disables buttons at boundaries', () => {
    const onSelect = vi.fn()
    const shorts = [{ index: 1 }, { index: 2 }, { index: 3 }]

    // Render at first Short (index 0)
    const { rerender } = render(
      <ShortNavigation
        totalCount={3}
        currentIndex={0}
        onSelectIndex={onSelect}
        shorts={shorts}
      />
    )

    expect(screen.getByText('Short 1 of 3')).toBeInTheDocument()
    const prevBtn = screen.getByRole('button', { name: /previous/i })
    const nextBtn = screen.getByRole('button', { name: /next/i })

    expect(prevBtn).toBeDisabled()
    expect(nextBtn).toBeEnabled()

    // Click next
    fireEvent.click(nextBtn)
    expect(onSelect).toHaveBeenCalledWith(1)

    // Rerender at last Short (index 2)
    rerender(
      <ShortNavigation
        totalCount={3}
        currentIndex={2}
        onSelectIndex={onSelect}
        shorts={shorts}
      />
    )

    expect(screen.getByText('Short 3 of 3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /previous/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled()
  })
})

describe('Phase 3 - SubtitleStylePicker Component', () => {
  it('renders Default, Karaoke, Minimal options and triggers selection', () => {
    const onSelectStyle = vi.fn()
    render(
      <SubtitleStylePicker currentStyle="default" onSelectStyle={onSelectStyle} />
    )

    expect(screen.getByRole('radio', { name: /default/i })).toHaveClass('active')
    expect(screen.getByRole('radio', { name: /karaoke/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /minimal/i })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('radio', { name: /karaoke/i }))
    expect(onSelectStyle).toHaveBeenCalledWith('karaoke')
  })
})

describe('Phase 3 - SubtitleEditor Component', () => {
  const initialTrack = {
    segments: [
      { start_seconds: 0.0, end_seconds: 2.0, text: 'Hello world' },
      { start_seconds: 2.0, end_seconds: 5.0, text: 'Second subtitle' },
    ],
  }

  it('renders subtitle segments and allows editing text and timestamps', () => {
    render(
      <SubtitleEditor
        captionTrack={initialTrack}
        duration={10.0}
        activeIndex={0}
        onSeek={vi.fn()}
        onSaveTrack={vi.fn()}
      />
    )

    expect(screen.getByText(/2 segments/i)).toBeInTheDocument()
    expect(screen.getByText('Playing')).toBeInTheDocument() // activeIndex = 0 has Playing badge

    const textInputs = screen.getAllByRole('textbox')
    expect(textInputs[0]).toHaveValue('Hello world')

    fireEvent.change(textInputs[0], { target: { value: 'Updated subtitle text' } })
    expect(textInputs[0]).toHaveValue('Updated subtitle text')
  })

  it('validates invalid timestamps and prevents saving when errors exist', async () => {
    render(
      <SubtitleEditor
        captionTrack={initialTrack}
        duration={10.0}
        activeIndex={-1}
        onSeek={vi.fn()}
        onSaveTrack={vi.fn()}
      />
    )

    const startInput = screen.getByLabelText('Segment #1 start time')
    // Set start to negative value
    fireEvent.change(startInput, { target: { value: '-2.0' } })

    expect(
      screen.getByText(/Start time must be greater than or equal to 0.0s/i)
    ).toBeInTheDocument()

    const saveBtn = screen.getByRole('button', { name: /save subtitles/i })
    expect(saveBtn).toBeDisabled()
  })

  it('saves updated subtitles and notifies user about persistence requiring backend endpoint', async () => {
    const onSave = vi.fn().mockResolvedValue({})
    render(
      <SubtitleEditor
        captionTrack={initialTrack}
        duration={10.0}
        activeIndex={-1}
        onSeek={vi.fn()}
        onSaveTrack={onSave}
      />
    )

    const saveBtn = screen.getByRole('button', { name: /save subtitles/i })
    expect(saveBtn).toBeEnabled()

    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(onSave).toHaveBeenCalled()
      expect(
        screen.getByText(/Subtitles updated in workspace/i)
      ).toBeInTheDocument()
      expect(
        screen.getByText(/Persistence requires a backend endpoint/i)
      ).toBeInTheDocument()
    })
  })

  it('handles missing captions gracefully with empty state and add button', () => {
    render(
      <SubtitleEditor
        captionTrack={null}
        duration={10.0}
        activeIndex={-1}
        onSeek={vi.fn()}
        onSaveTrack={vi.fn()}
      />
    )

    expect(screen.getByText('No Captions Available')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /add first subtitle/i })
    ).toBeInTheDocument()
  })
})

describe('Phase 3 - VideoWorkspacePreview Component', () => {
  const mockShort = {
    index: 1,
    final_file_path: 'outputs/jobs/job-1/short_001.mp4',
    vertical_clip_path: 'outputs/jobs/job-1/vertical/short_001.mp4',
    framing_type: 'smart_framing',
    candidate: {
      start_seconds: 0.0,
      end_seconds: 30.0,
      duration_seconds: 30.0,
      title: 'Awesome Viral Clip',
      viral_hook: 'Watch till the end',
      score: { overall: 0.92 },
      source_type: 'ai',
    },
    caption_track: {
      segments: [{ start_seconds: 0.0, end_seconds: 2.5, text: 'Viral speech text' }],
    },
  }

  it('renders video element, overlays active caption, and provides download button', () => {
    render(
      <VideoWorkspacePreview
        short={mockShort}
        activeCaptionText="Viral speech text"
        captionStyle="karaoke"
        onTimeUpdate={vi.fn()}
      />
    )

    expect(screen.getByText('Preview #1')).toBeInTheDocument()
    expect(screen.getByText('92% Potential')).toBeInTheDocument()
    expect(screen.getByText('Active Short: Awesome Viral Clip')).toBeInTheDocument()
    expect(screen.getByText(/Watch till the end/i)).toBeInTheDocument()

    // Live caption overlay
    expect(screen.getByText('Viral speech text')).toBeInTheDocument()

    // Download button
    const downloadLink = screen.getByRole('link', { name: /download active short #1/i })
    expect(downloadLink).toBeInTheDocument()
    expect(downloadLink).toHaveAttribute('href', expect.stringContaining('short_001.mp4'))
  })

  it('handles failed or unavailable video gracefully', () => {
    const failedShort = {
      index: 2,
      status: 'failed',
      error_message: 'Video encoding failed due to corrupt source frame',
    }

    render(
      <VideoWorkspacePreview
        short={failedShort}
        activeCaptionText={null}
        captionStyle="default"
        onTimeUpdate={vi.fn()}
      />
    )

    expect(screen.getByText('Short Video Generation Failed')).toBeInTheDocument()
    expect(
      screen.getByText(/Video encoding failed due to corrupt source frame/i)
    ).toBeInTheDocument()
  })
})

describe('Phase 3 - Full Results Workspace Integration in ShortGrid', () => {
  const multiShorts = [
    {
      index: 1,
      status: 'completed',
      final_file_path: 'outputs/jobs/job-1/short_1.mp4',
      candidate: {
        start_seconds: 0.0,
        end_seconds: 20.0,
        duration_seconds: 20.0,
        title: 'Highlight One',
        score: { overall: 0.9 },
      },
      caption_track: {
        segments: [{ start_seconds: 0.0, end_seconds: 3.0, text: 'First short caption' }],
      },
    },
    {
      index: 2,
      status: 'completed',
      final_file_path: 'outputs/jobs/job-1/short_2.mp4',
      candidate: {
        start_seconds: 25.0,
        end_seconds: 45.0,
        duration_seconds: 20.0,
        title: 'Highlight Two',
        score: { overall: 0.85 },
      },
      caption_track: {
        segments: [{ start_seconds: 0.0, end_seconds: 3.0, text: 'Second short caption' }],
      },
    },
    {
      index: 3,
      status: 'failed',
      error_message: 'FFmpeg filter failure',
      candidate: {
        start_seconds: 50.0,
        end_seconds: 70.0,
        duration_seconds: 20.0,
        title: 'Failed Highlight',
      },
    },
  ]

  it('renders workspace with total counts, navigation, and does not hide successful shorts when one fails', () => {
    const result = {
      generated_shorts: multiShorts,
      candidates: [{}, {}, {}],
    }

    render(<ShortGrid result={result} jobId="job-p3-test" onReset={vi.fn()} />)

    // Summary counts
    expect(screen.getByText(/3 Shorts created and formatted/i)).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument() // 2 Ready to Export
    expect(screen.getByText('Ready to Export')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument() // 1 Failed Render
    expect(screen.getByText('Failed Render')).toBeInTheDocument()

    // Workspace navigation
    expect(screen.getByText('Short 1 of 3')).toBeInTheDocument()

    // Next navigates to Short 2
    const nextBtn = screen.getByRole('button', { name: /next/i })
    fireEvent.click(nextBtn)
    expect(screen.getByText('Short 2 of 3')).toBeInTheDocument()

    // Next navigates to failed Short 3 without crashing
    fireEvent.click(nextBtn)
    expect(screen.getByText('Short 3 of 3')).toBeInTheDocument()
    expect(screen.getByText('Short Video Generation Failed')).toBeInTheDocument()

    // All 3 shorts remain visible in the grid below
    expect(screen.getByText('Short #1')).toBeInTheDocument()
    expect(screen.getByText('Short #2')).toBeInTheDocument()
    expect(screen.getByText('Short #3')).toBeInTheDocument()
  })

  it('selects a Short when clicking Open in Workspace from the cards list', () => {
    const result = {
      generated_shorts: multiShorts,
      candidates: [{}, {}, {}],
    }

    render(<ShortGrid result={result} jobId="job-p3-test" onReset={vi.fn()} />)

    // Currently on Short 1
    expect(screen.getByText('Short 1 of 3')).toBeInTheDocument()

    // Click "Open in Workspace" on Short #2 (second button in the list)
    const openBtns = screen.getAllByRole('button', { name: /open in workspace/i })
    fireEvent.click(openBtns[0]) // Since Short #1 is selected and has "Active Short", openBtns[0] is for Short #2!

    expect(screen.getByText('Short 2 of 3')).toBeInTheDocument()
  })
})
