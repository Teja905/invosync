# Deployment Guide

## Quick Deploy (Railway + Vercel)

### Backend (Railway)

1. Push to GitHub
2. Go to [railway.app](https://railway.app)
3. New Project → Deploy from GitHub repo
4. Root directory: `backend/`
5. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Add environment variables (copy from `.env`)

### Frontend (Vercel)

1. Go to [vercel.com](https://vercel.com)
2. Import GitHub repo
3. Root directory: `frontend/`
4. Framework preset: Vite
5. Environment variable: `VITE_API_URL=https://your-backend.railway.app`

### Database (MongoDB Atlas)

1. Go to [mongodb.com/atlas](https://mongodb.com/atlas)
2. Create free cluster
3. Get connection string
4. Set `MONGODB_URI` in Railway env vars

## Environment Variables

```
GEMINI_API_KEY=your_key
OPENROUTER_API_KEY=your_key
NVIDIA_API_KEY=your_key
MONGODB_URI=mongodb+srv://...
COMPANY_STATE_CODE=27
COMPANY_NAME=My Company
```

## Local Dev

```bash
# Terminal 1 - Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# Terminal 2 - Frontend
cd frontend
npm install
npm run dev
```

## Costs

| Service | Monthly |
|---|---|
| Railway (backend) | $5-7 |
| Vercel (frontend) | Free |
| MongoDB Atlas | Free |
| Domain (optional) | $12/yr |
| **Total** | **~$10/mo** |
