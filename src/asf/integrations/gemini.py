from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from http.client import HTTPMessage
from pathlib import Path
from typing import IO, Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from asf.contracts.models import ModelMessage, ModelRequest, ModelResponse, ModelUsage
from asf.integrations.retry import (
    backoff_delay,
    effective_timeout,
    http_error_code,
    is_context_too_long,
    parse_retry_after,
)
from asf.models.errors import ALLOWED_GATEWAY_ERROR_CODES, ModelGatewayError

GEMINI_API_HOST = "generativelanguage.googleapis.com"
GEMINI_API_BASE = f"https://{GEMINI_API_HOST}/v1beta"
DEFAULT_MAX_REQUEST_BYTES = 1_000_000
DEFAULT_MAX_RESPONSE_BYTES = 4_000_000
DEFAULT_MAX_REQUESTS_PER_RUN = 12
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_RETRIES = 2
_SECRET_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|authorization|bearer|password|secret|token)"
    r"[\s\"':=]+[A-Za-z0-9._~+/=-]{8,}|AQ\.[A-Za-z0-9._~+/=-]{8,}"
)
_MODEL_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]+")


class HttpTransport(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> tuple[int, Mapping[str, str], bytes]:
        """Returns (status, headers, body); header names lowercased."""
        ...


class UrlLibTransport:
    """Small urllib transport with redirects disabled."""

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> tuple[int, Mapping[str, str], bytes]:
        request = Request(url, data=body, headers=dict(headers), method="POST")
        opener = build_opener(_NoRedirectHandler)
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                payload = response.read(max_response_bytes + 1)
                if len(payload) > max_response_bytes:
                    raise _ResponseTooLargeError
                return response.status, _lower_headers(response.headers), payload
        except HTTPError as exc:
            payload = exc.read(max_response_bytes + 1)
            if len(payload) > max_response_bytes:
                raise _ResponseTooLargeError from None
            return exc.code, _lower_headers(exc.headers), payload


def _lower_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    return {str(key).lower(): str(value) for key, value in headers.items()}


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        response: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        return None


class _ResponseTooLargeError(Exception):
    pass


@dataclass(frozen=True)
class EvidenceRecord:
    run_id: str
    agent_id: str
    request: Any
    response: Any
    usage: Mapping[str, Any] | None
    duration_ms: int
    status: str
    retry_count: int


class EvidenceCapture:
    """Writes redacted JSONL records under ``directory/run_id.jsonl``."""

    def __init__(
        self,
        directory: str | Path,
        *,
        secrets: Sequence[str] = (),
    ) -> None:
        self._directory = Path(directory)
        self._secrets = tuple(secret for secret in secrets if secret)
        self._last_path: Path | None = None

    def record(self, record: EvidenceRecord) -> Path:
        redacted_request = _redact(record.request, self._secrets)
        redacted_response = _redact(record.response, self._secrets)
        request_json = _canonical_json(redacted_request)
        response_json = _canonical_json(redacted_response)
        payload = {
            "runId": record.run_id,
            "agentId": record.agent_id,
            "requestHash": _sha256(request_json),
            "responseHash": _sha256(response_json),
            "request": redacted_request,
            "response": redacted_response,
            "usage": _redact(record.usage, self._secrets),
            "durationMs": record.duration_ms,
            "status": record.status,
            "retryCount": record.retry_count,
        }
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._directory / f"{_safe_run_id(record.run_id)}.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True, ensure_ascii=True) + "\n")
        self._last_path = path
        return path

    @property
    def last_path(self) -> Path | None:
        return self._last_path


class RequestBudget:
    """Thread-safe request budget shared by gateways in one chain run."""

    def __init__(self, limit: int = DEFAULT_MAX_REQUESTS_PER_RUN) -> None:
        if limit < 1:
            raise ValueError("Request budget limit must be positive")
        self._limit = limit
        self._used = 0
        self._lock = threading.Lock()

    def consume(self) -> bool:
        with self._lock:
            if self._used >= self._limit:
                return False
            self._used += 1
            return True

    @property
    def limit(self) -> int:
        return self._limit


class GeminiModelGateway:
    """Synchronous Gemini generateContent adapter for the ModelGateway port.

    The model is supplied by configuration; no model ID is selected by this
    adapter. The API key is resolved from the configured environment variable.
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        endpoint: str = GEMINI_API_BASE,
        transport: HttpTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[float, float], float] = random.uniform,
        max_requests_per_run: int = DEFAULT_MAX_REQUESTS_PER_RUN,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        evidence: EvidenceCapture | None = None,
        run_id: str = "live-run",
        request_budget: RequestBudget | None = None,
    ) -> None:
        normalized_model = model.strip()
        if normalized_model.startswith("models/"):
            normalized_model = normalized_model[7:]
        if not normalized_model or _MODEL_ID_PATTERN.fullmatch(normalized_model) is None:
            raise ValueError(
                "Gemini model must be a non-empty ID containing only letters, numbers, "
                "'.', '_' or '-'"
            )
        if not api_key:
            raise ValueError("Gemini API key must not be empty")
        _validate_endpoint(endpoint)
        if max_requests_per_run < 1 or timeout_seconds <= 0 or max_retries < 0:
            raise ValueError("Gemini request limits must be positive and retries non-negative")
        self._model = normalized_model
        self._api_key = api_key
        self._endpoint = endpoint.rstrip("/")
        self._transport = transport or UrlLibTransport()
        self._sleep = sleep
        self._rand = rand
        self._request_budget = request_budget or RequestBudget(max_requests_per_run)
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes
        self._evidence = evidence
        self._run_id = run_id

    @classmethod
    def from_environment(
        cls,
        *,
        model: str,
        endpoint: str = GEMINI_API_BASE,
        api_key_env: str = "ASF_LIVE_GEMINI_API_KEY",
        **kwargs: Any,
    ) -> GeminiModelGateway:
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ValueError(f"Gemini API key environment variable '{api_key_env}' is not set")
        return cls(model=model, api_key=api_key, endpoint=endpoint, **kwargs)

    def complete(self, request: ModelRequest) -> ModelResponse:
        payload = self._build_payload(request.messages)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > self._max_request_bytes:
            raise ModelGatewayError(
                "LLM_INVALID_RESPONSE",
                "Gemini request exceeds the configured size limit",
                details={"limitBytes": self._max_request_bytes},
            )
        url = f"{self._endpoint}/models/{self._model}:generateContent"
        retry_count = 0
        started = time.monotonic()
        try:
            while True:
                if not self._request_budget.consume():
                    raise ModelGatewayError(
                        "INTEGRATION_UNAVAILABLE",
                        "Gemini request budget exhausted",
                        details={"limit": self._request_budget.limit},
                    )
                try:
                    status, headers, raw = self._transport.post(
                        url,
                        headers={
                            "Content-Type": "application/json",
                            "x-goog-api-key": self._api_key,
                        },
                        body=body,
                        timeout_seconds=effective_timeout(self._timeout, request),
                        max_response_bytes=self._max_response_bytes,
                    )
                except _ResponseTooLargeError:
                    raise ModelGatewayError(
                        "LLM_INVALID_RESPONSE",
                        "Gemini response exceeds the configured size limit",
                        details={"limitBytes": self._max_response_bytes},
                    ) from None
                except TimeoutError:
                    if retry_count < self._max_retries:
                        self._sleep(
                            backoff_delay(
                                retry_count,
                                retry_after=None,
                                rand=self._rand,
                            )
                        )
                        retry_count += 1
                        continue
                    raise ModelGatewayError(
                        "LLM_TIMEOUT",
                        "Gemini request timed out",
                    ) from None
                except (URLError, OSError) as error:
                    timed_out = isinstance(
                        getattr(error, "reason", None),
                        TimeoutError,
                    )
                    if retry_count < self._max_retries:
                        self._sleep(
                            backoff_delay(
                                retry_count,
                                retry_after=None,
                                rand=self._rand,
                            )
                        )
                        retry_count += 1
                        continue
                    if timed_out:
                        raise ModelGatewayError(
                            "LLM_TIMEOUT",
                            "Gemini request timed out",
                        ) from None
                    raise ModelGatewayError(
                        "INTEGRATION_UNAVAILABLE",
                        "Gemini transport failed",
                    ) from None

                if status >= 300:
                    details = _error_details(raw, url, self._api_key)
                    if status < 400:
                        error_code = "LLM_INVALID_RESPONSE"
                        retryable = False
                    else:
                        error_code = http_error_code(
                            status,
                            context_too_long=is_context_too_long(
                                details["providerStatus"],
                                details["providerMessage"],
                            ),
                        )
                        retryable = ALLOWED_GATEWAY_ERROR_CODES[error_code][1]
                    if retryable and retry_count < self._max_retries:
                        self._sleep(
                            backoff_delay(
                                retry_count,
                                retry_after=parse_retry_after(headers),
                                rand=self._rand,
                            )
                        )
                        retry_count += 1
                        continue
                    raise ModelGatewayError(
                        error_code,
                        _http_error_message(status, details),
                        details={**details, "httpStatus": status},
                    )
                if len(raw) > self._max_response_bytes:
                    raise ModelGatewayError(
                        "LLM_INVALID_RESPONSE",
                        "Gemini response exceeds the configured size limit",
                        details={"limitBytes": self._max_response_bytes},
                    )
                response = self._parse_response(raw)
                self._capture(
                    request,
                    payload,
                    {
                        "content": response.content,
                        "model": response.model,
                        "finishReason": response.finish_reason,
                    },
                    started,
                    "success",
                    retry_count,
                    response.usage.to_contract(),
                )
                return response
        except ModelGatewayError as error:
            self._capture(
                request, payload, {"errorCode": error.code}, started, "error", retry_count
            )
            raise
        except Exception:
            self._capture(
                request, payload, {"errorCode": "INTERNAL"}, started, "error", retry_count
            )
            raise ModelGatewayError("INTEGRATION_UNAVAILABLE", "Gemini request failed") from None

    @staticmethod
    def _build_payload(messages: Sequence[ModelMessage]) -> dict[str, Any]:
        system_parts: list[dict[str, str]] = []
        contents: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                system_parts.append({"text": message.content})
            else:
                contents.append(
                    {
                        "role": "model" if message.role == "assistant" else "user",
                        "parts": [{"text": message.content}],
                    }
                )
        payload: dict[str, Any] = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        return payload

    @staticmethod
    def _parse_response(raw: bytes) -> ModelResponse:
        try:
            data = json.loads(raw.decode("utf-8"))
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            usage_data = data.get("usageMetadata", {})
            model = data.get("modelVersion", "gemini")
            usage = ModelUsage(
                prompt_tokens=int(usage_data.get("promptTokenCount", 0)),
                completion_tokens=int(usage_data.get("candidatesTokenCount", 0)),
            )
            metadata: dict[str, Any] = {"provider": "google-gemini"}
            thinking_tokens = usage_data.get("thoughtsTokenCount")
            if isinstance(thinking_tokens, int):
                metadata["thinkingTokens"] = thinking_tokens
            return ModelResponse(
                content=text,
                model=model,
                usage=usage,
                finish_reason=data["candidates"][0].get("finishReason", "STOP"),
                metadata=metadata,
            )
        except (
            UnicodeDecodeError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            raise ModelGatewayError(
                "LLM_INVALID_RESPONSE",
                "Gemini returned an invalid response payload",
            ) from None

    def _capture(
        self,
        request: ModelRequest,
        payload: Mapping[str, Any],
        response: Mapping[str, Any],
        started: float,
        status: str,
        retry_count: int,
        usage: Mapping[str, Any] | None = None,
    ) -> None:
        if self._evidence is None:
            return
        self._evidence.record(
            EvidenceRecord(
                run_id=self._run_id,
                agent_id=request.metadata.get("agentId", "unknown"),
                request={"model": self._model, "messages": payload},
                response=response,
                usage=usage,
                duration_ms=int((time.monotonic() - started) * 1000),
                status=status,
                retry_count=retry_count,
            )
        )


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.hostname != GEMINI_API_HOST
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Gemini endpoint must use HTTPS on the approved Google API host")


def _error_details(raw: bytes, url: str, api_key: str) -> dict[str, str]:
    status = "HTTP_ERROR"
    message = "No provider error message"
    try:
        payload = json.loads(raw.decode("utf-8"))
        error = payload.get("error", {})
        if isinstance(error, Mapping):
            status_value = error.get("status")
            message_value = error.get("message")
            if isinstance(status_value, str) and status_value:
                status = status_value
            if isinstance(message_value, str) and message_value:
                message = message_value
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, AttributeError):
        return {
            "providerStatus": status,
            "providerMessage": message,
            "requestPath": urlsplit(url).path,
        }
    redacted = str(_redact(message, (api_key,)))
    return {
        "providerStatus": status,
        "providerMessage": redacted[:240],
        "requestPath": urlsplit(url).path,
    }


def _http_error_message(status: int, details: Mapping[str, str]) -> str:
    if status in {401, 403}:
        category = "Gemini authentication or permission error"
    elif status == 404:
        category = "Gemini model or endpoint not found"
    elif 400 <= status < 500:
        category = "Gemini request rejected"
    else:
        category = "Gemini provider error"
    return (
        f"{category} (HTTP {status}, {details['providerStatus']}): "
        f"{details['providerMessage']} [{details['requestPath']}]"
    )


def _redact(value: Any, secrets: Sequence[str]) -> Any:
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            redacted = redacted.replace(secret, "[REDACTED]")
        return _SECRET_PATTERN.sub("[REDACTED]", redacted)
    if isinstance(value, Mapping):
        return {str(key): _redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_run_id(run_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", run_id)[:96] or "run"
