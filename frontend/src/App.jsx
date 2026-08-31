import React, { useState, useEffect, useRef } from 'react'
import { Navbar } from './components/Navbar'
import { HeroSection } from './components/HeroSection'
import { UploadZone } from './components/UploadZone'
import { GenerationSettings } from './components/GenerationSettings'
import { ProcessingView } from './components/ProcessingView'
import { ResultsGrid } from './components/ResultsGrid'
import { JobHistoryModal } from './components/JobHistoryModal'
import { AuthModal } from './components/AuthModal'
import { ErrorBanner } from './components/ErrorBanner'
import { uploadVideo, createJob, getJob, listJobs } from './api/client'
import { AuthProvider, useAuth } from './context/AuthContext'

const STORAGE_KEY = 'ai_shorts_generator_history_v1'

function getJobState(job) {
  if (!job) return 'idle'
  if (job.status === 'completed') return 'results'
  if (job.status === 'failed') return 'failed'
  return 'processing'
}

function MainApp() {
  const [selectedFile, setSelectedFile] = useState(null)
  const [uploadedData, setUploadedData] = useState(null)
  const [isUploading, setIsUploading] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const [settings, setSettings] = useState({
    numberOfClips: 3,
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

  // Fetch jobs for authenticated user or fallback to localStorage
  useEffect(() => {
    async function loadUserJobs() {
      if (user) {
        try {
          const userJobs = await listJobs()
          if (Array.isArray(userJobs) && userJobs.length > 0) {
            setHistory(userJobs)
            const active = userJobs.find(j => j.status !== 'completed' && j.status !== 'failed')
            if (active) {
              setCurrentJob(active)
              setJobState(getJobState(active))
            }
            return
          }
        } catch {
          // fallback
        }
      }

      try {
        const stored = localStorage.getItem(STORAGE_KEY)
        if (!stored) return
        const parsedHistory = JSON.parse(stored)
        if (!Array.isArray(parsedHistory)) return
        setHistory(parsedHistory)

        const activeJob = [...parsedHistory]
          .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))
          .find((job) => job && job.job_id && job.status !== 'completed' && job.status !== 'failed')

        if (activeJob) {
          setCurrentJob(activeJob)
          setJobState(getJobState(activeJob))
        }
      } catch {
        // Ignore parse error
      }
    }

    loadUserJobs()
  }, [user])

  // Save history to localStorage
  const saveToHistory = (jobRecord, sourceName) => {
    setHistory((prev) => {
      const existingIdx = prev.findIndex((j) => j.job_id === jobRecord.job_id)
      const updatedItem = {
        ...jobRecord,
        sourceName: sourceName || prev[existingIdx]?.sourceName || 'Uploaded Video',
      }

      let nextList = []
      if (existingIdx >= 0) {
        nextList = [...prev]
        nextList[existingIdx] = updatedItem
      } else {
        nextList = [updatedItem, ...prev.slice(0, 19)]
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
    setSelectedFile(null)
    setUploadedData(null)
    setError(null)
  }

  const handleReset = () => {
    setJobState('idle')
    setCurrentJob(null)
    setError(null)
    setSelectedFile(null)
    setUploadedData(null)
  }

  // Handle generation submission
  const handleGenerate = async () => {
    if (!uploadedData?.file_path) {
      setError('Please select and upload a valid video file first.')
      return
    }

    setIsSubmitting(true)
    setError(null)

    const payload = {
      source: {
        type: 'upload',
        location: uploadedData.file_path,
      },
      clip_duration_seconds: Number(settings.clipDurationSeconds),
      number_of_clips: Number(settings.numberOfClips),
      include_captions: Boolean(settings.includeCaptions),
      caption_preset: settings.captionPreset || 'default',
      enable_karaoke: Boolean(settings.enableKaraoke !== false),
      min_clip_duration: Number(settings.minClipDuration),
      max_clip_duration: Number(settings.maxClipDuration),
      vertical_width: 1080,
      vertical_height: 1920,
    }

    try {
      const job = await createJob(payload)
      setCurrentJob(job)
      setJobState('processing')
      saveToHistory(job, selectedFile?.name)
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
      } catch (err) {
        // Network blip
      }
    }

    poll()
    pollingRef.current = setInterval(poll, 1800)
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [jobState, currentJob?.job_id])

  const handleSelectHistoryJob = (jobItem) => {
    setCurrentJob(jobItem)
    if (jobItem.status === 'completed') {
      setJobState('results')
    } else if (jobItem.status === 'failed') {
      setJobState('failed')
      setError(jobItem.error || 'Job failed')
    } else {
      setJobState('processing')
    }
    setIsHistoryOpen(false)
  }

  const handleClearHistory = () => {
    localStorage.removeItem(STORAGE_KEY)
    setHistory([])
  }

  return (
    <div className="app-container">
      <Navbar
        onOpenHistory={() => setIsHistoryOpen(true)}
        historyCount={history.length}
        onOpenAuth={() => setIsAuthOpen(true)}
      />

      <main className="container" style={{ flex: 1, paddingBottom: '3rem' }}>
        {jobState === 'idle' && <HeroSection />}

        {error && (
          <ErrorBanner
            message={error}
            onRetry={jobState === 'failed' ? handleReset : null}
            onDismiss={() => setError(null)}
          />
        )}

        {jobState === 'idle' && (
          <section className="workspace-grid">
            <UploadZone
              selectedFile={selectedFile}
              uploadedData={uploadedData}
              isUploading={isUploading}
              onFileSelected={handleFileSelected}
              onClearFile={handleClearFile}
            />

            <GenerationSettings
              settings={settings}
              onChange={setSettings}
              onGenerate={handleGenerate}
              isSubmitting={isSubmitting || isUploading}
              canSubmit={Boolean(uploadedData?.file_path)}
            />
          </section>
        )}

        {jobState === 'processing' && (
          <ProcessingView
            job={currentJob}
            onCancel={handleReset}
          />
        )}

        {jobState === 'results' && currentJob?.result && (
          <ResultsGrid
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
      </main>

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
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <MainApp />
    </AuthProvider>
  )
}
