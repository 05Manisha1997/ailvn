"""
services/verification_service.py

Phase 2 — Identity Verification

After phone number is validated, we verify caller identity via:
1. KBA (Knowledge-Based Authentication) — DOB, last 4 SSN, etc.
2. Voice biometrics (Azure Speaker Recognition — optional)
3. OTP via SMS (Azure Communication Services or Twilio)

In production: hook into your CRM/identity DB in verify_identity().
"""
import uuid
import random
import string
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum

from config.settings import get_settings
from utils.logger import logger

settings = get_settings()


class VerificationStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    OTP_SENT = "otp_sent"
    LOCKED = "locked"


@dataclass
class VerificationSession:
    session_id: str
    caller_phone: str
    status: VerificationStatus = VerificationStatus.PENDING
    caller_name: Optional[str] = None
    caller_id: Optional[str] = None           # Internal customer ID
    otp_code: Optional[str] = None
    otp_expires_at: Optional[datetime] = None
    attempts: int = 0
    max_attempts: int = 3
    verified_at: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class VerificationResult:
    success: bool
    session: VerificationSession
    message: str
    next_step: Optional[str] = None   # "ask_name" | "ask_dob" | "send_otp" | "proceed"


class VerificationService:
    """
    Handles multi-step identity verification flow.
    Integrates with Azure Communication Services for OTP SMS.
    """

    MAX_ATTEMPTS = 3
    OTP_EXPIRY_MINUTES = 5

    def start_session(self, caller_phone: str) -> VerificationSession:
        """Start a new verification session for a caller."""
        session = VerificationSession(
            session_id=str(uuid.uuid4()),
            caller_phone=caller_phone,
        )
        logger.info("verification_session_started",
                    session_id=session.session_id,
                    phone=caller_phone)
        return session

    def verify_identity(
        self,
        session: VerificationSession,
        spoken_text: str,
        step: str,  # "name" | "dob" | "last4" | "otp"
    ) -> VerificationResult:
        """
        Verify one step of identity verification.
        In production: replace mock DB lookups with real CRM queries.
        """
        if session.status == VerificationStatus.LOCKED:
            return VerificationResult(
                success=False,
                session=session,
                message="Your account is locked due to too many failed attempts. Please call back.",
            )

        session.attempts += 1
        if session.attempts > self.MAX_ATTEMPTS:
            session.status = VerificationStatus.LOCKED
            return VerificationResult(
                success=False,
                session=session,
                message="Too many failed attempts. Your session has been locked.",
            )

        # ── Mock identity DB lookup ─────────────────────────────────
        # In production: query your CRM/database with session.caller_phone
        mock_customer = self._lookup_customer_by_phone(session.caller_phone)

        if step == "name":
            # Fuzzy name match (normalize whitespace, lowercase)
            spoken_normalized = " ".join(spoken_text.lower().split())
            expected_normalized = mock_customer["name"].lower()
            match = (
                spoken_normalized in expected_normalized
                or expected_normalized in spoken_normalized
            )
            if match:
                session.caller_name = mock_customer["name"]
                session.caller_id = mock_customer["id"]
                return VerificationResult(
                    success=True,
                    session=session,
                    message=f"Thank you, {mock_customer['name']}.",
                    next_step="ask_dob",
                )

        elif step == "dob":
            # Accept formats: "January 15 1985", "01/15/1985", "15th January 1985"
            spoken_clean = spoken_text.replace("/", " ").replace("-", " ").lower()
            expected_clean = mock_customer["dob"].replace("/", " ").replace("-", " ").lower()
            if spoken_clean == expected_clean or mock_customer["dob"] in spoken_text:
                session.status = VerificationStatus.PASSED
                session.verified_at = datetime.utcnow()
                return VerificationResult(
                    success=True,
                    session=session,
                    message="Identity verified successfully.",
                    next_step="proceed",
                )

        elif step == "otp":
            if (
                session.otp_code
                and session.otp_expires_at
                and datetime.utcnow() < session.otp_expires_at
                and spoken_text.strip() == session.otp_code
            ):
                session.status = VerificationStatus.PASSED
                session.verified_at = datetime.utcnow()
                return VerificationResult(
                    success=True,
                    session=session,
                    message="OTP verified successfully.",
                    next_step="proceed",
                )
            return VerificationResult(
                success=False,
                session=session,
                message="The OTP is incorrect or has expired.",
                next_step="retry_otp",
            )

        return VerificationResult(
            success=False,
            session=session,
            message=f"I could not verify that information. You have "
                    f"{self.MAX_ATTEMPTS - session.attempts} attempts remaining.",
            next_step=step,
        )

    def send_otp(self, session: VerificationSession) -> VerificationResult:
        """
        Generate OTP and send via SMS using Azure Communication Services.
        Free tier: 100 SMS/day.
        """
        otp = "".join(random.choices(string.digits, k=6))
        session.otp_code = otp
        session.otp_expires_at = datetime.utcnow() + timedelta(
            minutes=self.OTP_EXPIRY_MINUTES
        )
        session.status = VerificationStatus.OTP_SENT

        try:
            self._send_sms(
                to_number=session.caller_phone,
                message=f"Your Voice Navigator verification code is {otp}. "
                        f"Valid for {self.OTP_EXPIRY_MINUTES} minutes.",
                otp_code=otp,
            )
            logger.info("otp_sent", session_id=session.session_id)
            return VerificationResult(
                success=True,
                session=session,
                message=f"I've sent a 6-digit code to your phone ending in "
                        f"{session.caller_phone[-4:]}. Please say the code.",
                next_step="verify_otp",
            )
        except Exception as e:
            logger.error("otp_send_failed", error=str(e))
            return VerificationResult(
                success=False,
                session=session,
                message="I could not send the verification code. Please try again.",
            )

    def _send_sms(self, to_number: str, message: str, otp_code: Optional[str] = None):
        """Send SMS via Azure Communication Services."""
        try:
            from azure.communication.sms import SmsClient
            client = SmsClient.from_connection_string(
                settings.azure_comm_connection_string
            )
            client.send(
                from_="+18005551234",  # Your Azure Comm Services number
                to=[to_number],
                message=message,
            )
        except Exception as e:
            # Fallback: log the OTP for dev/testing
            if settings.app_env == "development":
                logger.debug("sms_send_failed_dev_fallback", error=str(e), to=to_number, otp=otp_code)
            else:
                raise

    def _lookup_customer_by_phone(self, phone: str) -> dict:
        """
        MOCK: Replace with actual CRM/database lookup.
        In production: query Azure Cosmos DB, SQL, or your CRM API.
        """
        # Simulated customer database
        mock_db = {
            "+14155552671": {"id": "CUST-001", "name": "John Smith", "dob": "01/15/1985"},
            "+14155552672": {"id": "CUST-002", "name": "Jane Doe", "dob": "06/22/1990"},
        }
        return mock_db.get(phone, {"id": "CUST-UNKNOWN", "name": "Customer", "dob": ""})


def get_verification_service() -> VerificationService:
    return VerificationService()
