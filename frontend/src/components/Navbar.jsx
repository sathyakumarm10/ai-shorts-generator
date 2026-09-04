import React from 'react'
import { Sparkles, History, User, LogOut, LogIn } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

export function Navbar({ onOpenHistory, historyCount = 0, onOpenAuth }) {
  const { user, logout } = useAuth()

  return (
    <nav className="navbar" aria-label="Main Navigation">
      <div className="container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
        <a href="/" className="nav-brand">
          <div className="brand-icon">
            <Sparkles size={18} />
          </div>
          <span>AI Shorts Generator</span>
        </a>

        <div className="nav-actions" style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <button
            type="button"
            className="btn-secondary"
            onClick={onOpenHistory}
            aria-label="View previous generation jobs"
          >
            <History size={16} />
            <span>Projects ({historyCount})</span>
          </button>

          {user ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                  fontSize: '0.82rem',
                  padding: '4px 10px',
                  background: '#F5F5F5',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: '20px',
                  color: 'var(--text-primary)',
                  fontWeight: 500,
                }}
              >
                <User size={13} />
                <span>{user.email.split('@')[0]}</span>
              </span>

              <button
                type="button"
                className="btn-secondary"
                onClick={logout}
                title="Logout"
                aria-label="Logout"
                style={{ padding: '0.45rem 0.75rem' }}
              >
                <LogOut size={15} />
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="btn-primary"
              onClick={onOpenAuth}
              style={{ padding: '0.45rem 0.9rem', fontSize: '0.85rem' }}
            >
              <LogIn size={15} />
              <span>Sign In</span>
            </button>
          )}
        </div>
      </div>
    </nav>
  )
}
