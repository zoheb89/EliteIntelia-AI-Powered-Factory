from c_invent.services.config import load_settings

def test_default_model():
    settings=load_settings()
    assert settings.llm_model=="openai.gpt-5.1"
    assert settings.llm_provider=="azure"
