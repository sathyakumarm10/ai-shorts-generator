import React from 'react'
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App, { getHistoryStorageKeys } from '../App'
import { getJob } from '../api/client'

vi.mock('../api/client', () => ({
  uploadVideo: vi.fn(),
  createJob: vi.fn(),
  getJob: vi.fn(),
  listJobs: vi.fn().mockResolvedValue([]),
  getCurrentUser: vi.fn().mockResolvedValue(null),
  login: vi.fn(),
  register: vi.fn(),
  logout: vi.fn(),
  refreshTokens: vi.fn(),
  getMediaUrl: vi.fn(() => '/api/media?file_path=test.mp4'),
}))

describe('App job history resume', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('restores an active job from storage and resumes polling after refresh', async () => {
    const activeJob = {
      job_id: 'job-123',
      status: 'transcribing',
      progress_percent: 35,
      message: 'Transcribing speech with AI',
      created_at: new Date().toISOString(),
    }

    localStorage.setItem(getHistoryStorageKeys(null).historyKey, JSON.stringify([activeJob]))

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

    expect(await screen.findByText('Creating Your Shorts')).toBeInTheDocument()
    expect(await screen.findByText('Your Generated Shorts')).toBeInTheDocument()
  })

  it('uses distinct browser history keys for anonymous and authenticated owners', () => {
    expect(getHistoryStorageKeys(null).historyKey).not.toBe(
      getHistoryStorageKeys({ user_id: 'user-a' }).historyKey
    )
    expect(getHistoryStorageKeys({ user_id: 'user-a' }).historyKey).not.toBe(
      getHistoryStorageKeys({ user_id: 'user-b' }).historyKey
    )
  })

  it('stops polling after a terminal job response', async () => {
    vi.useFakeTimers()
    const activeJob = {
      job_id: 'job-terminal',
      status: 'transcribing',
      progress_percent: 35,
      created_at: new Date().toISOString(),
    }
    localStorage.setItem(getHistoryStorageKeys(null).historyKey, JSON.stringify([activeJob]))
    vi.mocked(getJob).mockResolvedValue({
      ...activeJob,
      status: 'completed',
      progress_percent: 100,
      result: { generated_shorts: [] },
    })

    render(<App />)
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000)
    })

    expect(getJob).toHaveBeenCalledTimes(1)
  })

  it('surfaces persistent polling failures while continuing background retries', async () => {
    vi.useFakeTimers()
    const activeJob = {
      job_id: 'job-network-error',
      status: 'transcribing',
      progress_percent: 35,
      created_at: new Date().toISOString(),
    }
    localStorage.setItem(getHistoryStorageKeys(null).historyKey, JSON.stringify([activeJob]))
    vi.mocked(getJob).mockRejectedValue(new Error('Status service unavailable'))

    render(<App />)
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    for (let attempt = 0; attempt < 4; attempt += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1800)
        await Promise.resolve()
      })
    }

    expect(getJob.mock.calls.length).toBeGreaterThanOrEqual(3)
    expect(screen.getByText('Status service unavailable')).toBeInTheDocument()
  })
})
