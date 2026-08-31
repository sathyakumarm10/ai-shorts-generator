import React from 'react'
import { Sliders, Sparkles, Subtitles, Layers, Clock } from 'lucide-react'

export function GenerationSettings({
  settings,
  onChange,
  onGenerate,
  isSubmitting,
  canSubmit,
}) {
  const handleSliderChange = (key, value) => {
    onChange({ ...settings, [key]: Number(value) })
  }

  const handleToggleChange = (key, checked) => {
    onChange({ ...settings, [key]: checked })
  }

  return (
    <div className="glass-card">
      <div className="card-header">
        <h2 className="card-title">
          <Sliders size={20} color="#a855f7" />
          <span>Generation Settings</span>
        </h2>
      </div>

      <div className="settings-group">
        {/* Number of Clips */}
        <div className="setting-item">
          <div className="setting-label-row">
            <span className="setting-label" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <Layers size={15} color="var(--text-secondary)" />
              Number of Shorts
            </span>
            <span className="setting-value">{settings.numberOfClips} {settings.numberOfClips === 1 ? 'clip' : 'clips'}</span>
          </div>
          <input
            type="range"
            min="1"
            max="10"
            step="1"
            value={settings.numberOfClips}
            onChange={(e) => handleSliderChange('numberOfClips', e.target.value)}
            disabled={isSubmitting}
            aria-label="Number of shorts to generate"
          />
          <span className="setting-helper">Top highlight candidates ranked by speech curiosity, hooks, and density.</span>
        </div>

        {/* Target Clip Duration */}
        <div className="setting-item">
          <div className="setting-label-row">
            <span className="setting-label" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <Clock size={15} color="var(--text-secondary)" />
              Target Duration
            </span>
            <span className="setting-value">{settings.clipDurationSeconds}s</span>
          </div>
          <input
            type="range"
            min="30"
            max="120"
            step="5"
            value={settings.clipDurationSeconds}
            onChange={(e) => handleSliderChange('clipDurationSeconds', e.target.value)}
            disabled={isSubmitting}
            aria-label="Target clip duration in seconds"
          />
          <span className="setting-helper">Optimal short-form length for YouTube Shorts, Reels, and TikTok (30–120s).</span>
        </div>

        {/* Captions Toggle */}
        <div className="toggle-row">
          <div>
            <div className="setting-label" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <Subtitles size={16} color="var(--accent-emerald)" />
              <span>Burn Timestamped Captions</span>
            </div>
            <div className="setting-helper">Overlay animated styled subtitles centered for mobile viewing.</div>
          </div>

          <label className="switch">
            <input
              type="checkbox"
              checked={settings.includeCaptions}
              onChange={(e) => handleToggleChange('includeCaptions', e.target.checked)}
              disabled={isSubmitting}
              aria-label="Toggle timestamped captions"
            />
            <span className="slider"></span>
          </label>
        </div>

        {/* Caption Style Preset Selector */}
        {settings.includeCaptions && (
          <>
            <div className="setting-item" style={{ marginTop: '0.5rem' }}>
              <div className="setting-label-row">
                <span className="setting-label" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <Sparkles size={14} color="#a855f7" />
                  Caption Style
                </span>
              </div>
              <select
                value={settings.captionPreset || 'default'}
                onChange={(e) => onChange({ ...settings, captionPreset: e.target.value })}
                disabled={isSubmitting}
                aria-label="Select caption style preset"
                style={{
                  width: '100%',
                  padding: '0.6rem 0.8rem',
                  background: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text-primary)',
                  fontSize: '0.88rem',
                  outline: 'none',
                  cursor: 'pointer',
                }}
              >
                <option value="default" style={{ background: '#1e1b4b', color: '#fff' }}>Default (Clean White with Dark Border)</option>
                <option value="classic_karaoke" style={{ background: '#1e1b4b', color: '#fff' }}>Classic Karaoke (Energetic Gold Pop)</option>
                <option value="karaoke" style={{ background: '#1e1b4b', color: '#fff' }}>Karaoke (Gold Pop Accent)</option>
                <option value="word_highlight" style={{ background: '#1e1b4b', color: '#fff' }}>Word Highlight (Electric Cyan Accent)</option>
                <option value="highlight" style={{ background: '#1e1b4b', color: '#fff' }}>Highlight (Cyan Theme)</option>
                <option value="punch_pop" style={{ background: '#1e1b4b', color: '#fff' }}>Punch / Pop (High-Impact Heavy Block)</option>
                <option value="bold" style={{ background: '#1e1b4b', color: '#fff' }}>Bold (Heavy Outline Block)</option>
                <option value="clean_creator" style={{ background: '#1e1b4b', color: '#fff' }}>Clean Creator (Subtle Minimal Text)</option>
                <option value="minimal" style={{ background: '#1e1b4b', color: '#fff' }}>Minimal (Subtle Clean Text)</option>
              </select>
              <span className="setting-helper">Select social media typography and color theme for burned subtitles.</span>
            </div>

            {/* Karaoke Animation Toggle */}
            <div className="toggle-row" style={{ marginTop: '0.6rem', borderTop: '1px solid var(--border-subtle)', paddingTop: '0.75rem' }}>
              <div>
                <div className="setting-label" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <Sparkles size={14} color="#f59e0b" />
                  <span>Word-by-Word Karaoke Animation</span>
                </div>
                <div className="setting-helper">Synchronize active spoken word highlighting with speech audio.</div>
              </div>

              <label className="switch">
                <input
                  type="checkbox"
                  checked={settings.enableKaraoke !== false}
                  onChange={(e) => handleToggleChange('enableKaraoke', e.target.checked)}
                  disabled={isSubmitting}
                  aria-label="Toggle karaoke word animation"
                />
                <span className="slider"></span>
              </label>
            </div>
          </>
        )}

        {/* Framing specs note */}
        <div style={{ padding: '0.75rem 1rem', background: 'rgba(255, 255, 255, 0.02)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
          Output Format: <strong>1080 &times; 1920 (9:16 Vertical)</strong> &bull; H.264 &bull; AAC Audio
        </div>

        {/* Primary Action Button */}
        <button
          type="button"
          className="btn-primary"
          onClick={onGenerate}
          disabled={!canSubmit || isSubmitting}
        >
          <Sparkles size={18} />
          <span>{isSubmitting ? 'Starting AI Pipeline...' : 'Generate AI Shorts'}</span>
        </button>
      </div>
    </div>
  )
}
