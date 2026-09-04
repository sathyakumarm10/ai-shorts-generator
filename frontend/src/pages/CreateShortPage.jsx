import React from 'react'
import { VideoSourceSelector } from '../components/video/VideoSourceSelector'
import { GenerationSettings } from '../components/generation/GenerationSettings'
import { PageHeader } from '../components/PageHeader'

export function CreateShortPage({
  sourceType,
  setSourceType,
  selectedFile,
  uploadedData,
  videoUrl,
  setVideoUrl,
  isUploading,
  isSubmitting,
  onFileSelected,
  onClearFile,
  settings,
  setSettings,
  onGenerate,
  error,
}) {
  const canSubmit = Boolean(uploadedData?.file_path || videoUrl.trim())

  return (
    <div className="create-short-page">
      <PageHeader
        title="Create New Shorts"
        subtitle="Configure video source, select up to 15 target clips, and customize styled subtitles."
      />

      <div className="workspace-grid">
        <VideoSourceSelector
          sourceType={sourceType}
          setSourceType={setSourceType}
          selectedFile={selectedFile}
          uploadedData={uploadedData}
          videoUrl={videoUrl}
          setVideoUrl={setVideoUrl}
          isUploading={isUploading}
          onFileSelected={onFileSelected}
          onClearFile={onClearFile}
          error={error}
        />

        <GenerationSettings
          settings={settings}
          onChange={setSettings}
          onGenerate={onGenerate}
          isSubmitting={isSubmitting || isUploading}
          canSubmit={canSubmit}
        />
      </div>
    </div>
  )
}
