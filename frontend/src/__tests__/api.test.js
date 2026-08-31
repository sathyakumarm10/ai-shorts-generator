import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  uploadVideo,
  createJob,
  getJob,
  getMediaUrl,
  login,
  register,
  getCurrentUser,
  logout,
  getAuthToken,
  setAuthToken,
} from '../api/client'

describe('API Client Layer', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('uploadVideo sends FormData and returns response json', async () => {
    const mockFile = new File(['test'], 'test.mp4', { type: 'video/mp4' })
    const mockResp = { file_path: '/server/path.mp4', filename: 'test.mp4', file_size_bytes: 4 }

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResp,
    })

    const result = await uploadVideo(mockFile)
    expect(global.fetch).toHaveBeenCalledWith('/api/upload', expect.objectContaining({ method: 'POST' }))
    expect(result).toEqual(mockResp)
  })

  it('uploadVideo throws on server error', async () => {
    const mockFile = new File(['test'], 'test.mp4', { type: 'video/mp4' })

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'Unsupported format' }),
    })

    await expect(uploadVideo(mockFile)).rejects.toThrow('Unsupported format')
  })

  it('createJob sends JSON payload and returns JobRecord', async () => {
    const payload = { source: { type: 'upload', location: '/path.mp4' }, clip_duration_seconds: 30 }
    const mockJob = { job_id: 'job-abc', status: 'queued', progress_percent: 0 }

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockJob,
    })

    const result = await createJob(payload)
    expect(global.fetch).toHaveBeenCalledWith('/api/jobs', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify(payload),
    }))
    expect(result.job_id).toBe('job-abc')
  })

  it('getJob requests job status by ID', async () => {
    const mockJob = { job_id: 'job-123', status: 'completed', progress_percent: 100 }

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockJob,
    })

    const result = await getJob('job-123')
    expect(global.fetch).toHaveBeenCalledWith('/api/jobs/job-123')
    expect(result.status).toBe('completed')
  })

  it('getMediaUrl formats safe query parameter URL', () => {
    const url = getMediaUrl('C:\\downloads\\short_1.mp4')
    expect(url).toBe('/api/media?file_path=C%3A%5Cdownloads%5Cshort_1.mp4')
    expect(getMediaUrl('')).toBe('')
  })

  it('register stores access token and returns user payload', async () => {
    const mockToken = {
      access_token: 'fake-jwt-token-123',
      user: { user_id: 'u1', email: 'test@example.com' },
    }
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockToken,
    })

    const res = await register('test@example.com', 'password123')
    expect(res.access_token).toBe('fake-jwt-token-123')
    expect(getAuthToken()).toBe('fake-jwt-token-123')
  })

  it('login stores access token on success', async () => {
    const mockToken = {
      access_token: 'fake-jwt-login-456',
      user: { user_id: 'u2', email: 'user@example.com' },
    }
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockToken,
    })

    const res = await login('user@example.com', 'secret')
    expect(res.access_token).toBe('fake-jwt-login-456')
    expect(getAuthToken()).toBe('fake-jwt-login-456')
  })

  it('getCurrentUser includes Authorization header and returns profile', async () => {
    setAuthToken('bearer-token-789')
    const mockProfile = { user_id: 'u3', email: 'me@example.com' }
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockProfile,
    })

    const profile = await getCurrentUser()
    expect(global.fetch).toHaveBeenCalledWith('/api/auth/me', {
      headers: { Authorization: 'Bearer bearer-token-789' },
    })
    expect(profile.email).toBe('me@example.com')
  })

  it('logout clears stored token and calls endpoint', async () => {
    setAuthToken('token-to-clear')
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })

    await logout()
    expect(getAuthToken()).toBe('')
  })
})
