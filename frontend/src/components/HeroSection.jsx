import React from 'react'
import { Sparkles, Scissors, Smartphone, Subtitles } from 'lucide-react'

export function HeroSection() {
  return (
    <section className="hero">
      <div className="container">
        <div className="hero-badge">
          <Sparkles size={14} />
          <span>Automated AI Video Clipping & Framing</span>
        </div>

        <h1 className="hero-title">
          Turn long videos into <span className="hero-gradient-text">viral Shorts</span> automatically
        </h1>

        <p className="hero-subtitle">
          Intelligent speech-aware highlights detection, smart 9:16 vertical framing, and burned-in timestamped captions — 100% locally with zero external API fees.
        </p>

        <div className="feature-pills">
          <div className="feature-pill">
            <Scissors size={14} />
            <span>AI Highlight Detection</span>
          </div>
          <div className="feature-pill">
            <Smartphone size={14} />
            <span>9:16 Vertical Auto-Crop</span>
          </div>
          <div className="feature-pill">
            <Subtitles size={14} />
            <span>Synced Burned Captions</span>
          </div>
        </div>
      </div>
    </section>
  )
}
