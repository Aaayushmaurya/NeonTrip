# NeonTrip ✦ AI Travel Planner India

NeonTrip is a production-grade, AI-powered travel itinerary generator tailored specifically for India. It uses the Model Context Protocol (MCP) to supply an AI agent with live real-world data (weather, hotels, flights, and currency) to craft realistic, budget-aware, day-by-day travel plans.

<div align="center">
  <img src="docs/screenshot1.png" alt="NeonTrip Hero" width="800"/>
  <br><br>
  <img src="docs/screenshot2.png" alt="NeonTrip Form" width="800"/>
</div>

## ✨ Features

- **Live Real-World Data**: Uses MCP to connect to live tools, so the AI never hallucinates prices or weather.
  - **🌤️ Weather**: Live forecasts and seasonal advisories via Open-Meteo.
  - **🏨 Hotels**: Real hotel data sourced directly from OpenStreetMap (Overpass API) and grouped into Budget, Mid-Range, and Premium tiers.
  - **💱 Currency**: Live ECB exchange rates.
  - **✈️ Travel Costs**: Distance-based travel cost formulas (Haversine formula) for flights, trains, cars, and bikes.
- **Agentic AI Architecture**: Powered by Groq (`llama-3.3-70b-versatile` with automatic failover fallback) running a robust tool-calling loop.
- **Local Persistent Memory**: Uses `aiosqlite` to store conversation history and caching.
- **Modern Glassmorphism UI**: A stunning, responsive Vanilla HTML/CSS/JS frontend featuring dynamic weather backgrounds, a live calendar, and beautiful day-by-day cost breakdown cards.
- **Local Food Recommendations**: The prompt engineering forces the AI to pick *specific local dishes* and *real top-rated restaurants* for every meal, avoiding generic placeholders.

## 🛠️ Tech Stack

- **Backend**: Python 3.12, FastAPI, Uvicorn, SQLite (`aiosqlite`)
- **AI / LLM**: Groq API (`llama-3.3-70b-versatile`)
- **Architecture**: Model Context Protocol (MCP) bridging
- **Frontend**: Vanilla HTML5, CSS3, JavaScript (No heavy frameworks, ultra-fast loading)

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.10+ (uv recommended)
- A [Groq API Key](https://console.groq.com/keys)

### 2. Setup
Clone the repository and install the dependencies:
```bash
pip install -r requirements.txt
```

### 3. Environment Variables
Create a `.env` file in the root directory and add your API keys:
```env
GROQ_API_KEY=gsk_your_api_key_here
```

### 4. Run the Server
Start the FastAPI server (which automatically mounts the frontend):
```bash
python main.py
```
*The server will start on `http://0.0.0.0:8000`.*

### 5. Access the App
Open your browser and navigate to:
**`http://localhost:8000/ui`**

## 📂 Project Structure

- `main.py` - FastAPI entry point, mounts the UI and agent endpoints.
- `agent_logic.py` - The core AI loop, system prompts, tool dispatch, and robust JSON parser.
- `db.py` - SQLite operations for saving conversational memory.
- `mcp_bridge.py` - Connects the AI function-calling schema to the underlying Python tools.
- `tools/` - Contains the individual tools (weather, flights, hotels, geocoding) used by the AI.
- `static/` - Contains the frontend assets (`index.html` and images).

## 💡 Troubleshooting

- **Rate Limits (429 / 413)**: If you hit a Groq API rate limit or token limit, the system is designed to automatically try falling back to smaller models (e.g., `llama-3.1-8b-instant`). If the query is still too large, try generating a trip with a shorter duration.
- **Port in Use**: If port 8000 is taken, modify the `uvicorn.run()` call in `main.py`.
