#!/bin/bash

cd "$(dirname "$0")"

if [ ! -f "backend/.env" ]; then
    echo "Creating .env file from .env.example..."
    cp backend/.env.example backend/.env
fi

cd backend

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python -m venv venv
fi

echo "Activating virtual environment..."
source venv/scripts/activate

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Creating necessary directories..."
mkdir -p uploads generated_apps chroma_data logs

echo "Starting FastAPI server..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
