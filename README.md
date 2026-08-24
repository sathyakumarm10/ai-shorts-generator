# AI Shorts Generator

## Purpose

AI Shorts Generator is a full-stack application designed to help creators
automatically turn long-form video content into short, engaging clips
("shorts") suitable for platforms such as YouTube Shorts, Instagram Reels,
and TikTok. The project aims to combine video processing, AI-driven content
analysis, and an intuitive web interface so users can generate short-form
video content with minimal manual editing.

> **Note:** This is an early-stage project. The features described below
> represent the planned architecture and direction of the project, not
> functionality that currently exists in this repository.

## Planned Architecture

The project is organized as a full-stack application with a clear
separation between backend and frontend concerns:

```
ai-shorts-generator/
├── backend/            # Python backend application
│   └── app/            # FastAPI application package (routes, services, models)
├── frontend/           # React + TypeScript frontend application
├── tests/              # Backend and frontend test suites
├── .gitignore
└── README.md
```

- **Backend**: Planned to be built with [FastAPI](https://fastapi.tiangolo.com/)
  (Python), responsible for handling API requests, orchestrating video and
  AI processing pipelines, managing uploads/outputs, and exposing endpoints
  for the frontend to consume.
- **Frontend**: Planned to be built with [React](https://react.dev/) and
  [TypeScript](https://www.typescriptlang.org/), providing the user
  interface for uploading videos, configuring short generation options, and
  reviewing/downloading generated shorts.
- **Tests**: A dedicated directory for backend and frontend automated tests
  to ensure reliability as functionality is added.

Future planned capabilities (not yet implemented) include:

- Video ingestion and processing (e.g., trimming, resizing, captioning)
- AI-based content analysis (e.g., highlight/key-moment detection)
- Transcription of source video/audio
- Downloading source content from platforms such as YouTube
- User authentication and account management
- Payments/subscription handling
- Deployment tooling and infrastructure configuration

## Current Development Stage

This repository currently contains only the **initial project scaffolding**:

- `backend/app/__init__.py` — placeholder for the future FastAPI application
  package.
- `frontend/` — empty directory reserved for the future frontend
  application.
- `tests/` — empty directory reserved for future automated tests.
- `.gitignore` — repository ignore rules covering Python, FastAPI, React,
  TypeScript, Node.js, editor/IDE files, temporary files, uploads, generated
  media, build artifacts, and local environment files.

No application features have been implemented yet. Subsequent work will
build out the backend API, frontend interface, and processing pipelines
described above incrementally.

## Getting Started

There is currently nothing to run — this stage only establishes the
repository structure. Setup and usage instructions will be added here as
the backend and frontend applications are scaffolded and implemented.
