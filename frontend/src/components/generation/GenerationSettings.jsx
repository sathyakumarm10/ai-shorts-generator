import React from 'react'
import { Sliders, Sparkles, Subtitles, Layers, Clock, Info } from 'lucide-react'

export function GenerationSettings({
  settings,
  onChange,
  onGenerate,
  isSubmitting,
  canSubmit,
}) {
  const handleSliderChange = (key, value) => {
    let numVal = Number(value)
    if (key === 'numberOfClips') {
      numVal = Math.min(15, Math.max(1, numVal))
    }
    onChange({ ...settings, [key]: numVal })
  }

  const handleToggleChange = (key, checked) => {
    onChange({ ...settings, [key]: checked })
  }

  const shortCount = Math.min(15, Math.max(1, Number(settings.numberOfClips) || 10))

  return (
    <div className="glass-card generation-settings-card">
      <div className="card-header">
        <h2 className="card-title">
          <Sliders size={20} color="#a855f7" />
          <span>Generation Settings</span>
        </h2>
      </div>

      <div className="settings-group">
        {/* Number of Shorts (1 to 15) */}
        <div className="setting-item">
          <div className="setting-label-row">
            <span className="setting-label" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <Layers size={15} color="var(--text-secondary)" />
              Number of Shorts
            </span>
            <span className="setting-value">{shortCount} {shortCount === 1 ? 'short' : 'shorts'}</span>
          </div>

          <input
            type="range"
            min="1"
            max="15"
            step="1"
            value={shortCount}
            onChange={(e) => handleSliderChange('numberOfClips', e.target.value)}
            disabled={isSubmitting}
            aria-label="Number of shorts to generate"
            className="settings-slider"
          />

          <div className="setting-note-box">
            <Info size={14} className="setting-note-icon" />
            <span className="setting-note-text">
              Select up to 15 distinct Shorts. The system identifies top unique highlights and may produce fewer if the video lacks enough distinct moments.
            </span>
          </div>
        </div>

        {/* Target Clip Duration */}
        <div className="setting-item">
          <div className="setting-label-row">
            <span className="setting-label" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <Clock size={15} color="var(--text-secondary)" />
              Target Duration
            </span>
            <span className="setting-value">{settings.clipDurationSeconds || 60}s</span>
          </div>
          <input
            type="range"
            min="30"
            max="120"
            step="5"
            value={settings.clipDurationSeconds || 60}
            onChange={(e) => handleSliderChange('clipDurationSeconds', e.target.value)}
            disabled={isSubmitting}
            aria-label="Target clip duration in seconds"
            className="settings-slider"
          />
          <span className="setting-helper">Optimal duration for YouTube Shorts, Reels, and TikTok (30–120s).</span>
        </div>

        {/* Subtitles Toggle */}
        <div className="toggle-row">
          <div>
            <div className="setting-label" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <Subtitles size={16} color="var(--accent-emerald)" />
              <span>Generate Subtitles</span>
            </div>
            <div className="setting-helper">Create synchronized readable subtitles formatted for 9:16 mobile display.</div>
          </div>

          <label className="switch">
            <input
              type="checkbox"
              checked={settings.includeCaptions !== false}
              onChange={(e) => handleToggleChange('includeCaptions', e.target.checked)}
              disabled={isSubmitting}
              aria-label="Toggle timestamped captions"
            />
            <span className="slider"></span>
          </label>
        </div>

        {/* Caption Style Preset Selector */}
        {settings.includeCaptions !== false && (
          <div className="setting-item" style={{ marginTop: '0.5rem' }}>
            <div className="setting-label-row">
              <span className="setting-label" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <Sparkles size={15} color="#06b6d4" />
                Subtitle Style
              </span>
            </div>
            <div className="preset-selector-grid">
              {[
                { id: 'default', name: 'Clean Dynamic', desc: 'Minimal clean captions' },
                { id: 'beast', name: 'MrBeast', desc: 'High energy bold titles' },
                { id: 'ali', name: 'Ali Abdaal', desc: 'Sleek pastel minimalist' },
                { id: 'hormozi', name: 'Hormozi', desc: 'Ultra-bold vibrant text' },
              ].map((preset) => (
                <button
                  key={preset.id}
                  type="button"
                  className={`preset-btn ${(settings.captionPreset || 'default') === preset.id ? 'active' : ''}`}
                  onClick={() => onChange({ ...settings, captionPreset: preset.id })}
                  disabled={isSubmitting}
                >
                  <div className="preset-name">{preset.name}</div>
                  <div className="preset-desc">{preset.desc}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Submit Action */}
        <button
          type="button"
          className="btn-primary btn-generate"
          onClick={onGenerate}
          disabled={!canSubmit || isSubmitting}
          style={{ width: '100%', marginTop: '1.25rem' }}
        >
          {isSubmitting ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}>
              <div className="loading-spinner-small" />
              <span>Starting Generation...</span>
            </span>
          ) : (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}>
              <Sparkles size={18} />
              <span>Generate AI Shorts</span>
            </span>
          )}
        </button>
      </div>
    </div>
  )
}
