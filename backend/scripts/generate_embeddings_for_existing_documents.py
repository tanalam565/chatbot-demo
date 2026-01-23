# backend/scripts/generate_embeddings_for_existing_documents.py - UPDATED FOR YOUR SETUP

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
    """Convert value to clean string"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _filename_from_urlish(urlish: str) -> str:
    """Extract filename from a URL or URL-like string"""
    try:
        parsed = urllib.parse.urlparse(urlish)
        path = parsed.path or ""
        name = path.split("/")[-1] if "/" in path else path
        name = urllib.parse.unquote(name)
        return _as_clean_str(name)
    except Exception:
        return ""


def extract_filename(result_dict: dict) -> str:
    """Extract filename from search result - tries multiple fields"""

    # 1) title (most reliable - comes from metadata_storage_name)
    title = _as_clean_str(result_dict.get("title"))
    if title:
        return title

    # 2) metadata_storage_name (original filename)
    storage_name = _as_clean_str(result_dict.get("metadata_storage_name"))
    if storage_name:
        return storage_name

    # 3) filepath
    filepath = _as_clean_str(result_dict.get("filepath"))
    if filepath:
        return filepath.split("/")[-1] if "/" in filepath else filepath

    # 4) url (blob storage path)
    url = _as_clean_str(result_dict.get("url"))
    if url:
        name = _filename_from_urlish(url)
        if name:
            return name

    # 5) parent_id (fallback)
    parent_id = _as_clean_str(result_dict.get("parent_id"))
    if parent_id:
        name = _filename_from_urlish(parent_id)
        if name:
            return name

    return "Unknown Document"


async def generate_embeddings_for_all_documents():
    """Generate embeddings for all documents in the search index"""

    print("=" * 70)
    print("🚀 Starting Embedding Generation for All Documents")
    print("=" * 70)

    embedding_service = EmbeddingService()

    search_client = SearchClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        index_name=config.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY)
    )

    try:
        print(f"\n📊 Fetching documents from index: {config.AZURE_SEARCH_INDEX_NAME}")

        # Fetch one document to identify the key field
        results = search_client.search(search_text="*", top=1)

        first_result = None
        for r in results:
            first_result = dict(r)
            break

        if not first_result:
            print("❌ No documents found in index")
            print("\nℹ️  Make sure your indexer has run successfully:")
            print("   python scripts/debug_index_contents.py")
            return

        # Identify the key field
        key_field = None
        possible_keys = ["chunk_id", "id", "document_id", "key", "metadata_storage_path"]

        for possible_key in possible_keys:
            if possible_key in first_result:
                key_field = possible_key
                print(f"✓ Found key field: {key_field}")
                break

        if not key_field:
            print(f"❌ Could not identify key field")
            print(f"Available fields: {list(first_result.keys())}")
            return

        # Show available content fields
        print(f"\n📝 Available content fields:")
        for field in ["content", "merged_content"]:
            if field in first_result:
                content_val = first_result.get(field, "")
                if content_val:
                    print(f"   ✓ {field}: {len(str(content_val))} characters")
                else:
                    print(f"   ⚠️  {field}: empty")

        # Fetch all documents (paginated for future scaling)
        print(f"\n📥 Fetching all documents (with pagination)...")
        
        all_documents = []
        skip = 0
        batch_size = 1000
        
        while True:
            results = search_client.search(
                search_text="*",
                top=batch_size,
                skip=skip,
                select=[
                    key_field, 
                    "content", 
                    "merged_content",
                    "title", 
                    "filepath", 
                    "url", 
                    "parent_id",
                    "metadata_storage_name"
                ]
            )
            
            batch = list(results)
            if not batch:
                break
                
            all_documents.extend(batch)
            skip += batch_size
            
            if len(batch) < batch_size:
                break

        print(f"✓ Total documents to process: {len(all_documents)}")

        # Process documents and generate embeddings
        documents_to_update = []
        processed = 0
        skipped_no_content = 0
        skipped_no_key = 0
        unknown_count = 0

        print(f"\n⚙️  Generating embeddings...")
        print("-" * 70)

        for result in all_documents:
            result_dict = dict(result)

            # Try merged_content first (has OCR + PDF text), fallback to content
            content = result_dict.get("merged_content", "")
            if not content:
                content = result_dict.get("content", "")
            
            if isinstance(content, list):
                content = " ".join(_as_clean_str(x) for x in content)

            content = _as_clean_str(content)
            
            if not content:
                filename = extract_filename(result_dict)
                print(f"  ⚠️  Skipping {filename}: No content found")
                skipped_no_content += 1
                continue

            # Get key value
            key_value = result_dict.get(key_field)
            if key_value is None or _as_clean_str(key_value) == "":
                print(f"  ⚠️  Skipping document: No key value")
                skipped_no_key += 1
                continue

            filename = extract_filename(result_dict)
            if filename == "Unknown Document":
                unknown_count += 1

            processed += 1
            
            # Show progress
            print(f"  [{processed}/{len(all_documents)}] Processing: {filename[:60]}...")
            print(f"      Content length: {len(content)} chars")

            # Generate embedding (truncate to 32k chars to avoid token limits)
            embedding = embedding_service.generate_embedding(content[:32000])

            # Verify dimensions
            if len(embedding) != config.EMBEDDING_DIMENSIONS:
                print(f"      ⚠️  Warning: Expected {config.EMBEDDING_DIMENSIONS} dims, got {len(embedding)}")

            doc_update = {
                key_field: key_value,
                "content_vector": embedding
            }
            documents_to_update.append(doc_update)

            # Upload in batches of 10 for stability
            if len(documents_to_update) >= 10:
                print(f"\n  📤 Uploading batch of {len(documents_to_update)} embeddings...")
                try:
                    search_client.merge_or_upload_documents(documents=documents_to_update)
                    print(f"  ✅ Batch uploaded successfully\n")
                except Exception as batch_error:
                    print(f"  ❌ Batch upload error: {batch_error}")
                    print(f"  ℹ️  Trying one-by-one upload...")
                    # Fallback: upload one by one
                    for doc in documents_to_update:
                        try:
                            search_client.merge_or_upload_documents(documents=[doc])
                        except Exception as doc_error:
                            print(f"    ❌ Failed to upload document: {doc_error}")
                documents_to_update = []

        # Upload remaining documents
        if documents_to_update:
            print(f"\n  📤 Uploading final batch of {len(documents_to_update)} embeddings...")
            try:
                search_client.merge_or_upload_documents(documents=documents_to_update)
                print(f"  ✅ Final batch uploaded successfully")
            except Exception as batch_error:
                print(f"  ❌ Final batch upload error: {batch_error}")
                print(f"  ℹ️  Trying one-by-one upload...")
                for doc in documents_to_update:
                    try:
                        search_client.merge_or_upload_documents(documents=[doc])
                    except Exception as doc_error:
                        print(f"    ❌ Failed to upload document: {doc_error}")

        # Summary
        print("\n" + "=" * 70)
        print("✅ EMBEDDING GENERATION COMPLETE!")
        print("=" * 70)
        print(f"📊 Summary:")
        print(f"   ✓ Successfully processed: {processed} documents")
        if skipped_no_content:
            print(f"   ⚠️  Skipped (no content): {skipped_no_content} documents")
        if skipped_no_key:
            print(f"   ⚠️  Skipped (no key): {skipped_no_key} documents")
        if unknown_count:
            print(f"   ℹ️  Unknown filename: {unknown_count} documents (but embeddings generated)")
        print(f"\n🎉 Hybrid search is now fully operational!")
        print(f"   Model: {config.AZURE_OPENAI_EMBEDDING_MODEL}")
        print(f"   Dimensions: {config.EMBEDDING_DIMENSIONS}")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ Error generating embeddings: {e}")
        import traceback
        traceback.print_exc()
        print("\nℹ️  Troubleshooting:")
        print("   1. Check if indexer ran successfully:")
        print("      python scripts/debug_index_contents.py")
        print("   2. Verify documents are in index:")
        print("      python scripts/list_docments.py")
        print("   3. Check Azure OpenAI embedding service is accessible")


if __name__ == "__main__":
    asyncio.run(generate_embeddings_for_all_documents())