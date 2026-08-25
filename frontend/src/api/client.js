/**
 * Centralized API Client for AI Shorts Generator
 */

const API_BASE = '' // Relative path works with Vite proxy or production serving

export async function uploadVideo(file) {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${API_BASE}/api/upload`, {
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
  const response = await fetch(`${API_BASE}/api/jobs`, {
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
  const response = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}`)

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

export function getMediaUrl(filePath) {
  if (!filePath) return ''
  return `${API_BASE}/api/media?file_path=${encodeURIComponent(filePath)}`
}
