"""Request settings and failure handling for the BeaconWorks analyst scripts.

The rules this file follows:
  1. Every call has a timeout. The SDK default is 10 minutes, far too long for us.
  2. Retry only failures that can pass on a second try, and retry in one place:
     the SDK already retries timeouts, connection errors, 408, 409, 429 and 5xx
     with exponential backoff and jitter. We do not add a second retry loop.
  3. Never retry a request that is wrong (400, 404, 422) or not allowed
     (401, 403, quota or spend limit). It will fail the same way again.
  4. Log the request ID so a failure can be traced. Never log the key.

Try a setting without editing code:
  BW_TIMEOUT=30       seconds allowed for one attempt
  BW_MAX_RETRIES=2    extra attempts the SDK makes for a failure worth retrying
  OPENAI_LOG=info     makes the SDK print a line for every retry
"""
import os
from dataclasses import dataclass
from typing import Optional

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

TIMEOUT_SECONDS = float(os.environ.get("BW_TIMEOUT", "30"))
MAX_RETRIES = int(os.environ.get("BW_MAX_RETRIES", "2"))

# A 429 can mean "slow down" (worth retrying) or "out of quota" (never worth it).
# These codes come from OpenAI's error codes guide.
QUOTA_CODES = {
    "insufficient_quota",
    "credit_balance_exhausted",
    "organization_spend_limit_exceeded",
    "project_spend_limit_exceeded",
    "organization_usage_limit_exceeded",
}


def make_client() -> OpenAI:
    return OpenAI(timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES)


@dataclass
class Failure:
    kind: str  # "transient", "fix_request", "stop_all" or "output"
    reason: str
    status: Optional[int] = None
    code: Optional[str] = None
    request_id: Optional[str] = None

    def line(self) -> str:
        parts = [self.kind, self.reason]
        if self.status is not None:
            parts.append(f"status {self.status}")
        if self.code:
            parts.append(f"code {self.code}")
        if self.request_id:
            parts.append(f"request id {self.request_id}")
        return " | ".join(parts)


def classify(error: Exception) -> Failure:
    """Turn any error from a model call into one of four kinds."""
    if isinstance(error, APITimeoutError):
        return Failure("transient", f"timed out ({TIMEOUT_SECONDS:g}s per attempt, {MAX_RETRIES} retries used)")
    if isinstance(error, APIConnectionError):
        return Failure("transient", f"could not connect ({MAX_RETRIES} retries used)")
    if isinstance(error, APIStatusError):
        status, code, request_id = error.status_code, error.code, error.request_id
        if status in (401, 403) or code in QUOTA_CODES:
            # Auth, permission and money problems: every next call fails too.
            return Failure("stop_all", "not allowed, fix the key, project or billing", status, code, request_id)
        if status in (408, 409, 429) or status >= 500:
            return Failure("transient", f"server side, still failing after {MAX_RETRIES} retries", status, code, request_id)
        # 400, 404, 422: our request is wrong. Show the API's message, it says what to fix.
        message = str(error.body.get("message", "")) if isinstance(error.body, dict) else ""
        return Failure("fix_request", message[:160] or "the request is invalid", status, code, request_id)
    # Our own TriageError: the call worked but the answer is unusable
    # (refused, cut off, wrong shape). Retrying the same request is not the fix.
    return Failure("output", str(error))
