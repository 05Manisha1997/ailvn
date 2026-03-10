# AI Voice Navigator - Setup Guide

This guide provides instructions for setting up the backend infrastructure, databases, and API keys for the AI Voice Navigator project.

## 1. Azure Infrastructure Prerequisites

You will need the following Azure resources:

| Service | Usage | Key Info Needed |
| :--- | :--- | :--- |
| **Azure OpenAI** | Embeddings and Chat Completion | Endpoint, API Key, Deployment Names |
| **Azure AI Search** | Policy Retrieval-Augmented Generation (RAG) | Endpoint, Admin Key, Index Name |
| **Azure Cosmos DB** | Customer Identity & Policy Metadata | Endpoint, Primary Key, DB/Container Name |
| **Azure Communication Services** | Voice/PSTN Connectivity (Optional for Demo) | Connection String |
| **Azure Speech Services** | Fallback for TTS (Optional) | Key, Region |

## 2. Environment Configuration

Create a `.env` file in the root directory based on the provided `.env.example`.

```bash
# Azure Communication Services
ACS_CONNECTION_STRING="your_connection_string"
ACS_CALLBACK_BASE_URL="http://your-public-url:8000"

# Azure OpenAI
AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
AZURE_OPENAI_KEY="your_api_key"
AZURE_OPENAI_DEPLOYMENT="gpt-4o"
AZURE_OPENAI_EMBEDDING_DEPLOYMENT="text-embedding-3-large"
AZURE_OPENAI_API_VERSION="2024-08-01-preview"

# Azure AI Search
AZURE_SEARCH_ENDPOINT="https://your-search-service.search.windows.net"
AZURE_SEARCH_KEY="your_admin_key"
AZURE_SEARCH_INDEX="insurance-policies"

# Azure Cosmos DB (NoSQL API)
COSMOS_ENDPOINT="https://your-cosmos-db.documents.azure.com:443/"
COSMOS_KEY="your_primary_key"
COSMOS_DATABASE="insurance_db"
COSMOS_CONTAINER="policyholders"

# Azure Speech (Fallback TTS)
AZURE_SPEECH_KEY="your_speech_key"
AZURE_SPEECH_REGION="eastus"

# ElevenLabs (Primary TTS)
ELEVENLABS_API_KEY="your_elevenlabs_key"
ELEVENLABS_VOICE_ID="21m00Tcm4TlvDq8ikWAM"
```

## 3. Database & Search Setup

### Azure Cosmos DB
1. Create a Cosmos DB account (NoSQL API).
2. Create a Database named `insurance_db`.
3. Create a Container named `policyholders` with Partition Key `/policy_id`.

### Azure AI Search
Create an Index named `insurance-policies` with the following schema:

| Field Name | Type | Key | Searchable | Filterable | Facetable | Vector |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `id` | Edm.String | Yes | | | | |
| `policy_id` | Edm.String | | | Yes | Yes | |
| `content` | Edm.String | | Yes | | | |
| `section_title` | Edm.String | | Yes | | | |
| `coverage_type` | Edm.String | | | Yes | Yes | |
| `content_vector` | Collection(Edm.Single) | | | | | Dimensions: 1536* |

*\*Dimensions should match your embedding model (e.g., 1536 for `text-embedding-3-small` or 3072 for `large`).*

## 4. Seeding Data

### Step 1: Seed Customer Identity
Run the following command to populate Cosmos DB with sample policyholders for identity verification:
```bash
python database/seed_data.py
```

### Step 2: Index Policy Documents
Use the **Policy Manager** in the Dashboard (or use the CLI tool) to index your insurance PDFs:
```bash
python indexer/policy_indexer.py --pdf path/to/your/policy.pdf --policy-id POL-001
```

## 5. Running the Application

1. Install dependencies: `pip install -r requirements.txt`
2. Start the FastAPI server: `python main.py`
3. Access the dashboard: [http://localhost:8000/app](http://localhost:8000/app)
