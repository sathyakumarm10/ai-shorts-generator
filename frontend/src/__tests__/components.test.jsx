import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { Navbar } from '../components/Navbar'
import { HeroSection } from '../components/HeroSection'
import { UploadZone } from '../components/UploadZone'
import { GenerationSettings } from '../components/GenerationSettings'
import { ProcessingView } from '../components/ProcessingView'
import { ResultsGrid } from '../components/ResultsGrid'
import { ErrorBanner } from '../components/ErrorBanner'
import { JobHistoryModal } from '../components/JobHistoryModal'

describe('Navbar Component', () => {
  it('renders product title and projects count', () => {
    const onOpen = vi.fn()
    render(<Navbar onOpenHistory={onOpen} historyCount={3} />)
    expect(screen.getByText('AI Shorts Generator')).toBeInTheDocument()
    expect(screen.getByText('Projects (3)')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Projects (3)'))
    expect(onOpen).toHaveBeenCalledTimes(1)
  })
})

describe('HeroSection Component', () => {
  it('renders headline and feature badges', () => {
    render(<HeroSection />)
    expect(screen.getByText(/Turn long videos into/i)).toBeInTheDocument()
    expect(screen.getByText(/AI Highlight Detection/i)).toBeInTheDocument()
    expect(screen.getByText(/9:16 Vertical Auto-Crop/i)).toBeInTheDocument()
    expect(screen.getByText(/Synced Burned Captions/i)).toBeInTheDocument()
  })
})

describe('UploadZone Component', () => {
  it('renders dropzone when no file selected', () => {
    render(<UploadZone selectedFile={null} onFileSelected={() => {}} />)
    expect(screen.getByText(/Drag & drop your source video here/i)).toBeInTheDocument()
  })

  it('renders video info when file is selected', () => {
    const file = new File(['dummy'], 'podcast.mp4', { type: 'video/mp4' })
    // Mock URL.createObjectURL
    global.URL.createObjectURL = vi.fn(() => 'blob:mock-video')

    render(<UploadZone selectedFile={file} onClearFile={() => {}} />)
    expect(screen.getByText('podcast.mp4')).toBeInTheDocument()
    expect(screen.getByText('Remove')).toBeInTheDocument()
  })
})

describe('GenerationSettings Component', () => {
  it('updates settings on slider change and triggers generation', () => {
    const settings = {
      numberOfClips: 3,
      clipDurationSeconds: 45,
      includeCaptions: true,
      minClipDuration: 30,
      maxClipDuration: 120,
    }
    const onChange = vi.fn()
    const onGenerate = vi.fn()

    render(
      <GenerationSettings
        settings={settings}
        onChange={onChange}
        onGenerate={onGenerate}
        isSubmitting={false}
        canSubmit={true}
      />
    )

    expect(screen.getByText(/3 shorts/i)).toBeInTheDocument()
    expect(screen.getByText('45s')).toBeInTheDocument()

    // Test toggle
    const toggle = screen.getByLabelText('Toggle timestamped captions')
    fireEvent.click(toggle)
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ includeCaptions: false }))

    // Test generate button
    const btn = screen.getByText('Generate AI Shorts')
    fireEvent.click(btn)
    expect(onGenerate).toHaveBeenCalledTimes(1)
  })
})

describe('ProcessingView Component', () => {
  it('renders progress percentage and active stage', () => {
    const job = {
      status: 'transcribing',
      progress_percent: 35.0,
      message: 'Transcribing speech with AI',
    }

    render(<ProcessingView job={job} />)
    expect(screen.getAllByText('35%').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Transcribing speech with AI').length).toBeGreaterThan(0)
    expect(screen.getByText('Stage 4 of 9')).toBeInTheDocument()
  })
})

describe('ResultsGrid Component', () => {
  it('renders generated shorts cards with scores and actions', () => {
    const result = {
      generated_shorts: [
        {
          index: 1,
          final_file_path: '/path/to/short_1.mp4',
          candidate: {
            start_seconds: 15.0,
            end_seconds: 50.0,
            duration_seconds: 35.0,
            text: 'Amazing hook speech text',
            score: { overall: 0.95 },
          },
        },
      ],
    }

    render(<ResultsGrid result={result} onReset={() => {}} />)
    expect(screen.getByText('Your Generated Shorts')).toBeInTheDocument()
    expect(screen.getByText('Short #1')).toBeInTheDocument()
    expect(screen.getByText('95% Viral Score')).toBeInTheDocument()
    expect(screen.getByText('“Amazing hook speech text”')).toBeInTheDocument()
  })
})

describe('ErrorBanner Component', () => {
  it('renders error message and retry action', () => {
    const onRetry = vi.fn()
    const onDismiss = vi.fn()

    render(<ErrorBanner message="FFmpeg conversion failed" onRetry={onRetry} onDismiss={onDismiss} />)
    expect(screen.getByText('FFmpeg conversion failed')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Retry'))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })
})

describe('JobHistoryModal Component', () => {
  it('renders list of past jobs and allows selection', () => {
    const history = [
      {
        job_id: 'job-12345678',
        sourceName: 'My Podcast Episode',
        status: 'completed',
        created_at: new Date().toISOString(),
      },
    ]
    const onSelect = vi.fn()
    const onClose = vi.fn()

    render(
      <JobHistoryModal
        isOpen={true}
        onClose={onClose}
        history={history}
        onSelectJob={onSelect}
        onClearHistory={() => {}}
      />
    )

    expect(screen.getByText('My Podcast Episode')).toBeInTheDocument()
    expect(screen.getByText('completed')).toBeInTheDocument()

    fireEvent.click(screen.getByText('My Podcast Episode'))
    expect(onSelect).toHaveBeenCalledWith(history[0])
  })
})
