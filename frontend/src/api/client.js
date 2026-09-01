/**
 * Centralized API Client for AI Shorts Generator with JWT Authentication,
 * Token Rotation, Refresh Token Persistence, and Automatic 401 Re-Authentication.
 */

const API_BASE = '' // Relative path works with Vite proxy or production serving
const TOKEN_KEY = 'ai_shorts_auth_token'
const REFRESH_TOKEN_KEY = 'ai_shorts_refresh_token'

export function getAuthToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setAuthToken(token) {
  try {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token)
    } else {
      localStorage.removeItem(TOKEN_KEY)
    }
  } catch {
    // Storage quota or privacy mode
  }
}

export function getRefreshToken() {
  try {
    return localStorage.getItem(REFRESH_TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setRefreshToken(token) {
  try {
    if (token) {
      localStorage.setItem(REFRESH_TOKEN_KEY, token)
    } else {
      localStorage.removeItem(REFRESH_TOKEN_KEY)
    }
  } catch {
    // Storage quota or privacy mode
  }
}

export function clearAuthTokens() {
  setAuthToken(null)
  setRefreshToken(null)
}

function getAuthHeaders(extraHeaders = {}) {
  const token = getAuthToken()
  const headers = { ...extraHeaders }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}

let refreshPromise = null

export async function refreshTokens() {
  const currentRefreshToken = getRefreshToken()
  if (!currentRefreshToken) {
    clearAuthTokens()
    return null
  }

  // Prevent multiple simultaneous refresh calls (refresh stampede)
  if (refreshPromise) {
    return refreshPromise
  }

  refreshPromise = (async () => {
    try {
      const response = await fetch(`${API_BASE}/api/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: currentRefreshToken }),
      })

      if (!response.ok) {
        clearAuthTokens()
        return null
      }

      const data = await response.json()
      if (data.access_token) {
        setAuthToken(data.access_token)
      }
      if (data.refresh_token) {
        setRefreshToken(data.refresh_token)
      }
      return data
    } catch {
      clearAuthTokens()
      return null
    } finally {
      refreshPromise = null
    }
  })()

  return refreshPromise
}

/**
 * Authenticated Fetch wrapper with automatic token refresh on 401 Unauthorized responses.
 */
export async function authFetch(url, options = {}) {
  const headers = getAuthHeaders(options.headers || {})
  let response = await fetch(url, { ...options, headers })

  if (response.status === 401 && getRefreshToken()) {
    const refreshed = await refreshTokens()
    if (refreshed && refreshed.access_token) {
      const retryHeaders = getAuthHeaders(options.headers || {})
      response = await fetch(url, { ...options, headers: retryHeaders })
    }
  }

  return response
}

export async function register(email, password) {
  const response = await fetch(`${API_BASE}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({}))
    throw new Error(err.detail || 'Registration failed')
  }
  const data = await response.json()
  if (data.access_token) {
    setAuthToken(data.access_token)
  }
  if (data.refresh_token) {
    setRefreshToken(data.refresh_token)
  }
  return data
}

export async function login(email, password) {
  const response = await fetch(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({}))
    throw new Error(err.detail || 'Login failed')
  }
  const data = await response.json()
  if (data.access_token) {
    setAuthToken(data.access_token)
  }
  if (data.refresh_token) {
    setRefreshToken(data.refresh_token)
  }
  return data
}

export async function getCurrentUser() {
  const token = getAuthToken()
  const refreshToken = getRefreshToken()
  if (!token && !refreshToken) return null

  const response = await authFetch(`${API_BASE}/api/auth/me`)
  if (!response.ok) {
    clearAuthTokens()
    return null
  }
  return response.json()
}

export async function logout() {
  try {
    await authFetch(`${API_BASE}/api/auth/logout`, {
      method: 'POST',
    })
  } catch {
    // Ignore network errors on logout
  }
  clearAuthTokens()
}

export async function listSessions() {
  const response = await authFetch(`${API_BASE}/api/auth/sessions`)
  if (!response.ok) {
    return []
  }
  return response.json()
}

export async function revokeSession(tokenId) {
  const response = await authFetch(`${API_BASE}/api/auth/sessions/${encodeURIComponent(tokenId)}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error('Failed to revoke session')
  }
  return response.json()
}

export async function uploadVideo(file) {
  const formData = new FormData()
  formData.append('file', file)

  const response = await authFetch(`${API_BASE}/api/upload`, {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    let errorDetail = 'Video upload failed'
    try {
      const errJson = await response.json()
      errorDetail = errJson.detail || errorDetail
    } catch {
      // Ignore JSON parse errors
    }
    throw new Error(errorDetail)
  }

  return response.json()
}

export async function createJob(requestPayload) {
  const response = await authFetch(`${API_BASE}/api/jobs`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(requestPayload),
  })

  if (!response.ok) {
    let errorDetail = 'Failed to submit generation job'
    try {
      const errJson = await response.json()
      if (Array.isArray(errJson.detail)) {
        errorDetail = errJson.detail.map(d => d.msg || d.message).join(', ')
      } else if (errJson.detail) {
        errorDetail = errJson.detail
      }
    } catch {
      // Ignore JSON parse error
    }
    throw new Error(errorDetail)
  }

  return response.json()
}

export async function getJob(jobId) {
  const url = `${API_BASE}/api/jobs/${encodeURIComponent(jobId)}`
  const response = await authFetch(url)

  if (!response.ok) {
    let errorDetail = 'Failed to fetch job status'
    try {
      const errJson = await response.json()
      errorDetail = errJson.detail || errorDetail
    } catch {
      // Ignore JSON parse error
    }
    throw new Error(errorDetail)
  }

  return response.json()
}

export async function listJobs() {
  const url = `${API_BASE}/api/jobs`
  const response = await authFetch(url)
  if (!response.ok) {
    return []
  }
  return response.json()
}

export function getMediaUrl(filePath) {
  if (!filePath) return ''
  if (filePath.startsWith('http://') || filePath.startsWith('https://')) {
    return filePath
  }
  return `${API_BASE}/api/media?file_path=${encodeURIComponent(filePath)}`
}
