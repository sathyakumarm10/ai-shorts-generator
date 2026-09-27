import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  CAPTION_PRESETS,
  GenerationSettings,
} from '../components/generation/GenerationSettings'
import { GenerationProgress } from '../components/generation/GenerationProgress'
import { JobHistoryModal } from '../components/JobHistoryModal'
import { SubtitleEditor } from '../components/results/SubtitleEditor'
import { SubtitleStylePicker } from '../components/results/SubtitleStylePicker'
import { VideoSourceSelector } from '../components/video/VideoSourceSelector'

describe('Phase 1C truthful UI contracts', () => {
  it('submits only backend-supported IDs for every visible caption preset', () => {
    const onChange = vi.fn()
    const settings = {
      numberOfClips: 1,
      clipDurationSeconds: 30,
      includeCaptions: true,
      captionPreset: 'default',
    }
    render(
      <GenerationSettings
        settings={settings}
        onChange={onChange}
        onGenerate={() => {}}
        isSubmitting={false}
        canSubmit={true}
      />
    )

    expect(CAPTION_PRESETS.map((preset) => preset.id)).toEqual([
      'default',
      'punch_pop',
      'clean_creator',
      'word_highlight',
    ])
    for (const preset of CAPTION_PRESETS) {
      fireEvent.click(screen.getByRole('button', { name: new RegExp(preset.name, 'i') }))
      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ captionPreset: preset.id })
      )
    }
  })

  it('offers start-over navigation without fake cancellation wording', () => {
    const onStartOver = vi.fn()
    render(
      <GenerationProgress
        job={{ status: 'transcribing', progress_percent: 35, message: 'Transcribing' }}
        onStartOver={onStartOver}
      />
    )

    expect(screen.queryByText(/cancel/i)).not.toBeInTheDocument()
    expect(screen.getByText(/job will continue processing in the background/i)).toBeInTheDocument()
    expect(screen.getByText('Estimated 35%')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /start another project/i }))
    expect(onStartOver).toHaveBeenCalledTimes(1)
  })

  it('marks subtitle editing and style changes as preview-only', () => {
    render(
      <>
        <SubtitleStylePicker
          currentStyle="default"
          renderedStyle="punch_pop"
          onSelectStyle={() => {}}
        />
        <SubtitleEditor
          captionTrack={{ segments: [{ start_seconds: 0, end_seconds: 2, text: 'Hello' }] }}
          duration={5}
          onSaveTrack={vi.fn()}
        />
      </>
    )

    expect(screen.getByText('Preview Style')).toBeInTheDocument()
    expect(screen.getByText(/exported video remains rendered with punch_pop captions/i)).toBeInTheDocument()
    expect(screen.getByText(/edits are not saved after reload/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /update preview draft/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^save subtitles$/i })).not.toBeInTheDocument()
  })

  it('labels history clearing as browser-only and non-destructive', () => {
    render(
      <JobHistoryModal
        isOpen
        onClose={() => {}}
        history={[{ job_id: 'job-1', status: 'completed', created_at: new Date().toISOString() }]}
        onSelectJob={() => {}}
        onClearHistory={() => {}}
      />
    )

    expect(screen.getByRole('button', { name: /clear browser history/i })).toBeInTheDocument()
    expect(screen.getByText(/backend jobs and generated media are not deleted/i)).toBeInTheDocument()
  })

  it('describes the URL source as YouTube-only', () => {
    render(
      <VideoSourceSelector
        sourceType="url"
        setSourceType={() => {}}
        videoUrl=""
        setVideoUrl={() => {}}
        onFileSelected={() => {}}
      />
    )

    expect(screen.getByText('YouTube Video URL')).toBeInTheDocument()
    expect(screen.getByText(/other web and direct-stream URLs are not supported/i)).toBeInTheDocument()
    expect(screen.queryByText(/Direct MP4 or web stream URL/i)).not.toBeInTheDocument()
  })
})

describe('VideoSourceSelector object URL lifecycle', () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn((file) => `blob:${file.name}`)
    URL.revokeObjectURL = vi.fn()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('revokes object URLs when the file changes and on unmount', () => {
    const first = new File(['one'], 'one.mp4', { type: 'video/mp4' })
    const second = new File(['two'], 'two.mp4', { type: 'video/mp4' })
    const props = {
      sourceType: 'upload',
      setSourceType: () => {},
      uploadedData: null,
      isUploading: false,
      onFileSelected: () => {},
      onClearFile: () => {},
    }

    const { rerender, unmount } = render(
      <VideoSourceSelector {...props} selectedFile={first} />
    )
    rerender(<VideoSourceSelector {...props} selectedFile={second} />)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:one.mp4')

    unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:two.mp4')
  })
})
