from pathlib import Path
from typing import List

from langchain_community.document_loaders import PyPDFLoader, TextLoader, CSVLoader
from langchain_core.documents import Document


def load_dir(path: str) -> List[Document]:
    """Load documents from directory recursively.

    Supports: pdf, md, txt, csv. Silently skips unreadable files.
    """
    docs: List[Document] = []
    p = Path(path)
    if not p.exists():
        return docs
    for f in p.rglob("*"):
        if not f.is_file():
            continue
        suf = f.suffix.lower()
        try:
            if suf == ".pdf":
                docs += PyPDFLoader(str(f)).load()
            elif suf in [".md", ".txt"]:
                docs += TextLoader(str(f), encoding="utf-8").load()
            elif suf == ".csv":
                docs += CSVLoader(str(f)).load()
        except Exception:
            # Skip problematic files without breaking the flow
            continue
    return docs

