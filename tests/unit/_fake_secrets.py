from __future__ import annotations


def fake_secret(kind: str) -> str:
    if kind == "aws_access":
        return "AK" + "IA" + "IOSFODNN7EXAMPLE"
    if kind == "github":
        return "gh" + "p_" + ("x" * 36)
    if kind == "stripe_live":
        return "sk" + "_live_" + ("x" * 24)
    if kind == "stripe_test":
        return "sk" + "_test_" + ("x" * 24)
    if kind == "aq":
        return "AQ" + "." + ("x" * 24)
    raise ValueError(f"Unknown fake secret kind: {kind}")
