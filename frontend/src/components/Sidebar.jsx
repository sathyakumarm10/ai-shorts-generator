import React from 'react'
import { Sparkles, LayoutDashboard, PlusCircle, Film, LogIn, LogOut, User } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

export function Sidebar({
  activeTab,
  onSelectTab,
  onOpenAuth,
  historyCount = 0,
}) {
  const { user, logout } = useAuth()

  const navItems = [
    {
      id: 'dashboard',
      label: 'Dashboard',
      icon: LayoutDashboard,
    },
    {
      id: 'create',
      label: 'Create Short',
      icon: PlusCircle,
    },
    {
      id: 'my-shorts',
      label: 'My Shorts',
      icon: Film,
      badge: historyCount > 0 ? historyCount : null,
    },
  ]

  return (
    <aside className="app-sidebar" aria-label="Main Application Sidebar">
      {/* Brand Header */}
      <div className="sidebar-brand-wrapper">
        <div className="sidebar-brand" onClick={() => onSelectTab('dashboard')} role="button" tabIndex={0}>
          <div className="brand-icon">
            <Sparkles size={20} color="white" />
          </div>
          <div className="brand-text-block">
            <span className="brand-title">AI Shorts</span>
            <span className="brand-subtitle">Generator</span>
          </div>
        </div>
      </div>

      {/* Primary Navigation */}
      <nav className="sidebar-nav">
        <div className="nav-section-label">MAIN NAVIGATION</div>
        {navItems.map((item) => {
          const Icon = item.icon
          const isActive = activeTab === item.id

          return (
            <button
              key={item.id}
              type="button"
              className={`sidebar-nav-btn ${isActive ? 'active' : ''}`}
              onClick={() => onSelectTab(item.id)}
              aria-current={isActive ? 'page' : undefined}
            >
              <div className="sidebar-nav-btn-content">
                <Icon size={18} />
                <span>{item.label}</span>
              </div>
              {item.badge != null && (
                <span className="sidebar-nav-badge">{item.badge}</span>
              )}
            </button>
          )
        })}
      </nav>

      {/* User / Authentication Controls */}
      <div className="sidebar-footer">
        {user ? (
          <div className="sidebar-user-block">
            <div className="sidebar-user-info">
              <div className="user-avatar-circle">
                <User size={15} />
              </div>
              <div className="user-email-text" title={user.email}>
                {user.email}
              </div>
            </div>

            <button
              type="button"
              className="btn-sidebar-logout"
              onClick={logout}
              title="Sign Out"
              aria-label="Sign Out"
            >
              <LogOut size={16} />
              <span>Sign Out</span>
            </button>
          </div>
        ) : (
          <div className="sidebar-auth-prompt">
            <p className="auth-prompt-desc">Sign in to save and synchronize your projects.</p>
            <button
              type="button"
              className="btn-primary btn-sidebar-login"
              onClick={onOpenAuth}
            >
              <LogIn size={15} />
              <span>Sign In</span>
            </button>
          </div>
        )}
      </div>
    </aside>
  )
}
