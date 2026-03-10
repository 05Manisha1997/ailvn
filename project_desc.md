# Project Description: AI Voice Navigator for Insurance

This project is an AI-powered voice call system designed to streamline insurance query resolution. It uses a multi-agent orchestration to verify caller identity, extract intent, retrieve policy information using RAG (Retrieval-Augmented Generation), and respond via natural-sounding text-to-speech.

## 1. Libraries and Tools Used

| Tool / Library | Description |
| :--- | :--- |
| **FastAPI** | High-performance Python web framework used for the backend API and handling incoming call webhooks. |
| **CrewAI** | Multi-agent orchestration framework that manages specialized AI agents (Identity Verifier, Intent Extractor, etc.). |
| **Azure Communication Services (ACS)** | Handles PSTN (Public Switched Telephone Network) connectivity and call automation. |
| **Azure OpenAI (GPT-4o)** | Powers the intelligence for intent extraction, policy analysis, and response formatting. |
| **Azure AI Search** | Vector database used for RAG to retrieve relevant clauses from policy documents. |
| **Azure Cosmos DB** | NoSQL database for storing client profiles and policyholder metadata. |
| **Azure Speech Services** | Provides low-latency, real-time Speech-to-Text (STT) for transcribing live calls. |
| **ElevenLabs** | Advanced Text-to-Speech (TTS) engine used for natural, high-quality voice responses. |
| **LangChain** | Used for document loading, text splitting, and integrating with Azure AI Search. |
| **Pydantic** | Data validation and settings management using Python type annotations. |

## 2. How to Download and Set Up

### Prerequisites
- Python 3.10 or higher.
- An Azure account with active resources (OpenAI, Search, Cosmos DB, Speech, ACS).
- An ElevenLabs API key.

### Installation Steps

1. **Clone the Repository**:
   ```powershell
   git clone <repository-url>
   cd ailvn
   ```

2. **Create a Virtual Environment**:
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables**:
   Copy `.env.example` to a new file named `.env` and fill in your API keys and resource endpoints:
   ```powershell
   copy .env.example .env
   ```

## 3. How to Run the Project

### Database Seeding
To populate Cosmos DB with sample policyholders for testing:
```powershell
python database/seed_data.py
```

### Policy Indexing (RAG Setup)
To index a policy document (PDF) into Azure AI Search for retrieval:
```powershell
python indexer/policy_indexer.py --pdf path/to/your/policy.pdf --policy-id POL-001
```

### Start the Main Application
Run the FastAPI server to start handling calls and serve the dashboard:
```powershell
python main.py
```
*The API will be available at `http://localhost:8000`. The dashboard can be accessed at `http://localhost:8000/app`.*
