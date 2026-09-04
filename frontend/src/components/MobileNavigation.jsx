import React from 'react'
import { LayoutDashboard, PlusCircle, Film, Sparkles, LogIn, User, LogOut } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

export function MobileNavigation({
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
      label: 'Create',
      icon: PlusCircle,
    },
    {
      id: 'my-shorts',
      label: 'Shorts',
      icon: Film,
      badge: historyCount > 0 ? historyCount : null,
    },
  ]

  return (
    <div className="mobile-nav-bar" role="navigation" aria-label="Mobile Navigation">
      {navItems.map((item) => {
        const Icon = item.icon
        const isActive = activeTab === item.id

        return (
          <button
            key={item.id}
            type="button"
            className={`mobile-nav-item ${isActive ? 'active' : ''}`}
            onClick={() => onSelectTab(item.id)}
            aria-current={isActive ? 'page' : undefined}
          >
            <div className="mobile-nav-icon-wrap">
              <Icon size={20} />
              {item.badge != null && (
                <span className="mobile-nav-badge">{item.badge}</span>
              )}
            </div>
            <span className="mobile-nav-label">{item.label}</span>
          </button>
        )
      })}

      {user ? (
        <button
          type="button"
          className="mobile-nav-item"
          onClick={logout}
          aria-label="Sign Out"
        >
          <div className="mobile-nav-icon-wrap">
            <LogOut size={20} />
          </div>
          <span className="mobile-nav-label">Logout</span>
        </button>
      ) : (
        <button
          type="button"
          className="mobile-nav-item"
          onClick={onOpenAuth}
          aria-label="Sign In"
        >
          <div className="mobile-nav-icon-wrap">
            <LogIn size={20} />
          </div>
          <span className="mobile-nav-label">Login</span>
        </button>
      )}
    </div>
  )
}
