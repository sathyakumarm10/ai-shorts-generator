import React from 'react'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../App'
import { getJob } from '../api/client'

vi.mock('../api/client', () => ({
  uploadVideo: vi.fn(),
  createJob: vi.fn(),
  getJob: vi.fn(),
  getMediaUrl: vi.fn(() => '/api/media?file_path=test.mp4'),
}))

describe('App job history resume', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('restores an active job from storage and resumes polling after refresh', async () => {
    const activeJob = {
      job_id: 'job-123',
      status: 'transcribing',
      progress_percent: 35,
      message: 'Transcribing speech with AI',
      created_at: new Date().toISOString(),
    }

    localStorage.setItem('ai_shorts_generator_history_v1', JSON.stringify([activeJob]))

    vi.mocked(getJob).mockResolvedValue({
      ...activeJob,
      status: 'completed',
      progress_percent: 100,
      result: {
        generated_shorts: [
          {
            index: 1,
            final_file_path: '/tmp/short_1.mp4',
            candidate: {
              start_seconds: 12,
              end_seconds: 40,
              duration_seconds: 28,
              text: 'This is the hook we want to keep.',
              score: { overall: 0.92 },
            },
          },
        ],
      },
    })

    render(<App />)

    expect(screen.getByText('Creating Your Shorts')).toBeInTheDocument()
    expect(await screen.findByText('Your Generated Shorts')).toBeInTheDocument()
  })
})
