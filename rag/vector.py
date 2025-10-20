from typing import Optional

from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from pathlib import Path
import os
import chromadb
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma as LCChroma
from chromadb.config import Settings as ChromaSettings

def _settings(dir_: str) -> ChromaSettings:
    # Persistent on-disk storage (Chroma 0.5+)
    return ChromaSettings(
        chroma_db_impl="duckdb+parquet",
        persist_directory=dir_,
        anonymized_telemetry=False,
    )


def _embedding():
    # HuggingFace multilingual E5 (default: large). Override with EMBED_MODEL.
    model = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-large")
    return HuggingFaceEmbeddings(model_name=model)


def build_index(docs: list[Document], dir_: str) -> Optional[Chroma]:
    if not docs:
        return None
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
    chunks = splitter.split_documents(docs)
    if not chunks:
        return None
    emb = _embedding()
    collection_name = Path(dir_).name
    client = chromadb.PersistentClient(path=dir_)
    vs = LCChroma.from_documents(chunks, emb, client=client, collection_name=collection_name)
    return vs


def as_retriever(dir_: str, k: int = 5):
    emb = _embedding()
    collection_name = Path(dir_).name
    client = chromadb.PersistentClient(path=dir_)
    vs = LCChroma(collection_name=collection_name, client=client, embedding_function=emb)
    return vs.as_retriever(search_kwargs={"k": k})
