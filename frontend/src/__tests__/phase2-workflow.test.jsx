import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ShortCard } from '../components/results/ShortCard'
import { ShortGrid } from '../components/results/ShortGrid'
import { GenerationProgress } from '../components/generation/GenerationProgress'

describe('Phase 2 - ShortCard Component with HTML5 Video & Subtitles', () => {
  const mockShort = {
    index: 3,
    final_file_path: 'outputs/jobs/job-1/short_003.mp4',
    vertical_clip_path: 'outputs/jobs/job-1/vertical/short_003.mp4',
    captioned_clip_path: 'outputs/jobs/job-1/captioned/short_003.mp4',
    framing_type: 'smart_framing',
    caption_preset: 'default',
    is_karaoke: true,
    candidate: {
      start_seconds: 15.0,
      end_seconds: 75.0,
      duration_seconds: 60.0,
      text: 'AI video generation creates viral clips automatically from long videos.',
      score: { overall: 0.88 },
      title: 'How AI Video Automation Works',
      viral_hook: 'You will not believe how easy this is',
      source_type: 'ai',
    },
    caption_track: {
      segments: [
        { start_seconds: 0.0, end_seconds: 2.5, text: 'AI video generation creates' },
        { start_seconds: 2.5, end_seconds: 5.0, text: 'viral clips automatically' },
        { start_seconds: 5.0, end_seconds: 8.0, text: 'from long videos.' },
      ],
    },
  }

  it('renders individual short metadata, viral score, and HTML5 video element', () => {
    render(<ShortCard short={mockShort} />)

    expect(screen.getByText('Short #3')).toBeInTheDocument()
    expect(screen.getByText('88% Viral Score')).toBeInTheDocument()
    expect(screen.getByText('How AI Video Automation Works')).toBeInTheDocument()
    expect(screen.getByText(/You will not believe how easy this is/i)).toBeInTheDocument()
    expect(screen.getByText('Smart Framing')).toBeInTheDocument()
    expect(screen.getByText('Karaoke FX')).toBeInTheDocument()
    expect(screen.getByText('default Captions')).toBeInTheDocument()

    const videoEl = document.querySelector('video')
    expect(videoEl).toBeInTheDocument()
    expect(videoEl).toHaveAttribute('controls')
    expect(videoEl).toHaveAttribute('playsinline')
  })

  it('toggles synchronized subtitle segments view for the individual short', () => {
    render(<ShortCard short={mockShort} />)

    const toggleBtn = screen.getByText(/View Synchronized Subtitles \(3\)/i)
    expect(toggleBtn).toBeInTheDocument()

    // Expand subtitles
    fireEvent.click(toggleBtn)
    expect(screen.getByText('Hide Subtitles')).toBeInTheDocument()
    expect(screen.getByText(/0.0s – 2.5s:/i)).toBeInTheDocument()
    expect(screen.getByText(/“AI video generation creates”/i)).toBeInTheDocument()
    expect(screen.getByText(/“viral clips automatically”/i)).toBeInTheDocument()

    // Collapse subtitles
    fireEvent.click(screen.getByText('Hide Subtitles'))
    expect(screen.queryByText(/0.0s – 2.5s:/i)).not.toBeInTheDocument()
  })

  it('handles video playback errors gracefully without crashing', () => {
    render(<ShortCard short={mockShort} />)

    const videoEl = document.querySelector('video')
    expect(videoEl).toBeInTheDocument()

    // Trigger video error event
    fireEvent.error(videoEl)

    expect(screen.getByText('Video preview unavailable')).toBeInTheDocument()
    expect(screen.getByText(/Download below to view the rendered MP4 file/i)).toBeInTheDocument()
  })
})

describe('Phase 2 - ShortGrid Component with Dynamic Multi-Short Results', () => {
  it('renders all 10 shorts when 10 shorts are returned by the backend', () => {
    const tenShorts = Array.from({ length: 10 }, (_, i) => ({
      index: i + 1,
      final_file_path: `outputs/jobs/job-1/short_${i + 1}.mp4`,
      candidate: {
        start_seconds: i * 30,
        end_seconds: (i + 1) * 30,
        duration_seconds: 30,
        text: `Highlight moment number ${i + 1} transcript.`,
        score: { overall: 0.85 },
      },
    }))

    const result = {
      generated_shorts: tenShorts,
      candidates: tenShorts.map(s => s.candidate),
    }

    render(<ShortGrid result={result} jobId="job-abc-123" onReset={() => {}} />)

    expect(screen.getByText(/10 Shorts created and formatted/i)).toBeInTheDocument()
    for (let i = 1; i <= 10; i++) {
      expect(screen.getByText(`Short #${i}`)).toBeInTheDocument()
    }
  })

  it('renders 7 shorts and shows non-blocking notice when fewer valid highlights exist', () => {
    const sevenShorts = Array.from({ length: 7 }, (_, i) => ({
      index: i + 1,
      final_file_path: `outputs/jobs/job-1/short_${i + 1}.mp4`,
      candidate: {
        start_seconds: i * 30,
        end_seconds: (i + 1) * 30,
        duration_seconds: 30,
        text: `Highlight moment ${i + 1}.`,
        score: { overall: 0.8 },
      },
    }))

    // 10 candidates were evaluated, but only 7 produced valid rendered shorts
    const result = {
      generated_shorts: sevenShorts,
      candidates: Array.from({ length: 10 }, () => ({})),
    }

    render(<ShortGrid result={result} jobId="job-7-shorts" onReset={() => {}} />)

    expect(screen.getByText(/7 Shorts created and formatted/i)).toBeInTheDocument()
    expect(screen.getByText(/3 highlight candidates lacked sufficient audio\/visual clarity/i)).toBeInTheDocument()
    expect(screen.getAllByText(/Short #/).length).toBe(7)
  })
})

describe('Phase 2 - GenerationProgress Component with Real Backend Metrics', () => {
  it('displays real backend stage, requested count, rendered count, and progress message', () => {
    const job = {
      job_id: 'job-real-1',
      status: 'converting_vertical',
      progress_percent: 78.5,
      number_of_clips: 10,
      message: 'Converting short #5/10 to 9:16 vertical format',
    }

    render(<GenerationProgress job={job} onCancel={() => {}} />)

    expect(screen.getByText('Creating Your Shorts')).toBeInTheDocument()
    expect(screen.getByText('Converting short #5/10 to 9:16 vertical format')).toBeInTheDocument()
    expect(screen.getByText('Requested:')).toBeInTheDocument()
    expect(screen.getByText('10')).toBeInTheDocument()
    expect(screen.getByText('Generated:')).toBeInTheDocument()
    expect(screen.getByText('4')).toBeInTheDocument() // Rendered 4 so far, currently on #5
    expect(screen.getByText('79%')).toBeInTheDocument()
    expect(screen.getAllByText('Converting to 9:16 vertical video').length).toBeGreaterThan(0)
  })
})
