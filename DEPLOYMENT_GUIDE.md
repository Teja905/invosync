# INVOSYNC — The Dummy's Guide (for a 9 year old)

## What is this?
You take a photo of an invoice (a bill from a shop).
This app reads it, figures out the numbers, and makes a file that Tally (accounting software) can eat.
Tally is software that Indian accountants use.

---

## How does it work? (3 pieces)

```
Your laptop (you write code here)
    ↓ You type: git push
YOUR CODE goes to GitHub (free storage website)
    ↓ Auto-magic happens
Render (free server that runs your Python code)
    ↓ 
Vercel (free server that shows your React website)
    ↓
MongoDB Atlas (free database that saves everything)
```

## What accounts you need to create

Think of these like making accounts on Instagram, but for developers.

### 1. GitHub (your code's home)
- Go to https://github.com
- Sign up with email
- Your username is: **Teja905**
- This is where your code lives

### 2. MongoDB Atlas (your data's home)
- Go to https://cloud.mongodb.com
- Sign up free
- Click "Create" → "Free Shared Cluster" (it's called M0, costs $0)
- Wait 2 minutes for it to start
- Click "Connect" → "Drivers" → Copy the long URL shown

That URL looks like:
```
mongodb+srv://tejamongo:12345@cluster0.tppoykx.mongodb.net/
```

### 3. Render (runs your backend)
- Go to https://render.com
- Sign up with your GitHub (click "Sign up with GitHub")
- This makes your Python code run on the internet

### 4. Vercel (shows your frontend)
- Go to https://vercel.com
- Sign up with GitHub
- This makes your React website appear on the internet

---

## How to push your code (make it go live)

Open PowerShell (black window). Type these commands ONE BY ONE:

```powershell
# Step 1: Go to your project folder
cd C:\Users\Admin\Desktop\Project-Pauldirac

# Step 2: Tell git to watch all files
git add .

# Step 3: Save a checkpoint called a "commit"
git commit -m "what I changed"

# Step 4: Send to GitHub
git push
```

After Step 4, wait 2 minutes. Render and Vercel will automatically update.

---

## How to make changes (add a new feature)

```
1. Open App.jsx or main.py in VS Code
2. Edit the code
3. Open PowerShell
4. Type: git add .
5. Type: git commit -m "added X feature"
6. Type: git push
7. Wait 2 minutes
8. Your website automatically updates
```

THAT'S IT. You don't need to touch Render or Vercel again.
Just push to GitHub and they auto-update.

---

## URLs (your live websites)

- **Frontend (the website you see)**:
  https://invosync-wheat.vercel.app

- **Backend (the computer brain)**:
  https://invosync-backend-yjfa.onrender.com

- **Health check (is backend alive?)**:
  https://invosync-backend-yjfa.onrender.com/health

---

## Environment Variables (secret settings)

These are like the settings on your phone. You set them once and forget.

### Where to set them:
1. Go to https://dashboard.render.com
2. Click "invosync-backend"
3. Click "Environment" tab
4. Add each one:

| Name | Value | Why? |
|------|-------|------|
| `MONGODB_URI` | `mongodb+srv://tejamongo:12345@cluster0.tppoykx.mongodb.net/invosync` | Tells app where to save data |
| `GEMINI_API_KEY` | `AIzaSy...` (your key) | For AI to read invoices |
| `OPENROUTER_API_KEY` | `sk-or-v1-...` (your key) | Backup AI if Gemini fails |
| `ALLOWED_ORIGINS` | `https://invosync-wheat.vercel.app` | Tells browser "this site is allowed" |
| `JWT_SECRET` | `put-a-long-random-password-here` | Security for user logins |
| `COMPANY_STATE_CODE` | `27` | Your state code for GST |

### For Vercel (frontend):
1. Go to https://vercel.com/teja905/invosync
2. Click "Settings" → "Environment Variables"
3. Add:

| Name | Value |
|------|-------|
| `VITE_API_URL` | `https://invosync-backend-yjfa.onrender.com` |

---

## Daily operations (what to do when things go wrong)

### Problem: Website shows nothing (blank white page)
**Fix**: 
1. Go to https://vercel.com/teja905/invosync
2. Click "Deployments"
3. See if latest deployment says "Ready" or "Failed"
4. If "Failed" — click the deployment and read the error

### Problem: "Internal Server Error" when uploading
**Fix**:
1. Go to https://dashboard.render.com
2. Click "invosync-backend" → "Logs"
3. Read the RED text — that's the error

### Problem: "Cannot connect to database"
**Fix**:
1. Go to https://cloud.mongodb.com
2. Click your cluster → "Network Access"
3. Add `0.0.0.0/0` (allows all IPs — yes it's safe with password)
4. Click "Save"

### Problem: Backend is slow (first request takes 30 seconds)
**Reason**: Free Render goes to sleep after 15 min of no use.
**Fix**: Just wait 30 seconds. Or pay $7/month to Render.

---

## Files you will edit most

| File | What it does |
|------|-------------|
| `frontend/src/App.jsx` | The whole website (1648 lines) |
| `frontend/src/index.css` | Colors, fonts, looks |
| `backend/main.py` | All the computer logic (API routes) |
| `backend/extractors.py` | How AI reads invoices |
| `backend/xml_generator.py` | Makes the Tally XML file |
| `backend/database.py` | How data is saved |

---

## How to add a new button to the website

1. Open `frontend/src/App.jsx`
2. Find the part of the page you want to change
3. Add your button:
   ```jsx
   <button className="gh-btn gh-btn-primary" onClick={() => alert("Hello!")}>
     Click Me
   </button>
   ```
4. Save → `git add .` → `git commit -m "added button"` → `git push`
5. Wait 2 min → It's live

---

## How to add a new API route (new computer command)

1. Open `backend/main.py`
2. Scroll to the end
3. Add this:
   ```python
   @app.get("/hello")
   async def say_hello():
       return {"message": "Hello World!"}
   ```
4. Save → git push → wait 2 min
5. Visit https://invosync-backend-yjfa.onrender.com/hello

---

## Class names you can use (for making things look good)

I added a GitHub-style theme. These CSS classes are available:

| Class | What it looks like |
|-------|-------------------|
| `gh-card` | A white card with dark border |
| `gh-btn gh-btn-primary` | Green button |
| `gh-btn gh-btn-secondary` | Gray button |
| `gh-btn gh-btn-danger` | Red button |
| `gh-input` | Text input box |
| `gh-table` | Table with rows |
| `gh-tag gh-tag-green` | Green badge |
| `gh-tag gh-tag-yellow` | Yellow badge |
| `gh-tag gh-tag-red` | Red badge |
| `gh-tag gh-tag-blue` | Blue badge |
| `gh-alert gh-alert-error` | Red alert box |
| `gh-alert gh-alert-warning` | Yellow alert box |
| `gh-alert gh-alert-info` | Blue alert box |
| `gh-alert gh-alert-success` | Green alert box |
| `gh-label` | Label for form fields |
| `gh-dropzone` | File upload area |
| `gh-spinner` | Loading spinner |
| `gh-modal-overlay` + `gh-modal` | Popup window |

---

## Cost breakdown ($0 per month)

| Service | What it does | Cost |
|---------|-------------|------|
| GitHub | Stores code | Free |
| Render | Runs Python (backend) | Free (sleeps after 15 min idle) |
| Vercel | Shows React (frontend) | Free |
| MongoDB Atlas | Saves data | Free (512 MB) |
| **Total** | | **$0/month** |

### If you get 100 users:
- MongoDB Atlas: upgrade to M2 plan ($9/month)
- Everything else: still free

---

## How git works (the 3 commands you need)

Git is like a video game save system for your code.

```
git add .     →  "Save all changes to clipboard"
git commit -m "..."  →  "Write the save file with a note"
git push      →  "Upload the save file to the cloud"
```

That's it. Three commands. That's all you need to know.

---

## The most important rule

> **Just push to GitHub. Everything else happens automatically.**

Render watches GitHub. Vercel watches GitHub.
You push → they update. No clicking buttons on websites.

---

## Emergency cheat sheet

```
┌──────────────────────┬──────────────────────────────────────────────┐
│ You want to...       │ Type in PowerShell                          │
├──────────────────────┼──────────────────────────────────────────────┤
│ Deploy your changes  │ git add . && git commit -m "msg" && git push │
│ See what changed     │ git diff                                    │
│ Undo last change     │ git checkout -- filename                    │
│ Check deploy status  │ Go to render.com or vercel.com              │
│ See server errors    │ Render dashboard → Logs                     │
│ See website errors   │ Vercel dashboard → Functions → Logs         │
│ Check database       │ cloud.mongodb.com → Browse Collections      │
└──────────────────────┴──────────────────────────────────────────────┘
```

## Final words

This app took months to build. It has:
- AI that reads invoices
- GST tax logic (Indian tax rules)
- Tally XML export
- Validation (checks for mistakes)
- GitHub dark theme (because it looks cool)
- GSAP animations (smooth page transitions)

Everything works. Just push code and it goes live.
You don't need to understand everything. Just know:
**git add . → git commit -m "msg" → git push**

That's all.
