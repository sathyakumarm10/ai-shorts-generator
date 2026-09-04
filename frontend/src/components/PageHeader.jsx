import React from 'react'

export function PageHeader({
  badge = null,
  title,
  subtitle,
  actions = null,
}) {
  return (
    <header className="page-header">
      <div className="page-header-text">
        {badge && <div className="page-header-badge">{badge}</div>}
        <h1 className="page-header-title">{title}</h1>
        {subtitle && <p className="page-header-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </header>
  )
}
