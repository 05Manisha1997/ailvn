"""
indexer/policy_indexer.py
Offline pipeline: PDF → chunks → embeddings → Azure AI Search index.
Run: python indexer/policy_indexer.py --pdf path/to/policy.pdf --policy-id POL-001
"""
import os
import argparse
import json
from config import settings


def get_embedding(text: str, client) -> list[float]:
    response = client.embeddings.create(
        input=text,
        model=settings.azure_openai_embedding_deployment,
    )
    return response.data[0].embedding


def classify_coverage_type(text: str, client) -> str:
    """Use GPT-4o to tag the coverage type of a chunk."""
    response = client.chat.completions.create(
        model=settings.azure_openai_deployment,
        messages=[
            {
                "role": "system",
                "content": (
                    "Classify this insurance policy text into ONE of: "
                    "hospital, surgery, dental, mental_health, pharmacy, "
                    "maternity, physiotherapy, other. "
                    "Return ONLY the class name, nothing else."
                ),
            },
            {"role": "user", "content": text[:500]},
        ],
        max_tokens=10,
    )
    return response.choices[0].message.content.strip().lower()


def extract_section_title(chunk) -> str:
    """Best-effort section title from chunk metadata or first line."""
    if hasattr(chunk, "metadata") and chunk.metadata.get("section"):
        return chunk.metadata["section"]
    first_line = chunk.page_content.strip().split("\n")[0]
    return first_line[:80] if first_line else "General"


def index_policy_document(pdf_path: str, policy_id: str) -> None:
    from langchain_community.document_loaders import PyPDFLoader
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    from azure.search.documents import SearchClient
    from azure.core.credentials import AzureKeyCredential
    from openai import AzureOpenAI

    print(f"Loading {pdf_path}...")
    loader = PyPDFLoader(pdf_path)
    pages = loader.load()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=100,
        separators=["\n\n", "\n", ".", " "],
    )
    chunks = splitter.split_documents(pages)
    print(f"Split into {len(chunks)} chunks")

    oai = AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_key,
        api_version=settings.azure_openai_api_version,
    )
    search_client = SearchClient(
        endpoint=settings.azure_search_endpoint,
        index_name=settings.azure_search_index,
        credential=AzureKeyCredential(settings.azure_search_key),
    )

    documents_to_index = []
    for i, chunk in enumerate(chunks):
        print(f"  Embedding chunk {i+1}/{len(chunks)}...", end="\r")
        embedding = get_embedding(chunk.page_content, oai)
        coverage_type = classify_coverage_type(chunk.page_content, oai)

        documents_to_index.append({
            "id": f"{policy_id}-chunk-{i}",
            "policy_id": policy_id,
            "content": chunk.page_content,
            "section_title": extract_section_title(chunk),
            "content_vector": embedding,
            "coverage_type": coverage_type,
        })

    print(f"\nUploading {len(documents_to_index)} documents to Azure AI Search...")
    search_client.upload_documents(documents_to_index)
    print(f"Done! Indexed {len(documents_to_index)} chunks for policy {policy_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index a policy PDF into Azure AI Search")
    parser.add_argument("--pdf", required=True, help="Path to the policy PDF file")
    parser.add_argument("--policy-id", required=True, help="Policy ID (e.g. POL-001)")
    args = parser.parse_args()
    index_policy_document(args.pdf, args.policy_id)
