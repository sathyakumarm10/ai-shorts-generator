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
  getRefreshToken,
  setRefreshToken,
  clearAuthTokens,
  refreshTokens,
  authFetch,
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
    expect(global.fetch).toHaveBeenCalledWith('/api/jobs/job-123', expect.any(Object))
    expect(result.status).toBe('completed')
  })

  it('getMediaUrl formats safe query parameter URL', () => {
    const url = getMediaUrl('C:\\downloads\\short_1.mp4')
    expect(url).toBe('/api/media?file_path=C%3A%5Cdownloads%5Cshort_1.mp4')
    expect(getMediaUrl('')).toBe('')
  })

  it('register stores access token and refresh token', async () => {
    const mockToken = {
      access_token: 'fake-jwt-token-123',
      refresh_token: 'rt_uuid_secret123',
      user: { user_id: 'u1', email: 'test@example.com' },
    }
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockToken,
    })

    const res = await register('test@example.com', 'password123')
    expect(res.access_token).toBe('fake-jwt-token-123')
    expect(getAuthToken()).toBe('fake-jwt-token-123')
    expect(getRefreshToken()).toBe('rt_uuid_secret123')
  })

  it('login stores access token and refresh token on success', async () => {
    const mockToken = {
      access_token: 'fake-jwt-login-456',
      refresh_token: 'rt_uuid_refresh456',
      user: { user_id: 'u2', email: 'user@example.com' },
    }
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockToken,
    })

    const res = await login('user@example.com', 'secret')
    expect(res.access_token).toBe('fake-jwt-login-456')
    expect(getAuthToken()).toBe('fake-jwt-login-456')
    expect(getRefreshToken()).toBe('rt_uuid_refresh456')
  })

  it('refreshTokens rotates tokens successfully', async () => {
    setRefreshToken('rt_old_refresh_token')
    const mockNewPair = {
      access_token: 'new-access-token-999',
      refresh_token: 'rt_new_refresh_token',
      user: { user_id: 'u1', email: 'user@example.com' },
    }

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockNewPair,
    })

    const result = await refreshTokens()
    expect(global.fetch).toHaveBeenCalledWith('/api/auth/refresh', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ refresh_token: 'rt_old_refresh_token' }),
    }))
    expect(getAuthToken()).toBe('new-access-token-999')
    expect(getRefreshToken()).toBe('rt_new_refresh_token')
    expect(result).toEqual(mockNewPair)
  })

  it('authFetch automatically refreshes token on 401 and retries request', async () => {
    setAuthToken('expired-access-token')
    setRefreshToken('valid-refresh-token')

    const mockRefreshed = {
      access_token: 'brand-new-access-token',
      refresh_token: 'brand-new-refresh-token',
      user: { user_id: 'u1' },
    }

    // 1st call: 401 Unauthorized
    // 2nd call (refresh): returns new tokens
    // 3rd call (retry original): 200 OK
    global.fetch = vi.fn()
      .mockResolvedValueOnce({
        status: 401,
        ok: false,
      })
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        json: async () => mockRefreshed,
      })
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        json: async () => ({ data: 'success' }),
      })

    const res = await authFetch('/api/jobs')
    expect(res.status).toBe(200)
    expect(getAuthToken()).toBe('brand-new-access-token')
    expect(getRefreshToken()).toBe('brand-new-refresh-token')
  })

  it('logout clears both access and refresh tokens', async () => {
    setAuthToken('token-to-clear')
    setRefreshToken('refresh-to-clear')
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })

    await logout()
    expect(getAuthToken()).toBe('')
    expect(getRefreshToken()).toBe('')
  })
})
