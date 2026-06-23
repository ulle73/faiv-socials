from src.deliver import should_create_document


def test_should_create_document_only_when_at_least_one_proposal_exists():
    assert should_create_document(0) is False
    assert should_create_document(1) is True
    assert should_create_document(5) is True
