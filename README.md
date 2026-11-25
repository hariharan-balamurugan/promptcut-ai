# 🎬 PromptCut AI

**AI-Powered Natural Language Video Editing & Multi-Clip Studio**

PromptCut AI allows you to edit videos using simple natural-language instructions. Instead of manually trimming, applying effects, searching for songs, and syncing audio, describe what you want in plain English and PromptCut AI handles the rest.

---

## ✨ Key Features

- **Natural Language Editing:** Transform prompts like *"Make it cinematic, add upbeat music, and convert to 9:16 vertical"* into precise FFmpeg operations.
- **Multi-Video Merge & Bulk Editing:** Upload 2 or more video clips to concatenate and edit them into a single cohesive video or process multiple videos in bulk.
- **Vision AI Scene & Emotion Detection:** Analyzes video frames with multimodal AI to detect emotions, pacing, and visual dynamics.
- **Emotion-Matched Music Catalog & Online Search:** Automatically selects suitable background music from local catalog or Jamendo API.
- **Word-by-Word Karaoke Subtitles:** Generates synced lyric captions using Faster-Whisper.
- **Audio Ducking & Mixing:** Automatically ducks background soundtrack volume during dialogue or prominent original audio.
- **Visual Transitions & Speed Ramps:** Supports zoom, fades, slides, speed adjustments, and aspect ratio conversion.
- **Batch Processing Dashboard:** Monitor progress with real-time status and download completed jobs.

---

## 🛠️ Tech Stack

- **Backend:** Python 3.11+, FastAPI, Uvicorn
- **AI Models:** Ollama (Qwen 2.5 / 3.5), OpenRouter, Grok (xAI)
- **Computer Vision & Audio:** FFmpeg, Librosa, Faster-Whisper
- **Database:** SQLite
- **Frontend:** HTML5, CSS3, JavaScript (Vanilla ES6+)

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.11+
- [FFmpeg](https://ffmpeg.org/download.html) (added to PATH or specified in `.env`)
- (Optional) [Ollama](https://ollama.ai) with `qwen2.5:7b` or `qwen3.5:4b`

### 2. Setup Environment
```bash
# Clone the repository
git clone https://github.com/hariharan-balamurugan/promptcut-ai.git
cd promptcut-ai

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install fastapi uvicorn python-dotenv pydantic requests librosa soundfile faster-whisper
```

### 3. Configure `.env`
Copy `.env.example` to `.env` and fill in your API keys / settings:
```bash
cp .env.example .env
```

### 4. Run the Application
```bash
# Start FastAPI backend
cd backend
python -m uvicorn main:app --reload --port 8000
```
Open `frontend/index.html` in your web browser.

---

## 📜 License
MIT License
