# backend/scripts/generate_embeddings_for_existing_documents.py

import asyncio
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import sys
import os
import urllib.parse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from services.embedding_service import EmbeddingService


def _as_clean_str(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _filename_from_urlish(urlish: str) -> str:
    """Extract filename from a URL or URL-like string."""
    try:
        parsed = urllib.parse.urlparse(urlish)
        path = parsed.path or ""
        name = path.split("/")[-1] if "/" in path else path
        name = urllib.parse.unquote(name)
        return _as_clean_str(name)
    except Exception:
        return ""


def extract_filename(result_dict: dict) -> str:
    """Extract filename - handle both parent docs and child chunks"""

    # 1) title
    title = _as_clean_str(result_dict.get("title"))
    if title:
        return title

    # 2) filepath
    filepath = _as_clean_str(result_dict.get("filepath"))
    if filepath:
        return filepath.split("/")[-1] if "/" in filepath else filepath

    # 3) url (your docs have this; this is the best fallback)
    url = _as_clean_str(result_dict.get("url"))
    if url:
        name = _filename_from_urlish(url)
        if name:
            return name

    # 4) parent_id
    parent_id = _as_clean_str(result_dict.get("parent_id"))
    if parent_id:
        name = _filename_from_urlish(parent_id)
        if name:
            return name

    return "Unknown Document"


async def generate_embeddings_for_all_documents():
    """Generate embeddings for all documents in the search index"""

    print("🚀 Starting embedding generation for existing documents...")

    embedding_service = EmbeddingService()

    search_client = SearchClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        index_name=config.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY)
    )

    try:
        print(f"Fetching documents from index: {config.AZURE_SEARCH_INDEX_NAME}")

        # Pull one doc to infer key field
        results = search_client.search(search_text="*", top=1)

        first_result = None
        for r in results:
            first_result = dict(r)
            break

        if not first_result:
            print("❌ No documents found in index")
            return

        # Identify key field
        key_field = None
        possible_keys = ["chunk_id", "id", "document_id", "key", "metadata_storage_path"]

        for possible_key in possible_keys:
            if possible_key in first_result:
                key_field = possible_key
                print(f"✓ Found key field: {key_field}")
                break

        if not key_field:
            print(f"❌ Could not identify key field. Available fields: {list(first_result.keys())}")
            return

        # Fetch all docs (top=1000 is OK for your current 61 docs; if it grows, we should paginate via skip)
        print("Re-fetching all documents...")
        results = search_client.search(search_text="*", top=1000)

        documents_to_update = []
        processed = 0
        skipped_no_content = 0
        skipped_no_key = 0
        unknown_count = 0

        for result in results:
            result_dict = dict(result)

            # content
            content = result_dict.get("content", "")
            if isinstance(content, list):
                content = " ".join(_as_clean_str(x) for x in content)

            content = _as_clean_str(content)
            if not content:
                skipped_no_content += 1
                continue

            # key
            key_value = result_dict.get(key_field)
            if key_value is None or _as_clean_str(key_value) == "":
                skipped_no_key += 1
                continue

            filename = extract_filename(result_dict)
            if filename == "Unknown Document":
                unknown_count += 1

            processed += 1
            print(f"  Processing document {processed}: {filename[:80]}...")

            embedding = embedding_service.generate_embedding(content[:32000])

            if len(embedding) != config.EMBEDDING_DIMENSIONS:
                print(f"    ⚠️  Warning: Expected {config.EMBEDDING_DIMENSIONS} dims, got {len(embedding)}")

            doc_update = {
                key_field: key_value,
                "content_vector": embedding
            }
            documents_to_update.append(doc_update)

            # Upload in batches of 10
            if len(documents_to_update) >= 10:
                print(f"  📤 Uploading batch of {len(documents_to_update)} embeddings...")
                try:
                    search_client.merge_or_upload_documents(documents=documents_to_update)
                    print("  ✅ Batch uploaded successfully")
                except Exception as batch_error:
                    print(f"  ❌ Batch upload error: {batch_error}")
                    # fallback: one-by-one
                    for doc in documents_to_update:
                        try:
                            search_client.merge_or_upload_documents(documents=[doc])
                        except Exception as doc_error:
                            print(f"    ❌ Failed to upload doc: {doc_error}")
                documents_to_update = []

        # Upload remaining
        if documents_to_update:
            print(f"  📤 Uploading final batch of {len(documents_to_update)} embeddings...")
            try:
                search_client.merge_or_upload_documents(documents=documents_to_update)
                print("  ✅ Final batch uploaded successfully")
            except Exception as batch_error:
                print(f"  ❌ Final batch upload error: {batch_error}")
                for doc in documents_to_update:
                    try:
                        search_client.merge_or_upload_documents(documents=[doc])
                    except Exception as doc_error:
                        print(f"    ❌ Failed to upload doc: {doc_error}")

        print("\n" + "=" * 60)
        print(f"✅ Successfully processed {processed} documents!")
        if skipped_no_content:
            print(f"ℹ️  Skipped {skipped_no_content} docs with no content")
        if skipped_no_key:
            print(f"ℹ️  Skipped {skipped_no_key} docs with no key value")
        if unknown_count:
            print(f"⚠️  {unknown_count} docs could not extract filename (but embeddings were generated)")
        print("🎉 Hybrid search is now fully operational!")
        print("=" * 60)

    except Exception as e:
        print(f"❌ Error generating embeddings: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(generate_embeddings_for_all_documents())
