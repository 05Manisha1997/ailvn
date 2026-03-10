
Act as an expert product manager aty companies like microsoft which have past experience with microsoft product building. Your job is to streamline the process through the tech stack. 

Idea: A ai voice navigator fit in call. Problem: An insurance company facing problems in answering queries on time, which have led to some loss. The person call for an instance "Is my insurance coverage full at this hospital/ clinic/ etc?", "how much is covered?", and similar questions. Job: The job of the company is to recieve call from their clients and verify their details and check the policy for them. And respond them with their answer. Note: Cost is not a problem, as it is funded by the organisation. Use of open ai APIs is appreciated. Crew.ai is recommended for agentic flow by the mentor. Thanks! Also, provide the snippets of how the code will look like.

Flow: 
1. Call recieve
2. answer the user
3. intent extract 
4. rag used to extract the knowledge from the policy document 
5. answer is given to the user 
6. calls goes on

the response will be limited, llm is used for extraction of policy but the response to user is fill in the blank. the answer is framed except the number or hospital or detail

Current tech stack in mind: Azure, Openai, CREW AI, 11 LAB, use of RAG.

Show more
6:07 PM
AI Voice Navigator for Insurance Query Resolution
Architecture Overview
Let me walk you through the complete system design and implementation approach.

Tech Stack Decision
Layer	Technology	Why
Telephony	Azure Communication Services	Native Azure integration, PSTN support
STT	Azure Speech Services (real-time)	Low latency, better than Whisper for live calls
TTS	ElevenLabs	Natural voice, reduces robotic feel in insurance context
Orchestration	CrewAI	Multi-agent policy verification flow
LLM	GPT-4o	Tool calling + structured extraction
RAG	Azure AI Search + LangChain	Policy document retrieval
Storage	Azure Cosmos DB	Client profiles + policy metadata
Backend	FastAPI on Azure Container Apps	Scalable, async-friendly
System Flow (Detailed)
Incoming Call (PSTN)
       ↓
Azure Communication Services
       ↓
Azure Speech → STT (streaming)
       ↓
CrewAI Orchestrator
    ├── Agent 1: Identity Verifier
    ├── Agent 2: Intent Extractor
    ├── Agent 3: RAG Policy Retriever
    └── Agent 4: Response Formatter (Fill-in-the-blank)
       ↓
ElevenLabs TTS → Audio Stream back to caller
Core Code Structure
1. Call Handler (FastAPI + Azure Communication Services)
python
# call_handler.py
from fastapi import FastAPI, WebSocket
from azure.communication.callautomation import CallAutomationClient
from azure.communication.callautomation.models import MediaStreamingOptions
import asyncio

app = FastAPI()
call_client = CallAutomationClient.from_connection_string(os.getenv("ACS_CONNECTION_STRING"))

@app.post("/incoming-call")
async def handle_incoming_call(request: Request):
    """Webhook triggered when a call comes in via Azure Communication Services"""
    event_data = await request.json()
    
    call_connection_id = event_data["callConnectionId"]
    
    # Start media streaming for real-time audio
    media_streaming = MediaStreamingOptions(
        transport_url=f"wss://your-app.azurecontainerapps.io/audio-stream/{call_connection_id}",
        transport_type="websocket",
        content_type="audio/pcm",
        channel_type="mixed"
    )
    
    call_client.answer_call(
        incoming_call_context=event_data["incomingCallContext"],
        cognitive_services_endpoint=os.getenv("AZURE_COGNITIVE_ENDPOINT"),
        media_streaming=media_streaming
    )
    
    return {"status": "answered"}


@app.websocket("/audio-stream/{call_id}")
async def audio_stream(websocket: WebSocket, call_id: str):
    """Real-time bidirectional audio stream"""
    await websocket.accept()
    
    navigator = InsuranceVoiceNavigator(call_id)
    await navigator.run(websocket)
2. CrewAI Multi-Agent Orchestration
python
# agents/insurance_crew.py
from crewai import Agent, Task, Crew, Process
from crewai.tools import tool
from langchain_openai import AzureChatOpenAI

llm = AzureChatOpenAI(
    azure_deployment="gpt-4o",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version="2024-08-01-preview"
)

# ── AGENT 1: Identity Verifier ──────────────────────────────────────────────
identity_agent = Agent(
    role="Identity Verification Specialist",
    goal="Verify the caller's identity using their policy number, DOB, and name",
    backstory="You are responsible for confirming the caller is a valid policyholder before any policy info is shared.",
    llm=llm,
    tools=[verify_identity_tool],
    verbose=True
)

# ── AGENT 2: Intent Extractor ───────────────────────────────────────────────
intent_agent = Agent(
    role="Insurance Query Intent Extractor",
    goal="Extract structured intent from caller's natural language query",
    backstory="You parse what the caller is asking — coverage check, hospital eligibility, claim limit — into structured fields.",
    llm=llm,
    verbose=True
)

# ── AGENT 3: RAG Policy Retriever ───────────────────────────────────────────
rag_agent = Agent(
    role="Policy Document Analyst",
    goal="Retrieve and extract the exact policy clause relevant to the user's query",
    backstory="You have deep access to the policy documents via vector search. You extract precise numbers, limits, and conditions.",
    llm=llm,
    tools=[policy_rag_tool],
    verbose=True
)

# ── AGENT 4: Response Formatter ─────────────────────────────────────────────
response_agent = Agent(
    role="Customer Response Formatter",
    goal="Frame the final answer using fill-in-the-blank templates. Never freeform.",
    backstory="You take extracted data and slot it into pre-approved response templates only. No improvisation.",
    llm=llm,
    verbose=True
)
3. CrewAI Tasks & Execution
python
# agents/tasks.py

def build_crew_for_query(caller_input: str, caller_id: str, conversation_history: list) -> str:
    
    verify_task = Task(
        description=f"""
        Caller ID from system: {caller_id}
        Verify this caller's identity. Check: name, DOB, policy number match in DB.
        Conversation so far: {conversation_history}
        If not verified, return a prompt to ask for missing detail.
        """,
        expected_output="Verified: True/False, PolicyID: <id>, MemberName: <name>",
        agent=identity_agent
    )

    intent_task = Task(
        description=f"""
        Caller said: "{caller_input}"
        Extract intent into structured JSON:
        - query_type: [coverage_check | hospital_eligibility | claim_limit | deductible | other]
        - hospital_name: <if mentioned>
        - treatment_type: <if mentioned>
        - policy_id: <from verification>
        """,
        expected_output="JSON with query_type, hospital_name, treatment_type",
        agent=intent_agent,
        context=[verify_task]
    )

    rag_task = Task(
        description="""
        Using the structured intent, query the policy document vector store.
        Extract: coverage percentage, max limit, network status of hospital, exclusions.
        Return raw extracted values only — no prose.
        """,
        expected_output="coverage_pct: X%, limit: $Y, hospital_in_network: True/False, exclusions: [...]",
        agent=rag_agent,
        context=[intent_task]
    )

    format_task = Task(
        description="""
        Use ONLY the approved templates below. Slot in extracted values. 
        
        Templates:
        - Hospital coverage: "Your policy covers [coverage_pct] of treatment costs at [hospital_name], up to a maximum of [limit]."
        - Out of network: "[hospital_name] is not in your network. Out-of-pocket costs may apply."
        - Claim limit: "Your remaining claim limit for [treatment_type] is [remaining_limit]."
        - Not covered: "[treatment_type] is not covered under your current plan."
        
        Pick the right template. Fill in values. Output final spoken response only.
        """,
        expected_output="Single sentence response ready for TTS",
        agent=response_agent,
        context=[rag_task]
    )

    crew = Crew(
        agents=[identity_agent, intent_agent, rag_agent, response_agent],
        tasks=[verify_task, intent_task, rag_task, format_task],
        process=Process.sequential,
        verbose=True
    )

    result = crew.kickoff()
    return str(result)
4. RAG Tool — Azure AI Search
python
# tools/rag_tool.py
from crewai.tools import tool
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from openai import AzureOpenAI

search_client = SearchClient(
    endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
    index_name="insurance-policies",
    credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_KEY"))
)

openai_client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version="2024-08-01-preview"
)

@tool("Policy RAG Retriever")
def policy_rag_tool(query: str, policy_id: str) -> str:
    """Retrieves relevant policy clauses from vector store for a given query and policy ID."""
    
    # Generate embedding for query
    embedding_response = openai_client.embeddings.create(
        input=query,
        model="text-embedding-3-large"
    )
    query_vector = embedding_response.data[0].embedding
    
    # Hybrid search: vector + keyword, filtered by policy_id
    vector_query = VectorizedQuery(
        vector=query_vector,
        k_nearest_neighbors=5,
        fields="content_vector"
    )
    
    results = search_client.search(
        search_text=query,
        vector_queries=[vector_query],
        filter=f"policy_id eq '{policy_id}'",
        select=["content", "section_title", "coverage_type"],
        top=3
    )
    
    extracted = []
    for r in results:
        extracted.append(f"[{r['section_title']}]: {r['content']}")
    
    return "\n\n".join(extracted)
5. ElevenLabs TTS Streaming
python
# tts/elevenlabs_streamer.py
import httpx
import asyncio

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = "your-chosen-insurance-voice-id"  # Warm, professional voice

async def stream_tts_to_call(text: str, websocket) -> None:
    """Stream ElevenLabs TTS audio directly back to caller via WebSocket"""
    
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream"
    
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2",      # Lowest latency model
        "voice_settings": {
            "stability": 0.75,
            "similarity_boost": 0.85,
            "style": 0.2,
            "use_speaker_boost": True
        },
        "output_format": "pcm_16000"         # Match Azure ACS expected format
    }
    
    async with httpx.AsyncClient() as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            async for chunk in response.aiter_bytes(chunk_size=4096):
                await websocket.send_bytes(chunk)
6. Main Voice Navigator Orchestrator
python
# navigator.py
import azure.cognitiveservices.speech as speechsdk

class InsuranceVoiceNavigator:
    def __init__(self, call_id: str):
        self.call_id = call_id
        self.conversation_history = []
        self.verified = False
        self.policy_id = None
        self.caller_id = None
        
        # Azure STT config — real-time streaming
        self.speech_config = speechsdk.SpeechConfig(
            subscription=os.getenv("AZURE_SPEECH_KEY"),
            region=os.getenv("AZURE_SPEECH_REGION")
        )
        self.speech_config.speech_recognition_language = "en-US"

    async def run(self, websocket):
        """Main loop — listen, process, respond"""
        
        # Greet the caller
        await stream_tts_to_call(
            "Thank you for calling InsureCo. Please state your policy number and date of birth to begin.",
            websocket
        )
        
        while True:
            # Receive audio chunk from caller
            audio_data = await websocket.receive_bytes()
            
            # STT — transcribe incoming audio
            transcribed_text = await self.transcribe(audio_data)
            if not transcribed_text:
                continue
            
            self.conversation_history.append({
                "role": "user", 
                "content": transcribed_text
            })
            
            # Run CrewAI agents
            response_text = build_crew_for_query(
                caller_input=transcribed_text,
                caller_id=self.caller_id,
                conversation_history=self.conversation_history
            )
            
            self.conversation_history.append({
                "role": "assistant",
                "content": response_text
            })
            
            # Stream response back as voice
            await stream_tts_to_call(response_text, websocket)

    async def transcribe(self, audio_bytes: bytes) -> str:
        """Azure STT for real-time transcription"""
        audio_stream = speechsdk.audio.PushAudioInputStream()
        audio_config = speechsdk.audio.AudioConfig(stream=audio_stream)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=self.speech_config,
            audio_config=audio_config
        )
        audio_stream.write(audio_bytes)
        audio_stream.close()
        result = recognizer.recognize_once()
        return result.text if result.reason == speechsdk.ResultReason.RecognizedSpeech else ""
Policy Document Indexing Pipeline
python
# indexer/policy_indexer.py
# Run this offline to index all policy PDFs into Azure AI Search

from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter

def index_policy_document(pdf_path: str, policy_id: str):
    loader = PyPDFLoader(pdf_path)
    pages = loader.load()
    
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,        # Keep chunks small for insurance precision
        chunk_overlap=100,
        separators=["\n\n", "\n", ".", " "]
    )
    chunks = splitter.split_documents(pages)
    
    documents_to_index = []
    for i, chunk in enumerate(chunks):
        embedding = get_embedding(chunk.page_content)  # text-embedding-3-large
        
        documents_to_index.append({
            "id": f"{policy_id}-chunk-{i}",
            "policy_id": policy_id,
            "content": chunk.page_content,
            "section_title": extract_section_title(chunk),
            "content_vector": embedding,
            "coverage_type": classify_coverage_type(chunk.page_content)  # GPT-4o call
        })
    
    search_client.upload_documents(documents_to_index)
    print(f"Indexed {len(documents_to_index)} chunks for policy {policy_id}")
Response Template Bank
python
# templates/response_templates.py
# These are the ONLY responses the system outputs — LLM fills slots, never freestyles

TEMPLATES = {
    "hospital_covered": "Your policy covers {coverage_pct} of treatment costs at {hospital_name}, up to a maximum of {max_limit}.",
    
    "hospital_not_in_network": "{hospital_name} is not within your network. Out-of-pocket costs will apply. Your nearest in-network facility is {nearest_network_hospital}.",
    
    "treatment_covered": "{treatment_type} is covered under your plan at {coverage_pct}, with a benefit limit of {limit} per year.",
    
    "treatment_not_covered": "{treatment_type} is not covered under your current {plan_name} plan.",
    
    "deductible_status": "Your annual deductible is {deductible_amount}. You have {deductible_remaining} remaining before full coverage activates.",
    
    "claim_limit_remaining": "You have {remaining_limit} remaining in your {benefit_category} benefit for this policy year.",
    
    "identity_prompt": "I need to verify your identity. Could you please provide your {missing_field}?",
    
    "fallback_human": "I wasn't able to find a clear answer for your query. Let me transfer you to a specialist right away."
}
```

---

## Deployment Architecture on Azure
```
┌─────────────────────────────────────────────────────┐
│                    Azure Infrastructure              │
│                                                     │
│  PSTN/VoIP ──→ Azure Communication Services         │
│                        │                            │
│              Azure Container Apps                   │
│              (FastAPI + Navigator)                  │
│                    │         │                      │
│         Azure Speech       ElevenLabs API           │
│           (STT)               (TTS)                 │
│                    │                                │
│              CrewAI Agents                          │
│           (GPT-4o via Azure OpenAI)                 │
│                    │                                │
│         Azure AI Search          Cosmos DB          │
│         (Policy RAG)         (Client Profiles)      │
│                                                     │
│  Monitoring: Azure App Insights + Log Analytics     │
└─────────────────────────────────────────────────────┘
Key Design Decisions Worth Noting
Why fill-in-the-blank over freeform LLM response? In insurance, a hallucinated number (e.g., wrong coverage %) is a legal liability. Templates ensure every response is auditable and the LLM only extracts values, never authors claims.

Why CrewAI sequential process? Identity must be verified before any policy data is retrieved — a hard dependency chain makes sequential the right process type here. Each agent has a single, auditable responsibility.

Why Azure Speech over Whisper for STT? Whisper processes chunks, Azure Speech does true streaming recognition — critical for low-latency call feel. Callers notice 2+ second delays immediately.

Latency budget to target: STT ~300ms + CrewAI pipeline ~1.5–2s + ElevenLabs stream start ~400ms = ~2.5s total. Acceptable for insurance queries. Add a "Let me check that for you..." interim TTS to bridge the gap during CrewAI processing.

what needs to be installed? ..

6:15 PM


what needs to be installed? 

Claude is AI and can make mistakes. Please double-check responses.
