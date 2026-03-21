# Azure Deployment — Portal, Database & Hosting

This document lists **Azure free-tier–friendly services** for running the Voice Navigator portal and API, and how to deploy.

---

## 1. Database: Azure vs MongoDB / PostgreSQL

| Option | Use when | Free tier |
|--------|----------|-----------|
| **Azure Cosmos DB** (current) | You want everything on Azure, minimal ops. | **Always free:** 1000 RU/s, 25 GB storage. Sufficient for response templates and call/session data. |
| **Azure Database for PostgreSQL** | You prefer SQL and relational schema. | **Not** in Azure always-free list. 12-month free trial only (Flexible Server, then paid). |
| **MongoDB Atlas** | You want a managed NoSQL DB outside Azure. | Free M0 cluster (512 MB). You’d need to add a DB adapter in code (Cosmos API is different). |

**Recommendation:** **Keep using Azure Cosmos DB** for the portal and call data. It’s already integrated, fits the “Azure-first, free where possible” requirement, and response templates + sessions fit the document model. Use MongoDB or PostgreSQL only if you have a strong reason (e.g. existing tooling or SQL requirements).

---

## 2. Azure free / low-cost services to run the app

| Service | Role | Free / trial |
|---------|------|--------------|
| **Azure Cosmos DB** | Store response templates (portal config) and call sessions | Always free: 1000 RU/s, 25 GB |
| **Azure App Service** (Linux) | Host FastAPI + portal UI (single app) | Free F1: 10 apps, 1 GB storage, 60 min/day compute |
| **Azure Container Apps** | Alternative to App Service (container-based) | Free tier: 180,000 vCPU-seconds, 360,000 GiB-seconds/month |
| **Azure Blob Storage** | RAG documents | 5 GB LRS free (first 12 months), then low cost |
| **Azure OpenAI** | LLM + embeddings | Pay-per-use; use **Ollama** locally for $0 if preferred |
| **Azure Speech** | STT / TTS | 5 hrs STT, 500K chars TTS/month free |
| **Azure Communication Services** | Email / calls | 100 emails/day, 60 min calls/month free |

Portal and API run as **one app** (FastAPI serves both `/api` and `/portal`), so one App Service or one Container App is enough.

---

## 3. Deployment checklist

1. **Database (Cosmos DB)**  
   - Create Cosmos DB account (e.g. serverless or autoscale with 400 RU).  
   - Create database `layavoicenavigator` and containers: `response_templates`, `sessions`, `calls`.  
   - Set partition key (e.g. `/id` for templates and sessions).  
   - Copy endpoint and key into app settings (see below).

2. **App hosting (choose one)**  
   - **Option A – App Service**  
     - Create a Linux App Service (e.g. Python 3.11).  
     - Deploy via GitHub Actions, Azure CLI, or ZIP deploy.  
     - Set startup: `uvicorn api.main:app --host 0.0.0.0 --port 8000` (or the port App Service assigns, often 8000 or 80).  
   - **Option B – Container Apps**  
     - Build image from project `Dockerfile`.  
     - Push to Azure Container Registry (or Docker Hub).  
     - Create Container App from image; set port 8000; add env vars.

3. **Environment variables (Azure)**  
   Set in App Service “Configuration” or Container Apps “Secrets / env”:

   - `COSMOS_DB_ENDPOINT`, `COSMOS_DB_KEY`  
   - `COSMOS_DB_DATABASE=layavoicenavigator`  
   - `COSMOS_DB_CONTAINER_TEMPLATES=response_templates`  
   - `COSMOS_DB_CONTAINER_SESSIONS=sessions`  
   - `COSMOS_DB_CONTAINER_CALLS=calls`  
   - Plus any existing vars: Azure Speech, OpenAI (or Ollama), Blob, etc.

4. **Portal URL**  
   - If the API is at `https://<your-app>.azurewebsites.net`, open:  
     **`https://<your-app>.azurewebsites.net/portal/`**  
   - The portal uses the same origin for `/api`, so no CORS or API URL change is needed.

5. **ChromaDB (RAG)**  
   - For production, run ChromaDB in a separate container (e.g. same Container Apps environment or a small VM) and set `CHROMA_HOST` / `CHROMA_PORT` in the app.  
   - Or use Azure AI Search (paid) as vector store later.

---

## 4. Code / config already in place

- **Portal UI** loads templates from `GET /api/templates` and saves via `PUT /api/templates/{intent}` (stored in Cosmos `response_templates`).
- **Calls** are listed with `GET /api/calls?active_only=true|false` (from Cosmos `sessions`).
- **Static portal** is served at `/portal` by FastAPI when `portal_ui` directory exists (see `api/main.py`).
- **`.env.example`** documents all variables; use the same names in Azure configuration.

No MongoDB or PostgreSQL code is required unless you decide to add an alternate database adapter later.
