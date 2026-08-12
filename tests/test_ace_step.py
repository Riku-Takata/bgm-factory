from bgm_factory.ace_step import models_from_payload


def test_models_from_documented_payload() -> None:
    payload = {"data": {"models": [{"name": "acestep-v15-turbo"}]}}
    assert models_from_payload(payload) == [{"name": "acestep-v15-turbo"}]


def test_models_from_openai_compatible_payload() -> None:
    payload = {"object": "list", "data": [{"id": "acestep-v15-turbo"}]}
    assert models_from_payload(payload) == [{"id": "acestep-v15-turbo"}]
