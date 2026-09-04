import React from 'react'
import { Sidebar } from '../components/Sidebar'
import { MobileNavigation } from '../components/MobileNavigation'

export function AppShell({
  activeTab,
  onSelectTab,
  onOpenAuth,
  historyCount,
  children,
}) {
  return (
    <div className="app-shell-layout">
      {/* Desktop Persistent Sidebar */}
      <Sidebar
        activeTab={activeTab}
        onSelectTab={onSelectTab}
        onOpenAuth={onOpenAuth}
        historyCount={historyCount}
      />

      {/* Main Content Area */}
      <div className="app-shell-main-wrapper">
        <main className="app-shell-main-content">
          {children}
        </main>
      </div>

      {/* Mobile Responsive Navigation Bar */}
      <MobileNavigation
        activeTab={activeTab}
        onSelectTab={onSelectTab}
        onOpenAuth={onOpenAuth}
        historyCount={historyCount}
      />
    </div>
  )
}
