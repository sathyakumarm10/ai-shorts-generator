# ==============================================================================
# AI Shorts Generator - Production Frontend Dockerfile
# Multi-stage build: Node.js (Vite builder) -> Nginx Alpine (Lightweight runtime)
# ==============================================================================

# --- Stage 1: Build static assets ---
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package dependency manifests
COPY frontend/package.json frontend/package-lock.json ./

# Install dependencies deterministically
RUN npm ci

# Copy frontend source files
COPY frontend/ ./

# Build production bundle to /app/dist
RUN npm run build

# --- Stage 2: Production Nginx runtime ---
FROM nginx:alpine AS runner

# Remove default Nginx site configuration
RUN rm -rf /etc/nginx/conf.d/* /usr/share/nginx/html/*

# Copy built production assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy custom Nginx configuration
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

# Expose HTTP port 80
EXPOSE 80

# Healthcheck probing /health endpoint
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost:80/health || exit 1

# Run Nginx in foreground
CMD ["nginx", "-g", "daemon off;"]
