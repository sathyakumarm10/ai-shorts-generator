import React from 'react'
import { Sparkles } from 'lucide-react'

export function EmptyState({
  icon: Icon = Sparkles,
  title,
  description,
  actionLabel,
  onAction,
}) {
  return (
    <div className="empty-state-card" role="region" aria-label={title}>
      <div className="empty-state-icon-wrapper">
        <Icon size={32} className="empty-state-icon" />
      </div>
      <h3 className="empty-state-title">{title}</h3>
      {description && <p className="empty-state-description">{description}</p>}
      {actionLabel && onAction && (
        <button
          type="button"
          className="btn-primary"
          onClick={onAction}
        >
          {actionLabel}
        </button>
      )}
    </div>
  )
}
