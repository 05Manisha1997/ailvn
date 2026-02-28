"""
portal/response_portal.py

Phase 6 — In-House Response Portal

Manages intent-to-template mappings stored in Azure Cosmos DB.
Business users configure templates via the admin UI.
Dynamic {rag.xxx} slots are filled at runtime with RAG-retrieved facts.

Template format example:
  "Your account balance is {rag.balance}. 
   Your last transaction was {rag.last_txn} on {rag.last_txn_date}."

Sub-routes allow conditional branching based on intent + context:
  ACCOUNT_BALANCE → sub-route "HIGH_BALANCE" if balance > threshold
"""
import re
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

from config.azure_clients import get_cosmos_containers
from utils.logger import logger


@dataclass
class SubRoute:
    route_id: str
    label: str              # e.g. "OVERDUE_ACCOUNT"
    condition: str          # e.g. "rag.days_overdue > 30"
    response_override: str  # Override template for this condition
    next_intent: Optional[str] = None   # Trigger follow-up intent


@dataclass
class ResponseTemplate:
    intent: str
    template: str
    voice_id: Optional[str] = None  # ElevenLabs voice override per intent
    sub_routes: list[SubRoute] = field(default_factory=list)
    doc_sources: list[dict] = field(default_factory=list)  # Sources to fetch for this intent
    max_response_length: int = 150   # Characters — keep short for TTS
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# Default templates loaded when Cosmos DB is empty or unavailable
DEFAULT_TEMPLATES: dict[str, ResponseTemplate] = {
    "ACCOUNT_BALANCE": ResponseTemplate(
        intent="ACCOUNT_BALANCE",
        template="Your current balance is {rag.balance}. Your last transaction was {rag.last_txn}.",
        sub_routes=[
            SubRoute("SR-001", "NEGATIVE_BALANCE", "rag.balance_numeric < 0",
                     "Your account is overdrawn by {rag.overdraft_amount}. "
                     "Please make a deposit to avoid fees."),
            SubRoute("SR-002", "LARGE_BALANCE", "rag.balance_numeric > 100000",
                     "Your balance is {rag.balance}. Would you like information about "
                     "our wealth management services?"),
        ],
        doc_sources=[{"type": "text", "content": "MOCK_BALANCE", "title": "account_data"}],
    ),
    "RECENT_TRANSACTIONS": ResponseTemplate(
        intent="RECENT_TRANSACTIONS",
        template="Your last 3 transactions: {rag.txn_1}, {rag.txn_2}, and {rag.txn_3}.",
        doc_sources=[{"type": "text", "content": "MOCK_TRANSACTIONS", "title": "txn_data"}],
    ),
    "COMPLAINT": ResponseTemplate(
        intent="COMPLAINT",
        template="I understand your concern about {rag.issue_type}. "
                 "I've raised ticket number {rag.ticket_id} for you. "
                 "You'll receive an update within {rag.resolution_time}.",
        sub_routes=[
            SubRoute("SR-003", "ESCALATE", "rag.severity == 'high'",
                     "Due to the severity of this issue, I'm connecting you to a specialist now.",
                     next_intent="TRANSFER_AGENT"),
        ],
    ),
    "PRODUCT_INFO": ResponseTemplate(
        intent="PRODUCT_INFO",
        template="{rag.product_name}: {rag.description}. "
                 "The rate is {rag.rate}. Minimum deposit: {rag.min_deposit}.",
        doc_sources=[{"type": "azure_blob", "prefix": "products/"}],
    ),
    "BILLING_QUERY": ResponseTemplate(
        intent="BILLING_QUERY",
        template="Your {rag.billing_period} bill is {rag.amount}, due on {rag.due_date}. "
                 "Payment status: {rag.payment_status}.",
    ),
    "TECH_SUPPORT": ResponseTemplate(
        intent="TECH_SUPPORT",
        template="For {rag.issue_description}, please {rag.resolution_steps}. "
                 "If this doesn't help, I can connect you to technical support.",
        doc_sources=[{"type": "azure_blob", "prefix": "support/"}],
    ),
    "TRANSFER_AGENT": ResponseTemplate(
        intent="TRANSFER_AGENT",
        template="I'll connect you to a {rag.department} specialist now. "
                 "Estimated wait time is {rag.wait_time}. "
                 "Your reference number is {rag.reference_id}.",
    ),
    "LOAN_QUERY": ResponseTemplate(
        intent="LOAN_QUERY",
        template="Your {rag.loan_type} loan: balance {rag.loan_balance}, "
                 "next payment {rag.next_payment} due {rag.due_date}.",
        doc_sources=[{"type": "azure_blob", "prefix": "loans/"}],
    ),
    "GENERAL_QUERY": ResponseTemplate(
        intent="GENERAL_QUERY",
        template="I can help with account balances, transactions, complaints, "
                 "products, billing, and loans. What would you like to know?",
    ),
    "GOODBYE": ResponseTemplate(
        intent="GOODBYE",
        template="Thank you for calling. A summary of our conversation will be "
                 "emailed to you shortly. Have a great day!",
    ),
}


class ResponsePortal:
    """
    Intent-to-response mapping engine.
    Templates are loaded from Cosmos DB with in-memory cache.
    Falls back to DEFAULT_TEMPLATES if Cosmos DB is unavailable.
    """

    CACHE_TTL_SECONDS = 300  # Refresh templates every 5 minutes

    def __init__(self):
        self._cache: dict[str, ResponseTemplate] = {}
        self._cache_loaded_at: Optional[datetime] = None
        self._use_cosmos = True
        self._load_templates()

    def _load_templates(self):
        """Load templates from Cosmos DB into memory cache."""
        try:
            _, templates_container = get_cosmos_containers()
            items = list(templates_container.read_all_items())
            for item in items:
                sub_routes = [SubRoute(**sr) for sr in item.get("sub_routes", [])]
                template = ResponseTemplate(
                    intent=item["intent"],
                    template=item["template"],
                    voice_id=item.get("voice_id"),
                    sub_routes=sub_routes,
                    doc_sources=item.get("doc_sources", []),
                    max_response_length=item.get("max_response_length", 150),
                    enabled=item.get("enabled", True),
                )
                self._cache[item["intent"]] = template
            self._cache_loaded_at = datetime.utcnow()
            logger.info("templates_loaded_from_cosmos", count=len(self._cache))
        except Exception as e:
            logger.warning("cosmos_load_failed_using_defaults", error=str(e))
            self._cache = dict(DEFAULT_TEMPLATES)
            self._use_cosmos = False
            self._cache_loaded_at = datetime.utcnow()

    def _maybe_refresh_cache(self):
        """Refresh template cache if TTL has expired."""
        if not self._cache_loaded_at:
            self._load_templates()
            return
        elapsed = (datetime.utcnow() - self._cache_loaded_at).seconds
        if elapsed > self.CACHE_TTL_SECONDS:
            self._load_templates()

    def get_template(self, intent: str) -> ResponseTemplate:
        """Get response template for a given intent."""
        self._maybe_refresh_cache()
        template = self._cache.get(intent) or self._cache.get("GENERAL_QUERY")
        if not template:
            # Ultimate fallback
            return ResponseTemplate(
                intent=intent,
                template="I can help you with that. {rag.response}",
            )
        return template

    def fill_template(
        self,
        template: ResponseTemplate,
        rag_facts: dict,
        fallback: str = "information not available",
    ) -> str:
        """
        Fill template placeholders with RAG-retrieved facts.
        {rag.balance} → looks up rag_facts["balance"]
        Missing keys get a natural fallback phrase.
        """
        text = template.template

        def replace_placeholder(match):
            key = match.group(1)  # e.g. "balance" from {rag.balance}
            value = rag_facts.get(key)
            if value is None:
                return fallback
            return str(value)

        filled = re.sub(r"\{rag\.(\w+)\}", replace_placeholder, text)
        return filled

    def resolve_sub_route(
        self,
        template: ResponseTemplate,
        rag_facts: dict,
    ) -> Optional[SubRoute]:
        """
        Evaluate sub-route conditions against RAG facts.
        Returns the first matching sub-route, or None.
        Conditions are simple expressions evaluated safely.
        """
        for sub_route in template.sub_routes:
            try:
                # Build a safe eval context from rag_facts
                # Supports: rag.key > value, rag.key == 'string', etc.
                condition = sub_route.condition
                # Replace rag.xxx with rag_facts["xxx"]
                for key, value in rag_facts.items():
                    str_val = f'"{value}"' if isinstance(value, str) else str(value)
                    condition = condition.replace(f"rag.{key}", str_val)
                # Evaluate — only allow comparison operators
                if re.match(r'^[\d\s<>=!."\'+-]+$', condition):
                    if eval(condition):  # noqa: S307
                        logger.info("sub_route_triggered",
                                    route=sub_route.route_id,
                                    label=sub_route.label)
                        return sub_route
            except Exception:
                pass  # Condition evaluation failed — skip this sub-route
        return None

    def get_doc_sources(self, intent: str) -> list[dict]:
        """Return document sources to fetch for a given intent."""
        template = self.get_template(intent)
        return template.doc_sources

    def save_template(self, template: ResponseTemplate):
        """Save/update a template in Cosmos DB and refresh cache."""
        if not self._use_cosmos:
            self._cache[template.intent] = template
            return

        try:
            _, templates_container = get_cosmos_containers()
            import dataclasses, json
            item = dataclasses.asdict(template)
            item["id"] = template.intent  # Cosmos DB partition key
            item["updated_at"] = datetime.utcnow().isoformat()
            templates_container.upsert_item(item)
            self._cache[template.intent] = template
            logger.info("template_saved", intent=template.intent)
        except Exception as e:
            logger.error("template_save_failed", error=str(e))
            raise


_portal: Optional[ResponsePortal] = None


def get_response_portal() -> ResponsePortal:
    global _portal
    if _portal is None:
        _portal = ResponsePortal()
    return _portal
