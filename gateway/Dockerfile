# Production Dockerfile for Pizza Hut WhatsApp Gateway (Node.js + Baileys)
FROM node:20-alpine

# Set working directory
WORKDIR /app

# Install system dependencies (curl for healthchecks)
RUN apk add --no-cache curl

# Install Node dependencies
COPY package*.json ./
RUN npm ci --omit=dev

# Copy application source
COPY src/ ./src/

# Expose Gateway HTTP ports (3000 = Gateway, 3001 = Internal Notification Server)
EXPOSE 3000
EXPOSE 3001

# Health check against Gateway internal server health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:3001/health || exit 1

# Start Baileys gateway service
CMD ["node", "src/index.js"]
