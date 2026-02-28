# Voice Navigator — AI-Powered Call System

Full implementation of the Voice Navigator architecture using Azure, CrewAI, ElevenLabs, LangChain, and ChromaDB.

## Architecture Overview

```
Caller → Genesis/Azure Comm → Phone Validation → Identity Verification
       → Azure Speech STT   → CrewAI Intent     → RAG Pipeline (ChromaDB)
       → Response Portal    → ElevenLabs TTS    → Azure Durable Orchestrator
       → Live Agent (Genesys screen-pop)         → Post-Call Email Summary
```

## Project Structure

```
voice-navigator/
├── config/
│   ├── settings.py              # All env vars & config
│   └── azure_clients.py         # Azure SDK client factories
├── services/
│   ├── phone_validator.py       # E.164 validation + Twilio Lookup
│   ├── speech_service.py        # Azure Speech STT + noise suppression
│   ├── tts_service.py           # ElevenLabs TTS + Azure TTS fallback
│   ├── verification_service.py  # Identity verification logic
│   └── email_service.py         # Post-call summary email
├── agents/
│   ├── crew_orchestrator.py     # CrewAI agent crew setup
│   ├── intent_agent.py          # Intent classification agent
│   ├── context_agent.py         # Conversation context manager
│   ├── rag_agent.py             # RAG retrieval agent
│   └── summary_agent.py         # Call summary generation agent
├── rag/
│   ├── document_loader.py       # Multi-source document ingestion
│   ├── chunker.py               # LangChain text splitting
│   ├── embedder.py              # Embedding generation
│   ├── vector_store.py          # ChromaDB vector store
│   └── retriever.py             # Semantic search & context assembly
├── memory/
│   ├── session_memory.py        # Cosmos DB-backed session storage (temporary)
│   └── temp_doc_store.py        # Temporary document memory
├── portal/
│   ├── response_portal.py       # Intent → template mapping engine
│   ├── template_engine.py       # RAG slot filling in templates
│   └── intent_router.py         # Sub-response routing logic
├── orchestrator/
│   ├── call_orchestrator.py     # Main call lifecycle manager
│   ├── call_handler.py          # WebSocket / call event handler
│   └── agent_transfer.py        # Live agent handoff logic
├── api/
│   ├── main.py                  # FastAPI application entry point
│   ├── routes/
│   │   ├── calls.py             # Call ingestion endpoints
│   │   ├── portal_admin.py      # Portal CRUD endpoints
│   │   └── webhooks.py          # Genesis / Azure webhooks
│   └── models/
│       ├── call_models.py       # Pydantic models for calls
│       └── portal_models.py     # Pydantic models for portal config
├── utils/
│   ├── logger.py                # Structured logging
│   └── helpers.py               # Utility functions
├── tests/
│   ├── test_phone_validator.py
│   ├── test_intent_agent.py
│   ├── test_rag_pipeline.py
│   └── test_call_orchestrator.py
├── portal_ui/                   # React admin portal
│   ├── src/
│   │   ├── App.jsx
│   │   ├── pages/
│   │   │   ├── IntentConfig.jsx
│   │   │   ├── LiveCalls.jsx
│   │   │   └── CallHistory.jsx
│   │   └── components/
│   │       ├── TemplateEditor.jsx
│   │       └── SubRouteBuilder.jsx
│   └── package.json
├── requirements.txt
├── docker-compose.yml
├── .env.example
└── README.md
```

## Quick Start

### 1. Prerequisites
- Python 3.11+
- Node.js 18+ (for portal UI)
- Docker + Docker Compose (for ChromaDB)
- Azure account (free tier sufficient for MVP)

### 2. Clone & Install
```bash
git clone <repo>
cd voice-navigator
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Environment
```bash
cp .env.example .env
# Fill in your Azure, ElevenLabs, and Genesys credentials
```

### 4. Start Infrastructure
```bash
docker-compose up -d  # Starts ChromaDB
```

### 5. Run the API Server
```bash
uvicorn api.main:app --reload --port 8000
```

### 6. Run Portal UI
```bash
cd portal_ui && npm install && npm start
```

## Free Tier Services Used
| Service | Free Allowance |
|---------|---------------|
| Azure Speech STT | 5 hrs/month |
| Azure Speech TTS | 500K chars/month |
| ElevenLabs | 10K chars/month |
| Azure Functions | 1M executions/month |
| Azure Cosmos DB | 1000 RU/s, 25GB |
| Azure Comm. Services | 100 emails/day |
| ChromaDB | Open source, unlimited |
| CrewAI | Open source, unlimited |
| Ollama (local LLM) | Unlimited, free |

## Estimated Monthly Cost at 1000 calls: ~$11–35
