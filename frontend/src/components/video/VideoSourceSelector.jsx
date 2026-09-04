import React, { useState, useRef } from 'react'
import { UploadCloud, Link as LinkIcon, Video, Trash2, CheckCircle2, Film, AlertCircle } from 'lucide-react'

export function VideoSourceSelector({
  sourceType = 'upload',
  setSourceType = () => {},
  selectedFile,
  uploadedData,
  videoUrl = '',
  setVideoUrl = () => {},
  isUploading = false,
  onFileSelected,
  onClearFile,
  error,
}) {
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef(null)

  const handleDragOver = (e) => {
    e.preventDefault()
    setIsDragOver(true)
  }

  const handleDragLeave = () => {
    setIsDragOver(false)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setIsDragOver(false)
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      onFileSelected(e.dataTransfer.files[0])
    }
  }

  const handleInputChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      onFileSelected(e.target.files[0])
    }
  }

  const formatFileSize = (bytes) => {
    if (!bytes) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
  }

  return (
    <div className="glass-card video-source-selector">
      <div className="card-header">
        <h2 className="card-title">
          <Film size={20} color="#6366f1" />
          <span>Source Video</span>
        </h2>

        {/* Source Mode Tabs */}
        <div className="source-tabs" role="tablist" aria-label="Video Source Type">
          <button
            type="button"
            role="tab"
            aria-selected={sourceType === 'upload'}
            className={`source-tab ${sourceType === 'upload' ? 'active' : ''}`}
            onClick={() => setSourceType('upload')}
          >
            <UploadCloud size={15} />
            <span>Upload File</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={sourceType === 'url'}
            className={`source-tab ${sourceType === 'url' ? 'active' : ''}`}
            onClick={() => setSourceType('url')}
          >
            <LinkIcon size={15} />
            <span>Video URL</span>
          </button>
        </div>
      </div>

      {sourceType === 'upload' ? (
        <>
          {!selectedFile ? (
            <div
              className={`upload-zone ${isDragOver ? 'dragover' : ''}`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && fileInputRef.current?.click()}
              aria-label="Upload source video"
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="video/mp4,video/quicktime,video/x-matroska,video/webm"
                style={{ display: 'none' }}
                onChange={handleInputChange}
                aria-hidden="true"
              />

              <div className="upload-icon-wrapper">
                <UploadCloud size={30} />
              </div>

              <div className="upload-primary-text">
                Drag & drop your source video here, or <span className="upload-browse-link">browse</span>
              </div>

              <div className="upload-secondary-text">
                Supports MP4, MOV, MKV, WebM (landscape podcasts, lectures, interviews)
              </div>
            </div>
          ) : (
            <div className="preview-container">
              <video
                className="preview-video"
                controls
                preload="metadata"
                src={URL.createObjectURL(selectedFile)}
              />

              <div className="preview-meta">
                <div className="preview-file-info">
                  <Video size={16} color="var(--accent-primary)" />
                  <span className="preview-filename">{selectedFile.name}</span>
                  <span className="preview-filesize">({formatFileSize(selectedFile.size)})</span>
                </div>

                <button
                  type="button"
                  className="btn-remove"
                  onClick={onClearFile}
                  disabled={isUploading}
                  aria-label="Remove selected video"
                >
                  <Trash2 size={15} />
                  <span>Remove</span>
                </button>
              </div>

              {isUploading ? (
                <div className="upload-status-indicator">
                  <div className="loading-spinner-small" />
                  <span>Uploading to server workspace...</span>
                </div>
              ) : uploadedData ? (
                <div className="upload-ready-indicator">
                  <CheckCircle2 size={15} color="#10b981" />
                  <span>Video ready for processing</span>
                </div>
              ) : null}
            </div>
          )}
        </>
      ) : (
        <div className="url-source-container">
          <label htmlFor="video-url-input" className="url-input-label">
            Video Stream or Web URL
          </label>
          <div className="url-input-wrapper">
            <LinkIcon size={16} className="url-input-icon" />
            <input
              id="video-url-input"
              type="url"
              className="url-input-field"
              placeholder="https://example.com/video.mp4"
              value={videoUrl}
              onChange={(e) => setVideoUrl(e.target.value)}
              aria-label="Video URL input"
            />
          </div>
          <p className="setting-helper">
            Direct MP4 or web stream URL accessible by the server pipeline.
          </p>
        </div>
      )}

      {error && (
        <div className="source-error-message" role="alert">
          <AlertCircle size={15} />
          <span>{error}</span>
        </div>
      )}
    </div>
  )
}
