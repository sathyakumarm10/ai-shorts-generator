import React from 'react'
import { Sparkles, Type, Minus } from 'lucide-react'

const STYLES = [
  { id: 'default', label: 'Default', icon: Type, description: 'Clean bold monochrome text' },
  { id: 'karaoke', label: 'Karaoke', icon: Sparkles, description: 'Highlighted words with pop animation' },
  { id: 'minimal', label: 'Minimal', icon: Minus, description: 'Subtle lower-third styling' },
]

export function SubtitleStylePicker({ currentStyle = 'default', onSelectStyle }) {
  return (
    <div className="subtitle-style-picker" aria-label="Subtitle Style Presets">
      <label className="style-picker-label">Subtitle Style</label>
      <div className="style-picker-options" role="radiogroup">
        {STYLES.map((style) => {
          const Icon = style.icon
          const isSelected = (currentStyle || 'default').toLowerCase() === style.id

          return (
            <button
              key={style.id}
              type="button"
              role="radio"
              aria-checked={isSelected}
              className={`style-option-btn ${isSelected ? 'active' : ''}`}
              onClick={() => onSelectStyle(style.id)}
              title={style.description}
            >
              <Icon size={14} />
              <span>{style.label}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
