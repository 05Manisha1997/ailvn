"""
tests/test_core.py

Unit tests for core Voice Navigator components.
Run with: pytest tests/ -v
"""
import pytest
import json
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime


# ── Phone Validator Tests ─────────────────────────────────────────────────────

class TestPhoneValidator:
    def setup_method(self):
        from services.phone_validator import PhoneValidatorService
        self.validator = PhoneValidatorService()

    def test_valid_us_number(self):
        result = self.validator.validate("+14155552671")
        assert result.is_valid is True
        assert result.e164 == "+14155552671"
        assert result.country_code == "US"

    def test_national_format(self):
        result = self.validator.validate("(415) 555-2671", default_region="US")
        assert result.is_valid is True
        assert result.e164 == "+14155552671"

    def test_invalid_number(self):
        result = self.validator.validate("123")
        assert result.is_valid is False
        assert result.error is not None

    def test_extract_from_spoken_text(self):
        text = "My number is four one five five five five two six seven one"
        extracted = self.validator.extract_from_text(text)
        assert extracted is not None
        assert "415" in extracted or "4155" in extracted

    def test_extract_from_written_text(self):
        extracted = self.validator.extract_from_text("Call me at (415) 555-2671 please")
        assert extracted is not None
        assert "555-2671" in extracted or "415" in extracted

    def test_international_number(self):
        result = self.validator.validate("+447911123456")
        assert result.is_valid is True
        assert result.country_code == "GB"

    def test_blocklist(self):
        blocked = self.validator.is_blocked_number("+14155552671", ["+14155552671"])
        assert blocked is True

    def test_not_blocklisted(self):
        blocked = self.validator.is_blocked_number("+14155552671", ["+19999999999"])
        assert blocked is False


# ── Verification Service Tests ────────────────────────────────────────────────

class TestVerificationService:
    def setup_method(self):
        from services.verification_service import VerificationService
        self.svc = VerificationService()

    def test_start_session(self):
        session = self.svc.start_session("+14155552671")
        assert session.call_id is None or session.session_id is not None
        assert session.caller_phone == "+14155552671"

    def test_verify_name_success(self):
        session = self.svc.start_session("+14155552671")
        result = self.svc.verify_identity(session, "John Smith", "name")
        assert result.success is True
        assert result.next_step == "ask_dob"

    def test_verify_name_failure(self):
        session = self.svc.start_session("+14155552671")
        result = self.svc.verify_identity(session, "Wrong Name", "name")
        assert result.success is False
        assert session.attempts == 1

    def test_verify_dob_success(self):
        session = self.svc.start_session("+14155552671")
        # First pass name check
        self.svc.verify_identity(session, "John Smith", "name")
        result = self.svc.verify_identity(session, "01/15/1985", "dob")
        assert result.success is True
        assert result.next_step == "proceed"

    def test_max_attempts_locks_session(self):
        from services.verification_service import VerificationStatus
        session = self.svc.start_session("+14155552671")
        session.max_attempts = 3
        for _ in range(4):
            self.svc.verify_identity(session, "wrong", "name")
        result = self.svc.verify_identity(session, "wrong", "name")
        assert session.status == VerificationStatus.LOCKED

    def test_otp_verification(self):
        session = self.svc.start_session("+14155552671")
        session.otp_code = "123456"
        session.otp_expires_at = datetime(2099, 1, 1)  # Far future
        result = self.svc.verify_identity(session, "123456", "otp")
        assert result.success is True

    def test_expired_otp_fails(self):
        session = self.svc.start_session("+14155552671")
        session.otp_code = "123456"
        session.otp_expires_at = datetime(2000, 1, 1)  # Past
        result = self.svc.verify_identity(session, "123456", "otp")
        assert result.success is False


# ── Response Portal Tests ─────────────────────────────────────────────────────

class TestResponsePortal:
    def setup_method(self):
        from portal.response_portal import ResponsePortal, DEFAULT_TEMPLATES
        with patch("portal.response_portal.get_cosmos_containers", side_effect=Exception("No DB")):
            self.portal = ResponsePortal()

    def test_get_default_template(self):
        template = self.portal.get_template("ACCOUNT_BALANCE")
        assert template.intent == "ACCOUNT_BALANCE"
        assert "{rag." in template.template

    def test_get_fallback_template_for_unknown_intent(self):
        template = self.portal.get_template("NONEXISTENT_INTENT")
        assert template is not None  # Should fall back to GENERAL_QUERY

    def test_fill_template_success(self):
        template = self.portal.get_template("ACCOUNT_BALANCE")
        facts = {"balance": "$1,234.56", "last_txn": "Amazon $45.99"}
        filled = self.portal.fill_template(template, facts)
        assert "$1,234.56" in filled
        assert "Amazon $45.99" in filled

    def test_fill_template_missing_key_gets_fallback(self):
        template = self.portal.get_template("ACCOUNT_BALANCE")
        facts = {}  # No facts provided
        filled = self.portal.fill_template(template, facts, fallback="N/A")
        assert "N/A" in filled

    def test_sub_route_triggers_on_condition(self):
        template = self.portal.get_template("ACCOUNT_BALANCE")
        # Add a test sub-route with a simple numeric condition
        from portal.response_portal import SubRoute
        template.sub_routes = [
            SubRoute("SR-TEST", "TEST", "rag.amount > 100", "High value detected"),
        ]
        facts = {"amount": 500}
        sub_route = self.portal.resolve_sub_route(template, facts)
        assert sub_route is not None
        assert sub_route.label == "TEST"

    def test_sub_route_no_match(self):
        template = self.portal.get_template("ACCOUNT_BALANCE")
        from portal.response_portal import SubRoute
        template.sub_routes = [
            SubRoute("SR-TEST", "TEST", "rag.amount > 100", "High value"),
        ]
        facts = {"amount": 50}
        sub_route = self.portal.resolve_sub_route(template, facts)
        assert sub_route is None


# ── Session Memory Tests ──────────────────────────────────────────────────────

class TestSessionMemory:
    def setup_method(self):
        """Use a mock Cosmos DB container."""
        self.mock_container = MagicMock()
        self.mock_container.read_item.return_value = None
        self.mock_container.upsert_item.return_value = True

        with patch("memory.session_memory.get_cosmos_client") as mock_cosmos:
            mock_client = MagicMock()
            mock_db = MagicMock()
            mock_cosmos.return_value = mock_client
            mock_client.get_database_client.return_value = mock_db
            mock_db.get_container_client.return_value = self.mock_container
            
            from memory.session_memory import SessionMemory
            self.memory = SessionMemory()

    def test_create_session(self):
        session = self.memory.create_session("+14155552671")
        assert session.call_id is not None
        assert session.caller_phone == "+14155552671"
        assert session.is_verified is False

    def test_save_and_load_session(self):
        session = self.memory.create_session("+14155552671")

        # Mock Cosmos DB to return the session document
        import dataclasses
        session_dict = dataclasses.asdict(session)
        session_dict["conversation"] = [dataclasses.asdict(t) for t in session.conversation]
        session_dict["id"] = session.call_id
        session_dict["ttl"] = 3600
        self.mock_container.read_item.return_value = session_dict

        loaded = self.memory.get_session(session.call_id)
        assert loaded is not None
        assert loaded.call_id == session.call_id
        assert loaded.caller_phone == "+14155552671"

    def test_set_verified(self):
        session = self.memory.create_session("+14155552671")

        import dataclasses
        session_dict = dataclasses.asdict(session)
        session_dict["conversation"] = [dataclasses.asdict(t) for t in session.conversation]
        session_dict["id"] = session.call_id
        session_dict["ttl"] = 3600
        self.mock_container.read_item.return_value = session_dict

        self.memory.set_verified(session.call_id, "John Smith", "CUST-001")
        # Verify upsert_item was called (save happened)
        assert self.mock_container.upsert_item.called

    def test_get_full_context_for_agent(self):
        session = self.memory.create_session("+14155552671")
        session.caller_name = "John Smith"
        session.is_verified = True
        session.intent_history = ["ACCOUNT_BALANCE", "COMPLAINT"]

        import dataclasses
        session_dict = dataclasses.asdict(session)
        session_dict["conversation"] = [dataclasses.asdict(t) for t in session.conversation]
        session_dict["id"] = session.call_id
        session_dict["ttl"] = 3600
        self.mock_container.read_item.return_value = session_dict

        context = self.memory.get_full_context_for_agent(session.call_id)
        assert context["caller"]["name"] == "John Smith"
        assert context["caller"]["verified"] is True
        assert "ACCOUNT_BALANCE" in context["intent_journey"]


# ── Integration Test: Full Turn ───────────────────────────────────────────────

class TestFullTurn:
    """Integration test simulating one complete conversation turn."""

    def test_intent_to_response_pipeline(self):
        """
        Test the full path: user text → intent → RAG → template fill → response
        """
        from portal.response_portal import ResponsePortal

        with patch("portal.response_portal.get_cosmos_containers", side_effect=Exception("No DB")):
            portal = ResponsePortal()

        # 1. Classify intent (mock)
        user_text = "What is my account balance?"
        intent = "ACCOUNT_BALANCE"

        # 2. Get template
        template = portal.get_template(intent)
        assert template is not None

        # 3. Fill template with mock RAG facts
        rag_facts = {
            "balance": "$2,450.00",
            "last_txn": "Starbucks $5.75 on Monday",
        }
        response = portal.fill_template(template, rag_facts)

        # 4. Verify response is filled
        assert "$2,450.00" in response
        assert "Starbucks $5.75" in response
        assert "{rag." not in response  # No unfilled placeholders

        print(f"\n✅ Pipeline test passed: '{response}'")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
