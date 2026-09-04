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

const STORAGE_KEY = 'ai_shorts_generator_history_v1'
const ACTIVE_JOB_KEY = 'ai_shorts_active_job_id'

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

  const { user } = useAuth()
  const pollingRef = useRef(null)

  // Load history and restore active job on mount or refresh
  useEffect(() => {
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
        const stored = localStorage.getItem(STORAGE_KEY)
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
      const persistedActiveJobId = localStorage.getItem(ACTIVE_JOB_KEY)
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
          localStorage.setItem(ACTIVE_JOB_KEY, inProgress.job_id)
        }
      }
    }

    initJobs()
  }, [user])

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
        localStorage.setItem(STORAGE_KEY, JSON.stringify(nextList))
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
    if (pollingRef.current) clearInterval(pollingRef.current)
    localStorage.removeItem(ACTIVE_JOB_KEY)
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
      if (!uploadedData?.file_path) {
        setError('Please select and upload a valid video file first.')
        return
      }
    } else {
      if (!videoUrl || !videoUrl.trim()) {
        setError('Please enter a valid video stream or YouTube URL.')
        return
      }
      if (!/^https?:\/\//i.test(videoUrl.trim())) {
        setError('Video URL must begin with http:// or https://')
        return
      }
    }

    setIsSubmitting(true)
    setError(null)

    const payload = {
      source: {
        type: sourceType === 'upload' ? 'upload' : 'youtube',
        location: sourceType === 'upload' ? uploadedData.file_path : videoUrl.trim(),
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
      localStorage.setItem(ACTIVE_JOB_KEY, job.job_id)
      saveToHistory(job, selectedFile?.name || (videoUrl ? 'Web Video' : 'Generated Short'))
    } catch (err) {
      setError(err.message || 'Failed to start shorts generation job.')
    } finally {
      setIsSubmitting(false)
    }
  }

  // Polling loop for active jobs
  useEffect(() => {
    if (jobState !== 'processing' || !currentJob?.job_id) {
      if (pollingRef.current) clearInterval(pollingRef.current)
      return
    }

    const poll = async () => {
      try {
        const latestJob = await getJob(currentJob.job_id)
        setCurrentJob(latestJob)
        saveToHistory(latestJob, selectedFile?.name)

        if (latestJob.status === 'completed') {
          setJobState('results')
          clearInterval(pollingRef.current)
        } else if (latestJob.status === 'failed') {
          setJobState('failed')
          setError(latestJob.error || 'Job failed during video processing')
          clearInterval(pollingRef.current)
        }
      } catch {
        // Network blip; continue polling
      }
    }

    poll()
    pollingRef.current = setInterval(poll, 1800)
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [jobState, currentJob?.job_id])

  const handleSelectHistoryJob = async (jobItem) => {
    if (!jobItem || !jobItem.job_id) return
    localStorage.setItem(ACTIVE_JOB_KEY, jobItem.job_id)
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
    localStorage.removeItem(STORAGE_KEY)
    localStorage.removeItem(ACTIVE_JOB_KEY)
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
          onRetry={jobState === 'failed' ? handleReset : null}
          onDismiss={() => setError(null)}
        />
      )}

      {/* Active Job State takes precedence for Processing and Results */}
      {jobState === 'processing' && (
        <GenerationProgress
          job={currentJob}
          onCancel={handleReset}
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
