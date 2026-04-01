"""
services/phone_validator.py

Phase 1 — Phone Number Detection & Validation

Steps:
1. Extract phone number from caller ID string or speech text
2. Normalize to E.164 format using libphonenumber (free, offline)
"""
import re
import phonenumbers
from phonenumbers import NumberParseException
from typing import Optional
from dataclasses import dataclass

from config.settings import get_settings
from utils.logger import logger

settings = get_settings()


@dataclass
class PhoneValidationResult:
    raw_input: str
    is_valid: bool
    e164: Optional[str] = None           # e.g. "+14155552671"
    national_format: Optional[str] = None # e.g. "(415) 555-2671"
    country_code: Optional[str] = None   # e.g. "US"
    carrier: Optional[str] = None        # Reserved for future enrichment
    line_type: Optional[str] = None      # Reserved for future enrichment
    error: Optional[str] = None


class PhoneValidatorService:
    """
    Validates phone numbers offline using libphonenumber only.
    No external telephony providers (Twilio, etc.) are required.
    """

    def extract_from_text(self, text: str) -> Optional[str]:
        """
        Extract a phone number from spoken text or a caller ID string.
        Handles formats like: '415 555 2671', 'one four one five...',
        '+1-415-555-2671', '(415) 555-2671'
        """
        # Strip common spoken words
        spoken_digits = {
            "zero": "0", "one": "1", "two": "2", "three": "3",
            "four": "4", "five": "5", "six": "6", "seven": "7",
            "eight": "8", "nine": "9",
        }
        normalized = text.lower()
        for word, digit in spoken_digits.items():
            normalized = normalized.replace(word, digit)

        # Try to find a numeric sequence that looks like a phone number
        patterns = [
            r"\+?1?[\s\-\.]?\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]?\d{4}",  # US format
            r"\+?\d{1,3}[\s\-\.]?\d{3,5}[\s\-\.]?\d{3,5}[\s\-\.]?\d{3,5}",  # International
            r"\d{10,15}",  # Raw digit string
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                return match.group(0).strip()
        return None

    def validate(
        self,
        raw_number: str,
        default_region: str = "US"
    ) -> PhoneValidationResult:
        """
        Validates a phone number string.
        Returns a PhoneValidationResult with normalized formats.
        """
        log = logger.bind(raw_number=raw_number)

        # Try to extract if it's embedded in text
        extracted = self.extract_from_text(raw_number) or raw_number

        try:
            parsed = phonenumbers.parse(extracted, default_region)
        except NumberParseException as e:
            log.warning("phone_parse_failed", error=str(e))
            return PhoneValidationResult(
                raw_input=raw_number,
                is_valid=False,
                error=f"Could not parse number: {e}",
            )

        if not phonenumbers.is_valid_number(parsed):
            return PhoneValidationResult(
                raw_input=raw_number,
                is_valid=False,
                error="Number is structurally invalid",
            )

        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        national = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
        region = phonenumbers.region_code_for_number(parsed)

        result = PhoneValidationResult(
            raw_input=raw_number,
            is_valid=True,
            e164=e164,
            national_format=national,
            country_code=region,
        )

        log.info("phone_validated", e164=e164, country=region)
        return result

    def is_blocked_number(self, e164: str, blocklist: list[str] = None) -> bool:
        """Check if a number is on a blocklist (extend as needed)."""
        if blocklist is None:
            blocklist = []
        return e164 in blocklist


# Module-level singleton
_validator = None


def get_phone_validator() -> PhoneValidatorService:
    global _validator
    if _validator is None:
        _validator = PhoneValidatorService()
    return _validator
