"""Agent LLM client: AGENT_BASE_URL routing and cache-marker stripping."""
from services.agent.agent_service import _get_client, _is_claude_model, _strip_cache_markers


def test_default_is_anthropic(monkeypatch):
    from config import agent_config
    monkeypatch.setattr(agent_config, 'AGENT_BASE_URL', None)
    monkeypatch.setattr(agent_config, 'AGENT_API_KEY', 'sk-test')
    assert 'anthropic.com' in str(_get_client().base_url)


def test_base_url_override(monkeypatch):
    from config import agent_config
    monkeypatch.setattr(agent_config, 'AGENT_BASE_URL', 'https://api.deepseek.com/anthropic')
    monkeypatch.setattr(agent_config, 'AGENT_API_KEY', 'sk-ds')
    client = _get_client()
    assert 'deepseek' in str(client.base_url)
    assert client.api_key == 'sk-ds'


def test_model_routing_and_cache_markers():
    assert _is_claude_model('claude-sonnet-4-6')
    assert not _is_claude_model('deepseek-chat')
    out = _strip_cache_markers([{'text': 'hi', 'cache_control': {}}, 'plain'])
    assert out == [{'text': 'hi'}, 'plain']
