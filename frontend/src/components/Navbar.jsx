import React from 'react'
import { Sparkles, History } from 'lucide-react'

export function Navbar({ onOpenHistory, historyCount = 0 }) {
  return (
    <nav className="navbar" aria-label="Main Navigation">
      <div className="container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
        <a href="/" className="nav-brand">
          <div className="brand-icon">
            <Sparkles size={20} color="white" />
          </div>
          <span>AI Shorts Generator</span>
        </a>

        <div className="nav-actions">
          <button
            type="button"
            className="btn-secondary"
            onClick={onOpenHistory}
            aria-label="View previous generation jobs"
          >
            <History size={16} />
            <span>Projects ({historyCount})</span>
          </button>
        </div>
      </div>
    </nav>
  )
}
