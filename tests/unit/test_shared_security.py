from __future__ import annotations

import re

from asf.agents._shared.security import scan_secrets
from tests.unit._fake_secrets import fake_secret


def test_scan_secrets_aws_access_key() -> None:
    content = fake_secret("aws_access")
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 1
    assert matches[0].pattern_name == "aws_access_key_id"
    assert matches[0].file_path == "config.py"
    assert matches[0].line_number == 1
    assert fake_secret("aws_access") in matches[0].matched_text


def test_scan_secrets_aws_access_key_non_hit() -> None:
    # Too short
    content = "AKIA123"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0
    # Wrong prefix
    content = "BKIAIOSFODNN7EXAMPLE"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0


def test_scan_secrets_aws_secret_key() -> None:
    content = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 1
    assert matches[0].pattern_name == "aws_secret_access_key"


def test_scan_secrets_aws_secret_key_non_hit() -> None:
    # Too short (39 chars)
    content = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLKE"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0
    # Contains invalid character
    content = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKE!"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0


def test_scan_secrets_github_token() -> None:
    # ghp_ + 36 alphanumeric chars
    content = fake_secret("github")
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 1
    assert matches[0].pattern_name == "github_token"


def test_scan_secrets_github_token_non_hit() -> None:
    # ghp_ but too short (35 chars instead of 36)
    content = fake_secret("github")[:-1]
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0
    # wrong prefix (gho_)
    content = "gho_abcdefghijklmnopqrstuvwxyz1234567890"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0
    # ghp_ but with invalid character
    content = fake_secret("github")[:-1] + "!"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0


def test_scan_secrets_gitlab_token() -> None:
    # glpat- + 20+ alphanumeric chars
    content = "glpat-abcdefghijklmnopqrst"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 1
    assert matches[0].pattern_name == "gitlab_token"


def test_scan_secrets_gitlab_token_non_hit() -> None:
    # Too short
    content = "glpat-abcdefghijklmnopq"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0
    # Wrong prefix
    content = "glpt-abcdefghijklmnopqrst"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0


def test_scan_secrets_slack_token() -> None:
    # xoxb- (bot token)
    #content = "xoxb-123456789012-abcdefghijklmnop"
    FAKE_SLACK_TOKEN = "xoxb-FAKE-TEST-TOKEN-NOT-REAL"
    matches = scan_secrets(FAKE_SLACK_TOKEN, "config.py")
    assert len(matches) == 1
    assert matches[0].pattern_name == "slack_token"
    # xoxp- (user token)
    content = "xoxp-123456789012-abcdefghijklmnop"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 1
    assert matches[0].pattern_name == "slack_token"
    # xoxr- (refresh token)
    content = "xoxr-123456789012-abcdefghijklmnop"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 1
    assert matches[0].pattern_name == "slack_token"


def test_scan_secrets_slack_token_non_hit() -> None:
    # Too short
    content = "xoxb-123"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0
    # Wrong prefix (xoxz- not in [baprs])
    content = "xoxz-123456789012-abcdefghijklmnop"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0


def test_scan_secrets_stripe_key() -> None:
    # Need 24+ alphanumeric chars after sk_live_ (no underscores)
    FAKE_STRIPE_KEY = fake_secret("stripe_live")
    matches = scan_secrets(FAKE_STRIPE_KEY, "config.py")
    assert len(matches) == 1
    assert matches[0].pattern_name == "stripe_key"


def test_scan_secrets_stripe_key_non_hit() -> None:
    # Too short (23 chars after sk_live_)
    content = fake_secret("stripe_live")[:-1]
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0
    # Test key (sk_test_) should not match
    content = fake_secret("stripe_test")
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0
    # Wrong prefix
    content = "sk_liv_abcdefghijklmnopqrstuvwxyz"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0


def test_scan_secrets_private_key() -> None:
    content = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow..."
    matches = scan_secrets(content, "key.pem")
    assert len(matches) == 1
    assert matches[0].pattern_name == "private_key"
    # Test other key types
    for key_type in ["EC", "DSA", "OPENSSH"]:
        content = f"-----BEGIN {key_type} PRIVATE KEY-----\nkey"
        matches = scan_secrets(content, "key.pem")
        assert len(matches) == 1
        assert matches[0].pattern_name == "private_key"
    # No type
    content = "-----BEGIN PRIVATE KEY-----\nkey"
    matches = scan_secrets(content, "key.pem")
    assert len(matches) == 1
    assert matches[0].pattern_name == "private_key"


def test_scan_secrets_private_key_non_hit() -> None:
    # Public key should not match
    content = "-----BEGIN PUBLIC KEY-----\nkey"
    matches = scan_secrets(content, "key.pem")
    assert len(matches) == 0
    # Certificate should not match
    content = "-----BEGIN CERTIFICATE-----\nkey"
    matches = scan_secrets(content, "key.pem")
    assert len(matches) == 0


def test_scan_secrets_api_key_generic() -> None:
    content = 'api_key = "abcdefghijklmnopqrstuvwxyz123456"'
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 1
    assert matches[0].pattern_name == "api_key_generic"
    # Test various formats
    for fmt in [
        'apikey = "abcdefghijklmnopqrstuvwxyz123456"',
        'api-key = "abcdefghijklmnopqrstuvwxyz123456"',
        'secret = "abcdefghijklmnopqrstuvwxyz123456"',
        'api_key: "abcdefghijklmnopqrstuvwxyz123456"',
    ]:
        matches = scan_secrets(fmt, "config.py")
        assert len(matches) == 1
        assert matches[0].pattern_name == "api_key_generic"


def test_scan_secrets_api_key_generic_non_hit() -> None:
    # Too short
    content = 'api_key = "abcdefghijklmnopqrs"'
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0
    # No key-like prefix
    content = 'my_value = "abcdefghijklmnopqrstuvwxyz123456"'
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0


def test_scan_secrets_database_url() -> None:
    content = "postgres://user:password@localhost/db"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 1
    assert matches[0].pattern_name == "database_url"
    # mysql
    content = "mysql://user:password@localhost/db"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 1
    assert matches[0].pattern_name == "database_url"
    # mongodb
    content = "mongodb://user:password@localhost/db"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 1
    assert matches[0].pattern_name == "database_url"


def test_scan_secrets_database_url_non_hit() -> None:
    # No password
    content = "postgres://user@localhost/db"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0
    # Wrong protocol
    content = "http://user:password@localhost/db"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0


def test_scan_secrets_bearer_token() -> None:
    content = "bearer abcdefghijklmnopqrstuvwxyz123456"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 1
    assert matches[0].pattern_name == "bearer_token"
    # Case insensitive
    content = "BEARER abcdefghijklmnopqrstuvwxyz123456"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 1
    assert matches[0].pattern_name == "bearer_token"


def test_scan_secrets_bearer_token_non_hit() -> None:
    # Too short
    content = "bearer abcdefghijklmnopqrs"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0
    # Wrong keyword
    content = "token abcdefghijklmnopqrstuvwxyz123456"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 0


def test_scan_secrets_jwt_token() -> None:
    content = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    matches = scan_secrets(content, "token.txt")
    # JWT may also trigger aws_secret_access_key false positive
    jwt_matches = [m for m in matches if m.pattern_name == "jwt_token"]
    assert len(jwt_matches) == 1


def test_scan_secrets_jwt_token_non_hit() -> None:
    # Not enough parts
    content = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIQ"
    matches = scan_secrets(content, "token.txt")
    jwt_matches = [m for m in matches if m.pattern_name == "jwt_token"]
    assert len(jwt_matches) == 0
    # Invalid base64url characters
    content = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIQ.!@#"
    matches = scan_secrets(content, "token.txt")
    jwt_matches = [m for m in matches if m.pattern_name == "jwt_token"]
    assert len(jwt_matches) == 0


def test_scan_secrets_multiple_secrets() -> None:
    content = f"{fake_secret('aws_access')}\n{fake_secret('github')}"
    matches = scan_secrets(content, "config.py")
    assert len(matches) == 2
    assert matches[0].line_number == 1
    assert matches[1].line_number == 2


def test_scan_secrets_exclude_patterns() -> None:
    content = fake_secret("aws_access")
    matches = scan_secrets(content, "config.py", exclude_patterns=[re.compile(r"EXAMPLE")])
    assert len(matches) == 0


def test_scan_secrets_no_secrets() -> None:
    content = "print('hello world')\nfoo = 'bar'"
    matches = scan_secrets(content, "main.py")
    assert len(matches) == 0
