from c_invent.services.action_registry import next_action_spec, applicable_actions


def base_state():
    return {
        "intake": True, "discovery": True, "environment": True, "assessment": True,
        "architecture": False, "architecture_approved": False, "platform": False,
        "metadata": False, "engineering": False, "validate": False, "deploy": False,
        "operate": False,
    }


def test_action_plan_is_state_driven():
    s = base_state()
    assert next_action_spec(s).id == "architecture.generate"
    s["architecture"] = True
    assert next_action_spec(s).id == "architecture.approve"
    s["architecture_approved"] = True
    assert next_action_spec(s).id == "platform.configure"


def test_completed_state_has_no_action():
    s = base_state()
    for k in ("architecture", "architecture_approved", "platform", "metadata", "engineering", "validate", "deploy", "operate"):
        s[k] = True
    assert next_action_spec(s) is None
