import React, { useState, useEffect, useRef } from 'react'
import { AppShell } from './layouts/AppShell'
import { Navbar } from './components/Navbar'
import { DashboardPage } from './pages/DashboardPage'
import { CreateShortPage } from './pages/CreateShortPage'
import { MyShortsPage } from './pages/MyShortsPage'
import { GenerationProgress } from './components/generation/GenerationProgress'
import { ShortGrid } from './components/results/ShortGrid'
import { ErrorState } from './components/ui/ErrorState'
import { JobHistoryModal } from './components/JobHistoryModal'
import { AuthModal } from './components/AuthModal'
import { uploadVideo, createJob, getJob, listJobs } from './api/client'
import { AuthProvider, useAuth } from './context/AuthContext'

const HISTORY_STORAGE_PREFIX = 'ai_shorts_generator_history_v1'
const ACTIVE_JOB_STORAGE_PREFIX = 'ai_shorts_active_job_id'
const MAX_CONSECUTIVE_POLL_FAILURES = 3

export function getHistoryStorageKeys(user) {
  const ownerScope = user?.user_id ? `user:${user.user_id}` : 'anonymous'
  return {
    historyKey: `${HISTORY_STORAGE_PREFIX}:${ownerScope}`,
    activeJobKey: `${ACTIVE_JOB_STORAGE_PREFIX}:${ownerScope}`,
  }
}

function getJobState(job) {
  if (!job) return 'idle'
  if (job.status === 'completed') return 'results'
  if (job.status === 'failed') return 'failed'
  return 'processing'
}

function MainApp() {
  const [activeTab, setActiveTab] = useState('create') // 'dashboard' | 'create' | 'my-shorts'
  const [sourceType, setSourceType] = useState('upload') // 'upload' | 'url'
  const [selectedFile, setSelectedFile] = useState(null)
  const [uploadedData, setUploadedData] = useState(null)
  const [videoUrl, setVideoUrl] = useState('')
  const [isUploading, setIsUploading] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const [settings, setSettings] = useState({
    numberOfClips: 10,
    clipDurationSeconds: 60,
    includeCaptions: true,
    captionPreset: 'default',
    enableKaraoke: true,
    minClipDuration: 30,
    maxClipDuration: 120,
  })

  const [currentJob, setCurrentJob] = useState(null)
  const [jobState, setJobState] = useState('idle') // 'idle' | 'processing' | 'results' | 'failed'
  const [error, setError] = useState(null)

  const [history, setHistory] = useState([])
  const [isHistoryOpen, setIsHistoryOpen] = useState(false)
  const [isAuthOpen, setIsAuthOpen] = useState(false)

  const { user, loading: authLoading } = useAuth()
  const { historyKey, activeJobKey } = getHistoryStorageKeys(user)
  const pollingRef = useRef(null)
  const pollingFailuresRef = useRef(0)

  // Load history and restore active job on mount or refresh
  useEffect(() => {
    if (authLoading) return undefined

    setHistory([])
    setCurrentJob(null)
    setJobState('idle')
    setError(null)

    async function initJobs() {
      let loadedJobs = []

      // 1. Fetch user-scoped jobs if authenticated
      if (user) {
        try {
          const userJobs = await listJobs()
          if (Array.isArray(userJobs) && userJobs.length > 0) {
            loadedJobs = userJobs
            setHistory(userJobs)
          }
        } catch {
          // Fallback to localStorage
        }
      }

      // 2. Load stored local history
      try {
        const stored = localStorage.getItem(historyKey)
        if (stored) {
          const parsedHistory = JSON.parse(stored)
          if (Array.isArray(parsedHistory) && parsedHistory.length > 0) {
            if (loadedJobs.length === 0) {
              loadedJobs = parsedHistory
              setHistory(parsedHistory)
            }
          }
        }
      } catch {
        // Ignore parse error
      }

      // 3. Restore persisted active job ID if present
      const persistedActiveJobId = localStorage.getItem(activeJobKey)
      if (persistedActiveJobId) {
        try {
          const fetchedJob = await getJob(persistedActiveJobId)
          if (fetchedJob && fetchedJob.job_id) {
            setCurrentJob(fetchedJob)
            setJobState(getJobState(fetchedJob))
            saveToHistory(fetchedJob)
            return
          }
        } catch {
          // Job might no longer exist
        }
      }

      // 4. Otherwise check for active in-progress job in loaded jobs
      if (loadedJobs.length > 0) {
        const inProgress = [...loadedJobs]
          .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))
          .find((j) => j && j.job_id && j.status !== 'completed' && j.status !== 'failed')

        if (inProgress) {
          setCurrentJob(inProgress)
          setJobState(getJobState(inProgress))
          localStorage.setItem(activeJobKey, inProgress.job_id)
        }
      }
    }

    initJobs()
    return undefined
  }, [user, authLoading, historyKey, activeJobKey])

  // Save history to localStorage
  const saveToHistory = (jobRecord, sourceName) => {
    if (!jobRecord || !jobRecord.job_id) return
    setHistory((prev) => {
      const existingIdx = prev.findIndex((j) => j.job_id === jobRecord.job_id)
      const updatedItem = {
        ...jobRecord,
        sourceName: sourceName || prev[existingIdx]?.sourceName || jobRecord.sourceName || 'Video',
      }

      let nextList = []
      if (existingIdx >= 0) {
        nextList = [...prev]
        nextList[existingIdx] = updatedItem
      } else {
        nextList = [updatedItem, ...prev.slice(0, 29)]
      }

      try {
        localStorage.setItem(historyKey, JSON.stringify(nextList))
      } catch {
        // Storage quota exceed fallback
      }
      return nextList
    })
  }

  // Handle file selection and automatic server upload
  const handleFileSelected = async (file) => {
    if (isUploading || isSubmitting) return
    setSelectedFile(file)
    setError(null)
    setIsUploading(true)

    try {
      const data = await uploadVideo(file)
      setUploadedData(data)
    } catch (err) {
      setError(err.message || 'Failed to upload video')
      setSelectedFile(null)
      setUploadedData(null)
    } finally {
      setIsUploading(false)
    }
  }

  const handleClearFile = () => {
    if (isUploading || isSubmitting) return
    setSelectedFile(null)
    setUploadedData(null)
    setError(null)
  }

  const handleReset = () => {
    if (pollingRef.current) clearTimeout(pollingRef.current)
    pollingRef.current = null
    pollingFailuresRef.current = 0
    localStorage.removeItem(activeJobKey)
    setJobState('idle')
    setCurrentJob(null)
    setError(null)
    setSelectedFile(null)
    setUploadedData(null)
    setVideoUrl('')
    setIsSubmitting(false)
  }

  // Handle generation submission
  const handleGenerate = async () => {
    if (isSubmitting || isUploading) return // Prevent duplicate submissions

    if (sourceType === 'upload') {
      if (!uploadedData?.asset_id) {
        setError('Please select and upload a valid video file first.')
        return
      }
    } else {
      if (!videoUrl || !videoUrl.trim()) {
        setError('Please enter a valid YouTube URL.')
        return
      }
      if (!/^https?:\/\//i.test(videoUrl.trim())) {
        setError('YouTube URL must begin with http:// or https://')
        return
      }
    }

    setIsSubmitting(true)
    setError(null)

    const payload = {
      source: {
        type: sourceType === 'upload' ? 'upload' : 'youtube',
        ...(sourceType === 'upload'
          ? { asset_id: uploadedData.asset_id }
          : { location: videoUrl.trim() }),
      },
      clip_duration_seconds: Number(settings.clipDurationSeconds) || 60,
      number_of_clips: Math.min(15, Math.max(1, Number(settings.numberOfClips) || 10)),
      include_captions: Boolean(settings.includeCaptions !== false),
      caption_preset: settings.captionPreset || 'default',
      enable_karaoke: Boolean(settings.enableKaraoke !== false),
      min_clip_duration: Number(settings.minClipDuration) || 30,
      max_clip_duration: Number(settings.maxClipDuration) || 120,
      vertical_width: 1080,
      vertical_height: 1920,
    }

    try {
      const job = await createJob(payload)
      setCurrentJob(job)
      setJobState('processing')
      localStorage.setItem(activeJobKey, job.job_id)
      saveToHistory(job, selectedFile?.name || (videoUrl ? 'YouTube Video' : 'Generated Short'))
    } catch (err) {
      setError(err.message || 'Failed to start shorts generation job.')
    } finally {
      setIsSubmitting(false)
    }
  }

  // Polling loop for active jobs
  useEffect(() => {
    if (jobState !== 'processing' || !currentJob?.job_id) {
      if (pollingRef.current) clearTimeout(pollingRef.current)
      pollingRef.current = null
      return
    }

    let disposed = false
    const poll = async () => {
      let shouldContinue = true
      try {
        const latestJob = await getJob(currentJob.job_id)
        if (disposed) return
        if (pollingFailuresRef.current >= MAX_CONSECUTIVE_POLL_FAILURES) {
          setError(null)
        }
        pollingFailuresRef.current = 0
        setCurrentJob(latestJob)
        saveToHistory(latestJob, selectedFile?.name)

        if (latestJob.status === 'completed') {
          setJobState('results')
          localStorage.removeItem(activeJobKey)
          shouldContinue = false
        } else if (latestJob.status === 'failed') {
          setJobState('failed')
          setError(latestJob.error || 'Job failed during video processing')
          localStorage.removeItem(activeJobKey)
          shouldContinue = false
        }
      } catch (err) {
        if (disposed) return
        pollingFailuresRef.current += 1
        if (pollingFailuresRef.current >= MAX_CONSECUTIVE_POLL_FAILURES) {
          setError(err?.message || 'Unable to refresh job status. Retrying in the background.')
        }
      } finally {
        if (!disposed && shouldContinue) {
          pollingRef.current = setTimeout(poll, 1800)
        } else {
          pollingRef.current = null
        }
      }
    }

    poll()
    return () => {
      disposed = true
      if (pollingRef.current) clearTimeout(pollingRef.current)
      pollingRef.current = null
    }
  }, [jobState, currentJob?.job_id, activeJobKey])

  const handleSelectHistoryJob = async (jobItem) => {
    if (!jobItem || !jobItem.job_id) return
    localStorage.setItem(activeJobKey, jobItem.job_id)
    setIsHistoryOpen(false)

    try {
      const freshJob = await getJob(jobItem.job_id)
      setCurrentJob(freshJob)
      setJobState(getJobState(freshJob))
      saveToHistory(freshJob)
    } catch {
      // Fall back to cached copy
      setCurrentJob(jobItem)
      setJobState(getJobState(jobItem))
    }
  }

  const handleClearHistory = () => {
    localStorage.removeItem(historyKey)
    localStorage.removeItem(activeJobKey)
    setHistory([])
  }

  return (
    <AppShell
      activeTab={activeTab}
      onSelectTab={(tab) => {
        setActiveTab(tab)
        if (jobState === 'failed') {
          setJobState('idle')
        }
      }}
      onOpenAuth={() => setIsAuthOpen(true)}
      historyCount={history.length}
    >
      {/* Top Navbar */}
      <Navbar
        onOpenHistory={() => setIsHistoryOpen(true)}
        historyCount={history.length}
        onOpenAuth={() => setIsAuthOpen(true)}
      />

      {error && (
        <ErrorState
          title="Operation Failed"
          message={error}
          onRetry={null}
          onDismiss={() => setError(null)}
        />
      )}

      {/* Active Job State takes precedence for Processing and Results */}
      {jobState === 'processing' && (
        <GenerationProgress
          job={currentJob}
          onStartOver={handleReset}
        />
      )}

      {jobState === 'results' && currentJob?.result && (
        <ShortGrid
          result={currentJob.result}
          jobId={currentJob.job_id}
          onReset={handleReset}
        />
      )}

      {jobState === 'failed' && (
        <div style={{ textAlign: 'center', marginTop: '2rem' }}>
          <button type="button" className="btn-primary" onClick={handleReset}>
            Create Another Short
          </button>
        </div>
      )}

      {/* Idle / Standard Tab Views */}
      {jobState === 'idle' && (
        <>
          {activeTab === 'dashboard' && (
            <DashboardPage
              onNavigateCreate={() => setActiveTab('create')}
              history={history}
              onSelectJob={handleSelectHistoryJob}
              currentJob={currentJob}
            />
          )}

          {activeTab === 'create' && (
            <CreateShortPage
              sourceType={sourceType}
              setSourceType={setSourceType}
              selectedFile={selectedFile}
              uploadedData={uploadedData}
              videoUrl={videoUrl}
              setVideoUrl={setVideoUrl}
              isUploading={isUploading}
              isSubmitting={isSubmitting}
              onFileSelected={handleFileSelected}
              onClearFile={handleClearFile}
              settings={settings}
              setSettings={setSettings}
              onGenerate={handleGenerate}
              error={null}
            />
          )}

          {activeTab === 'my-shorts' && (
            <MyShortsPage
              history={history}
              onSelectJob={handleSelectHistoryJob}
              onNavigateCreate={() => setActiveTab('create')}
            />
          )}
        </>
      )}

      <JobHistoryModal
        isOpen={isHistoryOpen}
        onClose={() => setIsHistoryOpen(false)}
        history={history}
        onSelectJob={handleSelectHistoryJob}
        onClearHistory={handleClearHistory}
      />

      <AuthModal
        isOpen={isAuthOpen}
        onClose={() => setIsAuthOpen(false)}
      />
    </AppShell>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <MainApp />
    </AuthProvider>
  )
}
