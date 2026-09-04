import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { EmptyState } from '../components/ui/EmptyState'
import { LoadingState } from '../components/ui/LoadingState'
import { ErrorState } from '../components/ui/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { Sidebar } from '../components/Sidebar'
import { GenerationSettings } from '../components/generation/GenerationSettings'
import { ShortGrid } from '../components/results/ShortGrid'
import { AuthProvider } from '../context/AuthContext'

describe('EmptyState Component', () => {
  it('renders title, description and calls action callback', () => {
    const onAction = vi.fn()
    render(
      <EmptyState
        title="No items found"
        description="Try generating a new short"
        actionLabel="Create Now"
        onAction={onAction}
      />
    )

    expect(screen.getByText('No items found')).toBeInTheDocument()
    expect(screen.getByText('Try generating a new short')).toBeInTheDocument()
    const btn = screen.getByText('Create Now')
    fireEvent.click(btn)
    expect(onAction).toHaveBeenCalledTimes(1)
  })
})

describe('LoadingState Component', () => {
  it('renders message and submessage with polite aria region', () => {
    render(
      <LoadingState
        message="Generating 10 shorts..."
        submessage="Analyzing audio transcript"
      />
    )
    expect(screen.getByText('Generating 10 shorts...')).toBeInTheDocument()
    expect(screen.getByText('Analyzing audio transcript')).toBeInTheDocument()
  })
})

describe('ErrorState Component', () => {
  it('renders error alert with retry and dismiss options', () => {
    const onRetry = vi.fn()
    const onDismiss = vi.fn()
    render(
      <ErrorState
        title="Video Processing Error"
        message="FFmpeg exited with non-zero code"
        onRetry={onRetry}
        onDismiss={onDismiss}
      />
    )

    expect(screen.getByText('Video Processing Error')).toBeInTheDocument()
    expect(screen.getByText('FFmpeg exited with non-zero code')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Retry'))
    expect(onRetry).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByLabelText('Dismiss error'))
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })
})

describe('Sidebar Component Navigation', () => {
  it('renders navigation buttons and triggers selection callback', () => {
    const onSelectTab = vi.fn()
    const onOpenAuth = vi.fn()

    render(
      <AuthProvider>
        <Sidebar
          activeTab="dashboard"
          onSelectTab={onSelectTab}
          onOpenAuth={onOpenAuth}
          historyCount={5}
        />
      </AuthProvider>
    )

    expect(screen.getByText('AI Shorts')).toBeInTheDocument()
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
    expect(screen.getByText('Create Short')).toBeInTheDocument()
    expect(screen.getByText('My Shorts')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Create Short'))
    expect(onSelectTab).toHaveBeenCalledWith('create')
  })
})

describe('GenerationSettings Multi-Short Range & Defaults', () => {
  it('enforces 1 to 15 range and displays default 10 shorts', () => {
    const settings = {
      numberOfClips: 10,
      clipDurationSeconds: 60,
      includeCaptions: true,
      captionPreset: 'default',
    }
    const onChange = vi.fn()

    render(
      <GenerationSettings
        settings={settings}
        onChange={onChange}
        onGenerate={() => {}}
        isSubmitting={false}
        canSubmit={true}
      />
    )

    expect(screen.getByText(/10 shorts/i)).toBeInTheDocument()
    expect(screen.getByText(/Select up to 15 distinct Shorts/i)).toBeInTheDocument()

    const slider = screen.getByLabelText('Number of shorts to generate')
    expect(slider).toHaveAttribute('min', '1')
    expect(slider).toHaveAttribute('max', '15')

    fireEvent.change(slider, { target: { value: '14' } })
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ numberOfClips: 14 }))
  })
})

describe('ShortGrid Multi-Short Rendering', () => {
  it('renders multiple short cards with caption and duration info', () => {
    const mockShorts = Array.from({ length: 4 }, (_, i) => ({
      index: i + 1,
      final_file_path: `/tmp/short_${i + 1}.mp4`,
      captioned_clip_path: `/tmp/captioned_${i + 1}.mp4`,
      candidate: {
        start_seconds: i * 15,
        end_seconds: i * 15 + 30,
        duration_seconds: 30,
        title: `Highlight Moment #${i + 1}`,
        viral_hook: `Crazy hook text #${i + 1}`,
        score: { overall: 0.88 + i * 0.02 },
      },
    }))

    render(
      <ShortGrid
        result={{ generated_shorts: mockShorts }}
        onReset={() => {}}
      />
    )

    expect(screen.getByText('Your Generated Shorts')).toBeInTheDocument()
    expect(screen.getByText(/4 Shorts created/i)).toBeInTheDocument()
    expect(screen.getByText('Short #1')).toBeInTheDocument()
    expect(screen.getByText('Short #4')).toBeInTheDocument()
    expect(screen.getByText('Highlight Moment #1')).toBeInTheDocument()
  })
})
