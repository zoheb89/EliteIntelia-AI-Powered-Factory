from c_invent.services.document_intel import extract_upload

class Upload:
    name="test.txt"
    type="text/plain"
    def getvalue(self): return b"hello"

def test_text_extraction():
    text, meta=extract_upload(Upload())
    assert text=="hello"
    assert meta["extension"]=="txt"
