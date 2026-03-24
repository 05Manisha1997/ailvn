"""
agents/crew_orchestrator.py

Phase 4 — CrewAI Agent Crew

Agents:
1. IntentClassifierAgent   — classifies user intent from transcript
2. ContextManagerAgent     — maintains conversation context window
3. RAGRetrieverAgent       — fetches relevant documents for the intent
4. ResponseBuilderAgent    — fills response templates with RAG data
5. SummaryAgent            — generates post-call summary

Uses Azure OpenAI (GPT-4o) or Ollama (Mistral/Llama3) as the LLM backbone.
"""
from crewai import Agent, Task, Crew, Process
from crewai.tools import BaseTool
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from typing import Optional
from pydantic import BaseModel, Field

from config.settings import get_settings
from utils.logger import logger

settings = get_settings()


# ── LLM Factory ───────────────────────────────────────────────────────────────

def get_llm(temperature: float = 0.1):
    """
    Returns configured LLM instance.
    Azure OpenAI if configured, otherwise Ollama (free local).
    """
    if settings.use_local_llm or not settings.azure_openai_key:
        logger.info("llm_using_ollama", model=settings.ollama_model)
        return ChatOpenAI(
            model=settings.ollama_model,
            base_url=f"{settings.ollama_base_url}/v1",
            api_key="ollama",
            temperature=temperature,
        )
    else:
        logger.info("llm_using_azure_openai", model=settings.azure_openai_deployment_name)
        return AzureChatOpenAI(
            azure_deployment=settings.azure_openai_deployment_name,
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_key,
            api_version="2024-02-01",
            temperature=temperature,
        )


# ── Custom Tools ──────────────────────────────────────────────────────────────

class IntentClassificationTool(BaseTool):
    name: str = "intent_classifier"
    description: str = (
        "Classifies the user's intent from their utterance. "
        "Returns intent label, confidence score, and any entities extracted."
    )

    SUPPORTED_INTENTS = [
        "ACCOUNT_BALANCE",
        "RECENT_TRANSACTIONS",
        "COMPLAINT",
        "PRODUCT_INFO",
        "BILLING_QUERY",
        "TECH_SUPPORT",
        "TRANSFER_AGENT",
        "LOAN_QUERY",
        "INSURANCE_CLAIM",
        "APPOINTMENT_BOOKING",
        "GENERAL_QUERY",
        "GOODBYE",
    ]

    def _run(self, utterance: str) -> dict:
        """Classify intent from user utterance."""
        import json
        llm = get_llm(temperature=0.0)

        prompt = f"""You are an intent classifier for a voice banking/service assistant.

Classify this user utterance into exactly ONE intent from this list:
{', '.join(self.SUPPORTED_INTENTS)}

Utterance: "{utterance}"

Respond ONLY with valid JSON in this exact format:
{{
  "intent": "INTENT_NAME",
  "confidence": 0.95,
  "entities": {{"key": "value"}},
  "reasoning": "Brief explanation"
}}"""

        response = llm.invoke(prompt)
        try:
            # Strip markdown code blocks if present
            text = response.content.strip().strip("```json").strip("```").strip()
            return json.loads(text)
        except Exception:
            return {
                "intent": "GENERAL_QUERY",
                "confidence": 0.5,
                "entities": {},
                "reasoning": "Parse error — defaulting to GENERAL_QUERY",
            }


class ContextSummarizationTool(BaseTool):
    name: str = "context_summarizer"
    description: str = (
        "Summarizes the conversation history into a concise context string "
        "for passing to other agents."
    )

    def _run(self, conversation_json: str) -> str:
        """Summarize conversation turns into context."""
        import json
        try:
            turns = json.loads(conversation_json)
        except Exception:
            return conversation_json

        if not turns:
            return "No prior conversation."

        lines = []
        for turn in turns[-5:]:  # Last 5 turns for context window efficiency
            lines.append(f"User: {turn.get('user_text', '')}")
            lines.append(f"Bot: {turn.get('bot_response', '')}")
        return "\n".join(lines)


# ── Agent Definitions ─────────────────────────────────────────────────────────

def create_intent_agent() -> Agent:
    return Agent(
        role="Intent Classifier",
        goal="Accurately classify the user's intent from their spoken text "
             "and extract key entities (account numbers, dates, product names).",
        backstory=(
            "You are a specialist in natural language understanding for voice banking. "
            "You analyze spoken transcripts — which may contain disfluencies, noise artifacts, "
            "and informal language — and map them to structured intents. "
            "You always return a confidence score and flag low-confidence classifications."
        ),
        tools=[IntentClassificationTool()],
        llm=get_llm(temperature=0.0),
        verbose=False,
        allow_delegation=False,
    )


def create_context_agent() -> Agent:
    return Agent(
        role="Context Manager",
        goal="Maintain the full conversation context window across turns, "
             "detect topic shifts, and provide relevant history to other agents.",
        backstory=(
            "You are responsible for conversational coherence. You track what the user has "
            "said, what the bot has responded, which intents have been active, and alert the "
            "crew when the user changes topic mid-call so new documents can be fetched."
        ),
        tools=[ContextSummarizationTool()],
        llm=get_llm(temperature=0.1),
        verbose=False,
        allow_delegation=False,
    )


def create_rag_agent() -> Agent:
    return Agent(
        role="Knowledge Retriever",
        goal="Retrieve accurate, up-to-date factual information from the document store "
             "that is specifically relevant to the user's current intent.",
        backstory=(
            "You are a knowledge retrieval specialist. Given an intent and user query, "
            "you search the vector database for the most relevant chunks of information "
            "and synthesize them into structured facts that the response builder can use."
        ),
        tools=[],  # RAG pipeline is called directly by orchestrator; agent summarizes results
        llm=get_llm(temperature=0.0),
        verbose=False,
        allow_delegation=False,
    )


def create_response_builder_agent() -> Agent:
    return Agent(
        role="Response Builder",
        goal="Fill the intent-specific response template with accurate factual data "
             "retrieved from documents, creating a natural, conversational response.",
        backstory=(
            "You craft the final spoken response. You take the fixed template configured "
            "for this intent and populate the dynamic {rag.field} placeholders with real "
            "data. Your responses must be concise (under 40 words for voice), natural-sounding, "
            "and grammatically correct for text-to-speech output."
        ),
        tools=[],
        llm=get_llm(temperature=0.3),
        verbose=False,
        allow_delegation=False,
    )


def create_summary_agent() -> Agent:
    return Agent(
        role="Call Summarizer",
        goal="Generate a comprehensive, professional post-call summary "
             "suitable for email delivery to the customer.",
        backstory=(
            "You create clear, well-structured call summaries. You analyze the full "
            "conversation transcript, highlight the issues raised, resolutions provided, "
            "documents referenced, and any follow-up actions needed."
        ),
        tools=[],
        llm=get_llm(temperature=0.2),
        verbose=False,
        allow_delegation=False,
    )


# ── Crew Orchestrator ─────────────────────────────────────────────────────────

class VoiceNavigatorCrew:
    """
    Main CrewAI orchestrator.
    Runs agents in sequence for each conversation turn.
    """

    def __init__(self):
        self.intent_agent = create_intent_agent()
        self.context_agent = create_context_agent()
        self.rag_agent = create_rag_agent()
        self.response_agent = create_response_builder_agent()
        self.summary_agent = create_summary_agent()

    def process_turn(
        self,
        user_text: str,
        conversation_history: list[dict],
        rag_context: str,
        response_template: str,
        sub_routes: list[dict],
    ) -> dict:
        """
        Process a single conversation turn through the agent crew.
        Returns: {intent, confidence, entities, response, sub_route_triggered}
        """
        import json

        history_json = json.dumps([
            {"user_text": t["user_text"], "bot_response": t["bot_response"]}
            for t in conversation_history[-5:]
        ])

        # Task 1: Classify Intent
        intent_task = Task(
            description=f"""
            Classify the intent of this user utterance.
            
            Recent conversation context:
            {history_json}
            
            Current user utterance: "{user_text}"
            
            Use the intent_classifier tool and return the full JSON result.
            """,
            expected_output="JSON with intent, confidence, entities, reasoning",
            agent=self.intent_agent,
        )

        # Task 2: Build Response
        response_task = Task(
            description=f"""
            Build a natural voice response using the template and factual context.
            
            Intent: Use the intent from the previous task's output.
            User query: "{user_text}"
            
            Response template (fill in {{{{rag.xxx}}}} placeholders):
            {response_template}
            
            Factual context from documents:
            {rag_context}
            
            Rules:
            - Keep response under 40 words (it will be spoken aloud)
            - Fill ALL {{{{rag.xxx}}}} placeholders with data from the context
            - If data is missing, say "I don't have that information right now"
            - Sound natural and conversational, not robotic
            - Do NOT mention document names or technical details
            
            Available sub-routes (mention the relevant one if applicable):
            {json.dumps(sub_routes)}
            
            Return JSON: {{"response": "...", "sub_route": "..." or null}}
            """,
            expected_output="JSON with response text and optional sub_route",
            agent=self.response_agent,
            context=[intent_task],
        )

        crew = Crew(
            agents=[self.intent_agent, self.response_agent],
            tasks=[intent_task, response_task],
            process=Process.sequential,
            verbose=False,
        )

        try:
            result = crew.kickoff()

            # Parse the last task output (response_task)
            output_text = str(result)
            output_text = output_text.strip("```json").strip("```").strip()
            parsed = json.loads(output_text)

            # Also get intent from intent_task
            intent_output = intent_task.output.raw if intent_task.output else "{}"
            intent_output = intent_output.strip("```json").strip("```").strip()
            intent_data = json.loads(intent_output) if intent_output else {}

            return {
                "intent": intent_data.get("intent", "GENERAL_QUERY"),
                "confidence": intent_data.get("confidence", 0.5),
                "entities": intent_data.get("entities", {}),
                "response": parsed.get("response", "I'm sorry, could you repeat that?"),
                "sub_route": parsed.get("sub_route"),
            }

        except Exception as e:
            logger.error("crew_process_failed", error=str(e))
            return {
                "intent": "GENERAL_QUERY",
                "confidence": 0.0,
                "entities": {},
                "response": "I'm sorry, I had trouble processing that. Could you say it again?",
                "sub_route": None,
            }

    def generate_summary(
        self,
        caller_name: str,
        caller_phone: str,
        conversation: list[dict],
        intent_history: list[str],
        doc_metadata: list[dict],
        agent_name: Optional[str] = None,
    ) -> str:
        """
        Generate a professional post-call summary for email delivery.
        Uses GPT-4o-mini equivalent — very low cost.
        """
        import json

        transcript_text = "\n".join([
            f"Turn {t.get('turn', i+1)}:\n  Caller: {t.get('user_text', '')}\n  Bot: {t.get('bot_response', '')}"
            for i, t in enumerate(conversation)
        ])

        task = Task(
            description=f"""
            Generate a professional post-call summary for email delivery.
            
            Caller Name: {caller_name}
            Caller Phone: {caller_phone}
            Intent Journey: {' → '.join(intent_history)}
            Live Agent Involved: {agent_name or 'No'}
            
            Documents Referenced:
            {json.dumps([m.get('source', 'unknown') for m in doc_metadata[:10]], indent=2)}
            
            Full Transcript:
            {transcript_text}
            
            Write a professional HTML email summary with these sections:
            1. Call Overview (date, caller, duration estimate)
            2. Topics Discussed (bullet points from intents)
            3. Key Information Provided (what was told to the caller)
            4. Resolution Status (resolved / escalated / pending)
            5. Next Steps (if any)
            6. Reference Number (use the call transcript for context)
            
            Format as clean HTML suitable for email.
            Keep it concise and professional.
            """,
            expected_output="HTML email body string",
            agent=self.summary_agent,
        )

        crew = Crew(
            agents=[self.summary_agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )

        try:
            result = crew.kickoff()
            return str(result)
        except Exception as e:
            logger.error("summary_generation_failed", error=str(e))
            return f"<p>Call summary for {caller_name} — {caller_phone}.<br>Topics: {', '.join(intent_history)}</p>"


_crew: Optional[VoiceNavigatorCrew] = None


def get_crew() -> VoiceNavigatorCrew:
    global _crew
    if _crew is None:
        _crew = VoiceNavigatorCrew()
    return _crew
