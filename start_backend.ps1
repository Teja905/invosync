# Start the backend server
cd $PSScriptRoot\backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
 