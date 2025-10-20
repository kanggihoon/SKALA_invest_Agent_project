from typing import Optional

from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from chromadb.config import Settings as ChromaSettings

# Reuse a single Chroma Settings instance in-process to avoid
# "An instance of Chroma already exists for ephemeral with different settings"
CHROMA_SETTINGS = ChromaSettings(anonymized_telemetry=False)


def _embedding():
    # Force HuggingFace embeddings (multilingual E5).
    # This avoids network/API dependency on OpenAI for embeddings.
    return HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-base")


def build_index(docs: list[Document], dir_: str) -> Optional[Chroma]:
    if not docs:
        return None
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
    chunks = splitter.split_documents(docs)
    if not chunks:
        return None
    emb = _embedding()
    client_settings = CHROMA_SETTINGS
    vs = Chroma.from_documents(
        chunks,
        emb,
        persist_directory=dir_,
        client_settings=client_settings,
    )
    return vs


def as_retriever(dir_: str, k: int = 5):
    emb = _embedding()
    client_settings = CHROMA_SETTINGS
    return Chroma(
        persist_directory=dir_,
        embedding_function=emb,
        client_settings=client_settings,
    ).as_retriever(search_kwargs={"k": k})
