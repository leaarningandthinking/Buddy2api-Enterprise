import fingerprint


def test_origin_for_intl_and_domestic_hosts():
    assert fingerprint.origin_for("www.workbuddy.ai") == "https://www.workbuddy.ai"
    assert fingerprint.origin_for("workbuddy.ai") == "https://www.workbuddy.ai"
    assert fingerprint.origin_for("www.codebuddy.cn") == "https://www.codebuddy.cn"
    assert fingerprint.origin_for("www.workbuddy.cn") == "https://www.codebuddy.cn"
    assert fingerprint.origin_for("") == "https://www.codebuddy.cn"


def test_chat_headers_include_cli_fingerprint_not_cosy_or_refresh():
    headers = fingerprint.chat_headers(
        {
            "access_token": "tok",
            "uid": "user-1",
            "domain": "www.codebuddy.cn",
            "enterprise_id": "ent-1",
        }
    )
    assert headers["X-IDE-Type"] == "CLI"
    assert headers["Authorization"] == "Bearer tok"
    assert "X-Refresh-Token" not in headers
    assert "Cosy-Key" not in headers
    assert "cosy-key" not in {k.lower() for k in headers}


def test_refresh_headers_include_refresh_token():
    headers = fingerprint.refresh_headers(
        {
            "access_token": "tok",
            "refresh_token": "ref",
            "uid": "user-1",
            "domain": "www.codebuddy.cn",
        }
    )
    assert headers["X-Refresh-Token"] == "ref"
    assert headers["Authorization"] == "Bearer tok"
