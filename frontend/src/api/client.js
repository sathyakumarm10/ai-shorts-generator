/**
 * Centralized API Client for AI Shorts Generator with JWT Authentication
 */

const API_BASE = '' // Relative path works with Vite proxy or production serving
const TOKEN_KEY = 'ai_shorts_auth_token'

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

function getAuthHeaders(extraHeaders = {}) {
  const token = getAuthToken()
  const headers = { ...extraHeaders }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
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
  return data
}

export async function getCurrentUser() {
  const token = getAuthToken()
  if (!token) return null
  const response = await fetch(`${API_BASE}/api/auth/me`, {
    headers: getAuthHeaders(),
  })
  if (!response.ok) {
    setAuthToken(null)
    return null
  }
  return response.json()
}

export async function logout() {
  try {
    await fetch(`${API_BASE}/api/auth/logout`, {
      method: 'POST',
      headers: getAuthHeaders(),
    })
  } catch {
    // Ignore network errors on logout
  }
  setAuthToken(null)
}

export async function uploadVideo(file) {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${API_BASE}/api/upload`, {
    method: 'POST',
    headers: getAuthHeaders(),
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
  const response = await fetch(`${API_BASE}/api/jobs`, {
    method: 'POST',
    headers: getAuthHeaders({
      'Content-Type': 'application/json',
    }),
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
  const headers = getAuthHeaders()
  const init = Object.keys(headers).length > 0 ? { headers } : null
  const url = `${API_BASE}/api/jobs/${encodeURIComponent(jobId)}`
  const response = init ? await fetch(url, init) : await fetch(url)

  if (!response.ok) {
    if (response.status === 401) {
      setAuthToken(null)
    }
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
  const headers = getAuthHeaders()
  const init = Object.keys(headers).length > 0 ? { headers } : null
  const url = `${API_BASE}/api/jobs`
  const response = init ? await fetch(url, init) : await fetch(url)
  if (!response.ok) {
    if (response.status === 401) {
      setAuthToken(null)
    }
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
