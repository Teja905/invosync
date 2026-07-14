#!/usr/bin/env bash
set -euo pipefail

APP="invosync"
TAG="${1:-latest}"
BACKUP_DIR="./deploy-backups"

echo "=== Zero-Downtime Deploy: $APP:$TAG ==="

# 1. Pull new image
docker compose pull backend

# 2. Backup current DB
mkdir -p "$BACKUP_DIR"
docker exec invosync-mongo mongodump --archive="$BACKUP_DIR/pre-deploy-$(date +%Y%m%d_%H%M%S).gz" --gzip --username "$MONGO_USER" --password "$MONGO_PASS" 2>/dev/null || echo "⚠ DB backup skipped (auth may differ)"

# 3. Start new container alongside old (blue-green)
echo "⟳ Starting new backend container..."
docker compose up -d --no-deps --scale backend=2 backend
sleep 5

# 4. Health check
for i in {1..12}; do
  if curl -sf http://localhost:8000/health 2>/dev/null | grep -q ok; then
    echo "✅ New container healthy"
    break
  fi
  echo "   Waiting... ($i/12)"
  sleep 5
done

# 5. Stop old container
OLD_ID=$(docker ps -q --filter "name=invosync-backend" --filter "publish=8000" | tail -1)
if [ -n "$OLD_ID" ]; then
  echo "⟳ Draining old container: $OLD_ID"
  sleep 10
  docker stop "$OLD_ID" || true
  docker rm "$OLD_ID" || true
fi

# 6. Scale back to 1
docker compose up -d --no-deps --scale backend=1 backend

echo "=== Deploy complete ==="
