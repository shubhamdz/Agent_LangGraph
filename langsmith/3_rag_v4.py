
import os
import json
import hashlib
from pathlib import Path

from dotenv import load_dotenv
from langsmith import traceable

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_groq import ChatGroq
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.embeddings import Embeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import (
    RunnableParallel,
    RunnablePassthrough,
    RunnableLambda,
)
from langchain_core.output_parsers import StrOutputParser
import time 


# ----------------- ENVIRONMENT -----------------

load_dotenv()

os.environ["LANGCHAIN_PROJECT"] = "RAG_v4"

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY is missing from .env")

PDF_PATH = "dl-curriculum.pdf"
INDEX_ROOT = Path(".indices")
INDEX_ROOT.mkdir(exist_ok=True)

EMBEDDING_MODEL = "gemini-embedding-001"


# ----------------- GEMINI EMBEDDINGS -----------------


class GeminiEmbeddingWrapper(Embeddings):

    def __init__(self, model_name):
        self.client = GoogleGenerativeAIEmbeddings(
            model=model_name,
            google_api_key=GOOGLE_API_KEY,
        )

    def embed_documents(self, texts):

        all_embeddings = []
        batch_size = 100

        for i in range(0, len(texts), batch_size):

            batch = texts[i:i + batch_size]
            attempts = 0
            max_retries = 5

            while True:
                try:
                    print(
                        f"Embedding: {i + len(batch)}/{len(texts)}"
                    )

                    batch_embeddings = self.client.embed_documents(
                        batch,
                        batch_size=batch_size,
                        task_type="RETRIEVAL_DOCUMENT",
                    )

                    all_embeddings.extend(batch_embeddings)
                    break

                except Exception as e:

                    error = str(e)

                    if (
                        "429" not in error
                        and "RESOURCE_EXHAUSTED" not in error
                    ):
                        raise

                    attempts += 1

                    if attempts > max_retries:
                        raise

                    wait_time = 25

                    print(
                        f"Gemini rate limit reached. "
                        f"Retrying in {wait_time} seconds "
                        f"({attempts}/{max_retries})"
                    )

                    time.sleep(wait_time)

        return all_embeddings

    def embed_query(self, text):

        return self.client.embed_query(
            text,
            task_type="RETRIEVAL_QUERY",
        )


def build_embeddings(embed_model_name):
    return GeminiEmbeddingWrapper(embed_model_name)



# ----------------- PDF HELPERS -----------------

@traceable(name="load_pdf")
def load_pdf(path: str):

    return PyPDFLoader(path).load()


@traceable(name="split_documents")
def split_documents(docs, chunk_size=1000, chunk_overlap=150):

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    return splitter.split_documents(docs)


@traceable(name="build_vectorstore")
def build_vectorstore(splits, embed_model_name):

    embeddings = build_embeddings(embed_model_name)

    return FAISS.from_documents(
        documents=splits,
        embedding=embeddings,
    )


# ----------------- CACHE KEY / FINGERPRINT -----------------

def _file_fingerprint(path: str) -> dict:

    p = Path(path)
    h = hashlib.sha256()

    with p.open("rb") as f:

        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)

    return {
        "sha256": h.hexdigest(),
        "size": p.stat().st_size,
        "mtime": int(p.stat().st_mtime),
    }


def _index_key(
    pdf_path: str,
    chunk_size: int,
    chunk_overlap: int,
    embed_model_name: str,
) -> str:

    meta = {
        "pdf_fingerprint": _file_fingerprint(pdf_path),
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "embedding_model": embed_model_name,
        "format": "v2",
    }

    return hashlib.sha256(
        json.dumps(meta, sort_keys=True).encode("utf-8")
    ).hexdigest()


# ----------------- LOAD / BUILD INDEX -----------------

@traceable(name="load_index", tags=["index"])
def load_index_run(index_dir: Path, embed_model_name: str):

    embeddings = build_embeddings(embed_model_name)

    return FAISS.load_local(
        str(index_dir),
        embeddings,
        allow_dangerous_deserialization=True,
    )


@traceable(name="build_index", tags=["index"])
def build_index_run(
    pdf_path: str,
    index_dir: Path,
    chunk_size: int,
    chunk_overlap: int,
    embed_model_name: str,
):

    docs = load_pdf(pdf_path)

    splits = split_documents(
        docs,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    print(f"Total PDF pages: {len(docs)}")
    print(f"Total chunks: {len(splits)}")

    vectorstore = build_vectorstore(
        splits,
        embed_model_name,
    )

    index_dir.mkdir(parents=True, exist_ok=True)

    vectorstore.save_local(str(index_dir))

    (index_dir / "meta.json").write_text(
        json.dumps(
            {
                "pdf_path": os.path.abspath(pdf_path),
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "embedding_model": embed_model_name,
            },
            indent=2,
        )
    )

    print("FAISS index saved successfully!")

    return vectorstore


# ----------------- INDEX DISPATCHER -----------------

def load_or_build_index(
    pdf_path: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
    embed_model_name: str = EMBEDDING_MODEL,
    force_rebuild: bool = False,
):

    key = _index_key(
        pdf_path,
        chunk_size,
        chunk_overlap,
        embed_model_name,
    )

    index_dir = INDEX_ROOT / key

    cache_hit = (
        (index_dir / "index.faiss").exists()
        and (index_dir / "index.pkl").exists()
        and not force_rebuild
    )

    if cache_hit:

        print("FAISS cache found. Loading existing index...")

        return load_index_run(
            index_dir,
            embed_model_name,
        )

    print("No valid cache found. Building new index...")

    return build_index_run(
        pdf_path,
        index_dir,
        chunk_size,
        chunk_overlap,
        embed_model_name,
    )


# ----------------- LLM / PROMPT -----------------

llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0,
)

prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "Answer ONLY from the provided context. "
        "If the answer is not found, say you don't know.",
    ),
    (
        "human",
        "Question: {question}\n\nContext:\n{context}",
    ),
])


def format_docs(docs):

    return "\n\n".join(
        document.page_content
        for document in docs
    )


# ----------------- PIPELINE SETUP -----------------

@traceable(name="setup_pipeline", tags=["setup"])
def setup_pipeline(
    pdf_path: str,
    chunk_size=1000,
    chunk_overlap=150,
    embed_model_name=EMBEDDING_MODEL,
    force_rebuild=False,
):

    return load_or_build_index(
        pdf_path=pdf_path,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        embed_model_name=embed_model_name,
        force_rebuild=force_rebuild,
    )


# ----------------- COMPLETE RAG RUN -----------------

@traceable(name="pdf_rag_full_run")
def setup_pipeline_and_query(
    pdf_path: str,
    question: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
    embed_model_name: str = EMBEDDING_MODEL,
    force_rebuild: bool = False,
):

    vectorstore = setup_pipeline(
        pdf_path,
        chunk_size,
        chunk_overlap,
        embed_model_name,
        force_rebuild,
    )

    retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 4},
    )

    parallel = RunnableParallel({
        "context": retriever | RunnableLambda(format_docs),
        "question": RunnablePassthrough(),
    })

    chain = parallel | prompt | llm | StrOutputParser()

    return chain.invoke(
        question,
        config={
            "run_name": "pdf_rag_query",
            "tags": ["qa"],
            "metadata": {"k": 4},
        },
    )


# ----------------- CLI -----------------

if __name__ == "__main__":

    print("PDF RAG ready!")

    q = input("\nQ: ").strip()

    ans = setup_pipeline_and_query(
        PDF_PATH,
        q,
    )

    print("\nA:", ans)
