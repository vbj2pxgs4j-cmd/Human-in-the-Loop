"""Deterministic two-stage PII scrubbing pipeline for Indian financial identifiers and sensitive entities."""

import re
from typing import Dict, List, Set, Tuple


class PIIScrubber:
    """Multi-pattern Indian PII scrubber with obfuscation unfolding and false-positive shielding."""

    # Redaction Replacement Tokens
    PAN_REPLACEMENT = "[REDACTED_PAN]"
    PHONE_REPLACEMENT = "[REDACTED_PHONE]"
    AADHAAR_REPLACEMENT = "[REDACTED_AADHAAR]"
    ACCOUNT_REPLACEMENT = "[REDACTED_ACCOUNT]"
    EMAIL_REPLACEMENT = "[REDACTED_EMAIL]"
    NAME_REPLACEMENT = "[REDACTED_NAME]"
    LOCATION_REPLACEMENT = "[REDACTED_LOCATION]"

    # False Positive Shielding Patterns (Currency, Circulars, Scrip Codes, Ticket IDs)
    SHIELD_PATTERNS = [
        # Indian Currency formats (e.g., ₹15,000, Rs. 50,000, Rs 20, INR 1,00,000)
        r"(?:₹|Rs\.?|INR)\s*[\d,]+(?:\.\d+)?",
        # Percentage figures (e.g. 0.05%, 18%, 0.125%)
        r"\b\d+(?:\.\d+)?\s*%",
        # Official circular references (e.g., SEBI/HO/MRD/DC/CIR/P/2026/04, CDSL/OPS/DP/POLCY/2026/112)
        r"\b(?:SEBI|NSE|BSE|MCX|CDSL|NSDL)/[A-Z0-9_\-/]+",
        # Platform Ticket & Order IDs (e.g., TKT-10293, ORD-88201948)
        r"\b(?:TKT|ORD|REF)-[A-Za-z0-9]+\b",
        # BSE Scrip Codes (explicitly marked, e.g., Scrip 500325, BSE Code 500325)
        r"\b(?:scrip|code|bse|nse)\s*[:#]?\s*\d{6}\b",
    ]

    # Stage 1: Indian Financial Identifiers
    # PAN Card: 5 letters + 4 digits + 1 letter (case-insensitive with optional separators: spaces, dots, dashes)
    PAN_PATTERN = re.compile(
        r"\b[A-Za-z](?:[\s\.\-_]*[A-Za-z]){4}[\s\.\-_]*(?:\d[\s\.\-_]*){4}[A-Za-z]\b"
    )

    # Indian Mobile Phone: 10 digits starting with 6, 7, 8, or 9
    # Supports +91, 0 prefix, 5-5 split, 3-3-4 split, dashes, and spaces
    PHONE_PATTERN = re.compile(
        r"\b(?:\+91[\-\s]?|0)?[6-9](?:[\-\s]?\d){9}\b"
    )
    # Spaced mobile number: e.g. 9 8 7 6 5 4 3 2 1 0
    PHONE_SPACED_PATTERN = re.compile(
        r"\b[6-9](?:\s*\d){9}\b"
    )

    # Aadhaar Number: 12 digits, starting with 2-9
    AADHAAR_PATTERN = re.compile(
        r"\b[2-9]\d{3}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}\b|\b[2-9]\d{11}\b"
    )
    AADHAAR_SPACED_PATTERN = re.compile(
        r"\b[2-9](?:\s*\d){11}\b"
    )

    # Email Address
    EMAIL_PATTERN = re.compile(
        r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b"
    )

    # Demat / Client Account IDs:
    DEMAT_NSDL_PATTERN = re.compile(r"\bIN\d{14}\b", re.IGNORECASE)
    DEMAT_CDSL_OR_ACCOUNT_PATTERN = re.compile(r"\b\d{8,16}\b")

    # Stage 2: Entity-Based Masking (Names and Locations)
    # Capitalized names with linguistic prefixes (excluding action verbs)
    NAME_PATTERNS = [
        re.compile(r"(?i:\b(?:my name is|this is|customer\s+name\s*(?:is|[:\-])?|client\s+name\s*(?:is|[:\-])?|user\s+name\s*(?:is|[:\-])?|name\s*[:\-])\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b"),
        re.compile(r"(?i:\bi am\s+)(?!(?:living|residing|from|trying|asking|writing|investing|trading|using)\b)([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b"),
        re.compile(r"(?i:\b(?:mr\.|mrs\.|ms\.|dr\.)\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"),
        re.compile(r"(?i:\b(?:account holder|client name|user)\s*[:\-]?\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"),
    ]

    LOCATION_PATTERNS = [
        re.compile(r"(?i:\b(?:living in|from|residing in|location\s*[:\-])\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"),
        re.compile(r"\b(?:bangalore|bengaluru|mumbai|delhi|new delhi|pune|hyderabad|chennai|kolkata|ahmedabad|gurgaon|noida)\b", re.IGNORECASE),
    ]

    def __init__(self):
        self.compiled_shield_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.SHIELD_PATTERNS
        ]

    def _shield_legitimate_tokens(self, text: str) -> Tuple[str, Dict[str, str]]:
        """Identify and temporarily shield legitimate financial and platform patterns."""
        shields: Dict[str, str] = {}
        shield_counter = 0

        def replace_with_shield(match: re.Match) -> str:
            nonlocal shield_counter
            token = match.group(0)
            placeholder = f"__SHIELDED_TOKEN_{shield_counter}__"
            shields[placeholder] = token
            shield_counter += 1
            return placeholder

        shielded_text = text
        for pattern in self.compiled_shield_patterns:
            shielded_text = pattern.sub(replace_with_shield, shielded_text)

        return shielded_text, shields

    def _restore_shielded_tokens(self, text: str, shields: Dict[str, str]) -> str:
        """Restore previously shielded legitimate financial and platform tokens."""
        restored = text
        for placeholder, original in shields.items():
            restored = restored.replace(placeholder, original)
        return restored

    def scrub(self, text: str) -> str:
        """Execute the two-stage scrubbing pipeline and return sanitized text."""
        if not text or not text.strip():
            return text

        # 1. False-positive shielding pass
        shielded_text, shields = self._shield_legitimate_tokens(text)

        # 2. Stage 1: Financial Identifier Redaction
        # Redact Emails first
        sanitized = self.EMAIL_PATTERN.sub(self.EMAIL_REPLACEMENT, shielded_text)

        # Redact PAN (including spaced / unfolded variants)
        sanitized = self.PAN_PATTERN.sub(self.PAN_REPLACEMENT, sanitized)

        # Redact Phone numbers BEFORE Aadhaar so +91 10-digit numbers aren't treated as 12-digit Aadhaar
        sanitized = self.PHONE_PATTERN.sub(self.PHONE_REPLACEMENT, sanitized)
        sanitized = self.PHONE_SPACED_PATTERN.sub(self.PHONE_REPLACEMENT, sanitized)

        # Redact Aadhaar (12-digit numbers)
        sanitized = self.AADHAAR_PATTERN.sub(self.AADHAAR_REPLACEMENT, sanitized)
        sanitized = self.AADHAAR_SPACED_PATTERN.sub(self.AADHAAR_REPLACEMENT, sanitized)

        # Redact Demat / Account Numbers
        sanitized = self.DEMAT_NSDL_PATTERN.sub(self.ACCOUNT_REPLACEMENT, sanitized)
        sanitized = self.DEMAT_CDSL_OR_ACCOUNT_PATTERN.sub(self.ACCOUNT_REPLACEMENT, sanitized)

        # 3. Stage 2: Entity-Based Masking (Names & Locations)
        for name_pat in self.NAME_PATTERNS:
            def redact_name(match: re.Match) -> str:
                full_match = match.group(0)
                name_group = match.group(1)
                return full_match.replace(name_group, self.NAME_REPLACEMENT)
            sanitized = name_pat.sub(redact_name, sanitized)

        for loc_pat in self.LOCATION_PATTERNS:
            if loc_pat.groups > 0:
                def redact_loc(match: re.Match) -> str:
                    full_match = match.group(0)
                    loc_group = match.group(1)
                    return full_match.replace(loc_group, self.LOCATION_REPLACEMENT)
                sanitized = loc_pat.sub(redact_loc, sanitized)
            else:
                sanitized = loc_pat.sub(self.LOCATION_REPLACEMENT, sanitized)

        # 4. Unshield legitimate tokens
        final_text = self._restore_shielded_tokens(sanitized, shields)
        return final_text

    def contains_pii(self, text: str) -> bool:
        """Detect whether unredacted text contains sensitive PII."""
        scrubbed = self.scrub(text)
        return scrubbed != text

    def get_detected_pii(self, text: str) -> Dict[str, List[str]]:
        """Diagnostic utility returning detected sensitive entities categorized by type."""
        shielded_text, _ = self._shield_legitimate_tokens(text)
        detected: Dict[str, List[str]] = {
            "pan": [m.group(0) for m in self.PAN_PATTERN.finditer(shielded_text)],
            "phone": [m.group(0) for m in self.PHONE_PATTERN.finditer(shielded_text)],
            "aadhaar": [m.group(0) for m in self.AADHAAR_PATTERN.finditer(shielded_text)],
            "email": [m.group(0) for m in self.EMAIL_PATTERN.finditer(shielded_text)],
            "account": [m.group(0) for m in self.DEMAT_CDSL_OR_ACCOUNT_PATTERN.finditer(shielded_text)],
        }
        return {k: v for k, v in detected.items() if v}


# Global scrubber singleton
_default_scrubber: PIIScrubber | None = None


def get_pii_scrubber() -> PIIScrubber:
    """Retrieve global singleton PIIScrubber."""
    global _default_scrubber
    if _default_scrubber is None:
        _default_scrubber = PIIScrubber()
    return _default_scrubber


def scrub_pii(text: str) -> str:
    """Convenience functional interface to scrub PII from input text."""
    return get_pii_scrubber().scrub(text)
