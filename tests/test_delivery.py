from src.deliver import should_create_document


def test_should_create_document_only_when_three_or_more_proposals_exist():
    assert should_create_document(0) is False
    assert should_create_document(2) is False
    assert should_create_document(3) is True
