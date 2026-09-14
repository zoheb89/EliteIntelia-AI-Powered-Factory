import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.evidence import extract_explicit_intent
from core.next_action import recommend
from core.domain.lifecycle import LifecycleState, StageStatus


def test_extracts_only_explicit_customer_intent():
    text = (
        "The objective of this RFP is to establish a governed enterprise data "
        "platform that reduces reporting delivery from eight business days to "
        "two business days. The approved cloud remains to be confirmed."
    )
    intent = extract_explicit_intent(text)
    assert "establish a governed enterprise data platform" in intent
    assert "approved cloud" not in intent


def test_missing_intent_never_becomes_a_fake_executable_stage():
    state = LifecycleState()
    state.statuses["evidence"] = StageStatus.COMPLETE
    result = recommend(state, [], evidence_count=1)
    assert result["primary"]["kind"] == "answer_questions"
    assert result["primary"]["stage_id"] == "intent"
    assert result["primary"]["id"] == "confirm-business-intent"
