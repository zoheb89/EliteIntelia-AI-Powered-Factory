from c_invent.services.platforms import environment_fields


def test_existing_environment_fields_are_safe_and_required():
    fields = environment_fields('existing')
    assert fields['endpoint']['required'] is True
    assert fields['credential_ref']['required'] is True
    assert 'secret NAME only' in fields['credential_ref']['label']


def test_provision_environment_fields_are_customer_scope_driven():
    fields = environment_fields('provision')
    assert fields['account_scope']['required'] is True
    assert fields['region']['required'] is True
    assert fields['credential_ref']['required'] is True
    assert 'endpoint' not in fields
