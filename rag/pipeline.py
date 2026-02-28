"""
rag/pipeline.py

Phase 5 — RAG Pipeline

Complete retrieval-augmented generation pipeline:
1. Document Loading — from Azure Blob, local files, URLs, REST APIs
2. Text Chunking — LangChain RecursiveCharacterTextSplitter
3. Embedding — Azure OpenAI Ada-002 or HuggingFace (free)
4. Vector Store — ChromaDB (open source, in-process or Docker)
5. Semantic Retrieval — top-k cosine similarity search
"""
import hashlib
import asyncio
from typing import Optional
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    AzureBlobStorageContainerLoader,
    WebBaseLoader,
    TextLoader,
    PyPDFLoader,
)

from config.settings import get_settings
from config.azure_clients import get_chroma_client, get_blob_service_client
from utils.logger import logger

settings = get_settings()


@dataclass
class RetrievedChunk:
    doc_id: str
    content: str
    source: str
    score: float
    metadata: dict


class RAGPipeline:
    """
    Manages document ingestion and retrieval for a call session.
    Each call gets its own ChromaDB collection (auto-deleted post-call).
    Supports multiple document sources per intent.
    """

    def __init__(self):
        self._chroma = get_chroma_client()
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
            separators=["\n\n", "\n", ".", "!", "?", " ", ""],
        )
        self._embedder = self._init_embedder()

    def _init_embedder(self):
        """
        Initialize embedding model.
        Uses Azure OpenAI Ada-002 if configured, else free HuggingFace model.
        """
        if settings.azure_openai_key and not settings.use_local_llm:
            from langchain_openai import AzureOpenAIEmbeddings
            logger.info("embedder_init", model="azure-openai-ada-002")
            return AzureOpenAIEmbeddings(
                azure_deployment=settings.azure_openai_embedding_deployment,
                azure_endpoint=settings.azure_openai_endpoint,
                api_key=settings.azure_openai_key,
            )
        else:
            # Free alternative: HuggingFace sentence-transformers
            from langchain_community.embeddings import HuggingFaceEmbeddings
            logger.info("embedder_init", model="sentence-transformers/all-MiniLM-L6-v2")
            return HuggingFaceEmbeddings(
                model_name="sentence-transformers/all-MiniLM-L6-v2"
            )

    def get_or_create_collection(self, collection_name: str):
        """Get or create a ChromaDB collection for a call session."""
        return self._chroma.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def load_documents(self, source: dict) -> list[str]:
        """
        Load documents from various sources.
        source dict format:
            {"type": "azure_blob", "container": "...", "prefix": "..."}
            {"type": "url", "urls": [...]}
            {"type": "file", "paths": [...]}
            {"type": "text", "content": "...", "title": "..."}
        """
        docs = []
        source_type = source.get("type")

        if source_type == "azure_blob":
            loader = AzureBlobStorageContainerLoader(
                conn_str=settings.azure_storage_connection_string,
                container=source.get("container", settings.azure_storage_container_docs),
                prefix=source.get("prefix", ""),
            )
            docs = loader.load()

        elif source_type == "url":
            loader = WebBaseLoader(source.get("urls", []))
            docs = loader.load()

        elif source_type == "file":
            for path in source.get("paths", []):
                if path.endswith(".pdf"):
                    docs.extend(PyPDFLoader(path).load())
                else:
                    docs.extend(TextLoader(path).load())

        elif source_type == "text":
            from langchain.schema import Document
            docs = [Document(
                page_content=source["content"],
                metadata={"source": source.get("title", "inline"), "type": "text"},
            )]

        logger.info("documents_loaded", source_type=source_type, count=len(docs))
        return docs

    def ingest_for_call(
        self,
        call_id: str,
        intent: str,
        sources: list[dict],
    ) -> tuple[str, list[dict]]:
        """
        Load, chunk, embed, and store documents for a specific call + intent.
        Returns (collection_name, metadata_list) for session tracking.

        Documents from previous intents in the same call are preserved
        (accumulated in the same collection).
        """
        # Use a single collection per call (accumulate docs across intent changes)
        collection_name = f"call_{call_id.replace('-', '_')}"
        collection = self.get_or_create_collection(collection_name)

        all_docs = []
        for source in sources:
            try:
                docs = self.load_documents(source)
                all_docs.extend(docs)
            except Exception as e:
                logger.error("doc_load_failed", source=source, error=str(e))

        if not all_docs:
            logger.warning("no_documents_loaded", call_id=call_id, intent=intent)
            return collection_name, []

        # Chunk documents
        chunks = self._splitter.split_documents(all_docs)
        logger.info("chunks_created", count=len(chunks), intent=intent)

        # Generate embeddings and store
        texts = [chunk.page_content for chunk in chunks]
        metadatas = [
            {
                **chunk.metadata,
                "intent": intent,
                "call_id": call_id,
                "chunk_index": i,
            }
            for i, chunk in enumerate(chunks)
        ]
        ids = [
            hashlib.md5(f"{call_id}:{intent}:{i}:{text[:50]}".encode()).hexdigest()
            for i, text in enumerate(texts)
        ]

        # Generate embeddings
        embeddings = self._embedder.embed_documents(texts)

        # Store in ChromaDB
        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

        logger.info("docs_ingested_to_vector_store",
                    call_id=call_id,
                    intent=intent,
                    chunk_count=len(chunks))

        return collection_name, metadatas

    def retrieve(
        self,
        call_id: str,
        query: str,
        n_results: int = None,
    ) -> list[RetrievedChunk]:
        """
        Retrieve top-k most relevant chunks for a query from the call's collection.
        Searches ALL documents ingested for this call (across all intents).
        """
        n_results = n_results or settings.rag_top_k_chunks
        collection_name = f"call_{call_id.replace('-', '_')}"

        try:
            collection = self._chroma.get_collection(collection_name)
        except Exception:
            logger.warning("collection_not_found", call_id=call_id)
            return []

        # Embed the query
        query_embedding = self._embedder.embed_query(query)

        # Search
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        if not results["documents"] or not results["documents"][0]:
            return []

        chunks = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            chunks.append(RetrievedChunk(
                doc_id=meta.get("call_id", "") + "_" + str(meta.get("chunk_index", 0)),
                content=doc,
                source=meta.get("source", "unknown"),
                score=1.0 - dist,  # Convert cosine distance to similarity
                metadata=meta,
            ))

        logger.info("chunks_retrieved",
                    call_id=call_id,
                    query_preview=query[:50],
                    count=len(chunks))
        return chunks

    def assemble_context(self, chunks: list[RetrievedChunk]) -> str:
        """
        Assemble retrieved chunks into a context string for LLM prompting.
        Format: SOURCE: [source] \n CONTENT: [text]
        """
        if not chunks:
            return "No relevant documents found."

        parts = []
        for i, chunk in enumerate(chunks, 1):
            parts.append(
                f"[Source {i}: {chunk.source}] (relevance: {chunk.score:.2f})\n{chunk.content}"
            )
        return "\n\n---\n\n".join(parts)

    def cleanup_call(self, call_id: str):
        """
        Delete the call's ChromaDB collection when the call ends.
        This is the 'temporary memory' cleanup.
        """
        collection_name = f"call_{call_id.replace('-', '_')}"
        try:
            self._chroma.delete_collection(collection_name)
            logger.info("temp_docs_deleted", call_id=call_id, collection=collection_name)
        except Exception as e:
            logger.warning("temp_docs_delete_failed", error=str(e))


_rag_pipeline: Optional[RAGPipeline] = None


def get_rag_pipeline() -> RAGPipeline:
    global _rag_pipeline
    if _rag_pipeline is None:
        _rag_pipeline = RAGPipeline()
    return _rag_pipeline
