import io, json, yaml

def extract_upload(uploaded):
    data = uploaded.getvalue()
    name = uploaded.name.lower()
    meta = {"name": uploaded.name, "extension": name.rsplit(".",1)[-1] if "." in name else ""}
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages), {**meta, "pages":len(reader.pages)}
        except Exception as e:
            return f"[PDF extraction failed: {e}]", meta
    if name.endswith(".docx"):
        try:
            from docx import Document
            doc=Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs), meta
        except Exception as e:
            return f"[DOCX extraction failed: {e}]", meta
    if name.endswith(".xlsx"):
        try:
            import pandas as pd
            xls=pd.ExcelFile(io.BytesIO(data))
            chunks=[]
            for sheet in xls.sheet_names:
                df=pd.read_excel(xls,sheet_name=sheet)
                chunks.append(f"## SHEET: {sheet}\n{df.to_csv(index=False)}")
            return "\n\n".join(chunks), {**meta, "sheets":xls.sheet_names}
        except Exception as e:
            return f"[XLSX extraction failed: {e}]", meta
    if name.endswith(".json"):
        try: return json.dumps(json.loads(data.decode("utf-8")), indent=2), meta
        except Exception: pass
    if name.endswith((".yaml",".yml")):
        try: return json.dumps(yaml.safe_load(data.decode("utf-8")), indent=2), meta
        except Exception: pass
    return data.decode("utf-8","replace"), meta
