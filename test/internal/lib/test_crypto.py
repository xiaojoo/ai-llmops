from internal.lib.crypto import encrypt_value, decrypt_value, build_master_key


def test_roundtrip():
    key = build_master_key("my-secret")
    enc = encrypt_value("sk-ant-xxx", key)
    assert enc != "sk-ant-xxx"
    assert decrypt_value(enc, key) == "sk-ant-xxx"


def test_decrypt_failure_returns_original():
    key = build_master_key("k1")
    assert decrypt_value("not-base64!!!", key) == "not-base64!!!"
