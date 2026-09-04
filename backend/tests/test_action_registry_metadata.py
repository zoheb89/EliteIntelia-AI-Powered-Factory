from c_invent.services.action_registry import ACTIONS, next_action_spec

def test_actions_are_loaded_from_metadata():
    assert ACTIONS
    assert next_action_spec({"intake": False}).id == "intake.create"
    assert next_action_spec({"intake": True, "discovery": False}).id == "discovery.run"
