r"""Manual, one-request Gemini smoke test.

Run manually with:
    $env:ASF_LIVE_GEMINI_API_KEY = "<key>"
    $env:ASF_LIVE_GEMINI_MODEL = "<documented model id>"
    .\.venv\Scripts\python.exe scripts\gemini_smoke.py

The script reads the key only from the environment, sends one tiny request,
persists redacted evidence under ``.asf-evidence/``, and prints only summary
metadata. It never prints the key, headers, request, or response text.
"""

from __future__ import annotations

import os
import sys
import time

from asf.contracts.models import ModelMessage, ModelRequest
from asf.integrations.gemini import EvidenceCapture, GeminiModelGateway, HttpTransport


def build_gateway(
    api_key: str,
    model: str,
    evidence: EvidenceCapture,
    transport: HttpTransport | None = None,
) -> GeminiModelGateway:
    return GeminiModelGateway(
        model=model,
        api_key=api_key,
        evidence=evidence,
        run_id="manual-smoke",
        transport=transport,
    )


def main() -> int:
    api_key = os.environ.get("ASF_LIVE_GEMINI_API_KEY")
    model = os.environ.get("ASF_LIVE_GEMINI_MODEL")
    if not api_key or not model:
        print("Set ASF_LIVE_GEMINI_API_KEY and ASF_LIVE_GEMINI_MODEL.", file=sys.stderr)
        return 2

    evidence = EvidenceCapture(".asf-evidence", secrets=[api_key])
    gateway = build_gateway(api_key, model, evidence)
    started = time.monotonic()
    response = gateway.complete(
        ModelRequest(messages=[ModelMessage(role="user", content="Reply with: OK")])
    )
    duration = time.monotonic() - started
    usage = response.usage
    thinking_tokens = response.metadata.get("thinkingTokens", 0)
    print(f"evidence={evidence.last_path}")
    print(f"model={response.model}")
    print(f"finish_reason={response.finish_reason}")
    print(f"duration_seconds={duration:.3f}")
    print(
        f"prompt_tokens={usage.prompt_tokens} completion_tokens={usage.completion_tokens} "
        f"thinking_tokens={thinking_tokens}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
