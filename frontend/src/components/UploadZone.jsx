import React, { useState, useRef } from 'react'
import { UploadCloud, Video, Trash2, CheckCircle2, Film } from 'lucide-react'

export function UploadZone({
  selectedFile,
  uploadedData,
  isUploading,
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
    <div className="glass-card">
      <div className="card-header">
        <h2 className="card-title">
          <Film size={20} color="#6366f1" />
          <span>Source Video</span>
        </h2>
        {uploadedData && (
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.85rem', color: '#10b981' }}>
            <CheckCircle2 size={16} />
            <span>Ready for Processing</span>
          </span>
        )}
      </div>

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
            <UploadCloud size={28} />
          </div>

          <div className="upload-primary-text">
            Drag & drop your source video here, or <span style={{ color: 'var(--accent-primary)', textDecoration: 'underline' }}>browse</span>
          </div>

          <div className="upload-secondary-text">
            Supports MP4, MOV, MKV, WebM (landscape podcasts, lectures, gameplay, etc.)
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
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', overflow: 'hidden' }}>
              <Video size={16} color="var(--accent-primary)" />
              <span style={{ fontWeight: 600, textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                {selectedFile.name}
              </span>
              <span style={{ color: 'var(--text-muted)' }}>
                ({formatFileSize(selectedFile.size)})
              </span>
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

          {isUploading && (
            <div style={{ fontSize: '0.85rem', color: 'var(--accent-primary)', textAlign: 'center' }}>
              Uploading to server workspace...
            </div>
          )}
        </div>
      )}

      {error && (
        <div style={{ marginTop: '1rem', color: 'var(--accent-rose)', fontSize: '0.85rem' }}>
          {error}
        </div>
      )}
    </div>
  )
}
