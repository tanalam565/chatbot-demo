# backend/scripts/generate_embeddings_for_existing_documents.py - WITH CHUNKING

import asyncio
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import sys
import os
import urllib.parse
import hashlib

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from services.embedding_service import EmbeddingService


# CHUNKING CONFIGURATION
CHUNK_SIZE = 2000  # characters per chunk
CHUNK_OVERLAP = 500  # overlap between chunks


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list:
    """Split text into overlapping chunks"""
    if not text or len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # If not the last chunk, try to break at sentence/word boundary
        if end < len(text):
            # Look for sentence end (. ! ?)
            for i in range(end, max(start + chunk_size - 200, start), -1):
                if text[i] in '.!?':
                    end = i + 1
                    break
            else:
                # No sentence boundary, look for space
                for i in range(end, max(start + chunk_size - 100, start), -1):
                    if text[i] == ' ':
                        end = i
                        break
        
        chunks.append(text[start:end].strip())
        start = end - overlap  # overlap for context
    
    return chunks


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
    """Extract filename from search result"""
    title = _as_clean_str(result_dict.get("title"))
    if title:
        return title
    
    storage_name = _as_clean_str(result_dict.get("metadata_storage_name"))
    if storage_name:
        return storage_name
    
    filepath = _as_clean_str(result_dict.get("filepath"))
    if filepath:
        return filepath.split("/")[-1] if "/" in filepath else filepath
    
    url = _as_clean_str(result_dict.get("url"))
    if url:
        name = _filename_from_urlish(url)
        if name:
            return name
    
    parent_id = _as_clean_str(result_dict.get("parent_id"))
    if parent_id:
        name = _filename_from_urlish(parent_id)
        if name:
            return name
    
    return "Unknown Document"


def generate_chunk_id(parent_id: str, chunk_number: int) -> str:
    """Generate unique chunk ID"""
    combined = f"{parent_id}_chunk_{chunk_number}"
    # Base64 encode to match your existing chunk_id format
    import base64
    return base64.b64encode(combined.encode()).decode()


async def generate_embeddings_for_all_documents():
    """Generate embeddings for all documents with chunking"""

    print("=" * 70)
    print("🚀 Starting Chunked Embedding Generation")
    print("=" * 70)
    print(f"📏 Chunk size: {CHUNK_SIZE} characters")
    print(f"🔗 Chunk overlap: {CHUNK_OVERLAP} characters")

    embedding_service = EmbeddingService()

    search_client = SearchClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        index_name=config.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY)
    )

    try:
        # First, clear existing documents
        print(f"\n🗑️  Clearing existing index...")
        
        # Fetch all existing document IDs
        existing_results = search_client.search(
            search_text="*",
            select=["chunk_id"],
            top=10000
        )
        
        existing_ids = [dict(r)["chunk_id"] for r in existing_results]
        
        if existing_ids:
            print(f"   Found {len(existing_ids)} existing entries to delete...")
            # Delete in batches
            batch_size = 1000
            for i in range(0, len(existing_ids), batch_size):
                batch = existing_ids[i:i+batch_size]
                docs_to_delete = [{"chunk_id": doc_id} for doc_id in batch]
                search_client.delete_documents(documents=docs_to_delete)
                print(f"   Deleted {min(i+batch_size, len(existing_ids))}/{len(existing_ids)}")
            print(f"   ✅ Index cleared")
        else:
            print(f"   Index is empty")

        # Fetch source documents from blob storage metadata
        print(f"\n📥 Fetching source documents...")
        
        # Get unique parent documents (use parent_id or metadata_storage_path)
        results = search_client.search(
            search_text="*",
            top=1000,
            select=[
                "parent_id",
                "content", 
                "merged_content",
                "title", 
                "filepath", 
                "url",
                "metadata_storage_name",
                "metadata_storage_path",
                "metadata_storage_content_type"
            ]
        )
        
        # Group by parent document
        parent_docs = {}
        for result in results:
            result_dict = dict(result)
            parent_id = result_dict.get("parent_id") or result_dict.get("metadata_storage_path")
            
            if not parent_id:
                continue
            
            # Skip if already processed
            if parent_id in parent_docs:
                continue
            
            parent_docs[parent_id] = result_dict

        print(f"✓ Found {len(parent_docs)} unique documents")

        # Process each document and create chunks
        total_chunks_created = 0
        documents_processed = 0
        chunks_to_upload = []

        print(f"\n⚙️  Processing documents and creating chunks...")
        print("-" * 70)

        for parent_id, doc in parent_docs.items():
            # Get content
            content = doc.get("merged_content", "")
            if not content:
                content = doc.get("content", "")
            
            if isinstance(content, list):
                content = " ".join(_as_clean_str(x) for x in content)
            
            content = _as_clean_str(content)
            
            if not content:
                filename = extract_filename(doc)
                print(f"  ⚠️  Skipping {filename}: No content")
                continue

            filename = extract_filename(doc)
            documents_processed += 1

            # Split into chunks
            chunks = chunk_text(content)
            total_chunks_created += len(chunks)

            print(f"\n  [{documents_processed}] Processing: {filename}")
            print(f"      Document length: {len(content)} chars")
            print(f"      Created {len(chunks)} chunks")

            # Process each chunk
            for chunk_num, chunk_content in enumerate(chunks):
                # Generate embedding for this chunk
                embedding = embedding_service.generate_embedding(chunk_content)

                # Create chunk document
                chunk_id = generate_chunk_id(parent_id, chunk_num)
                
                chunk_doc = {
                    "chunk_id": chunk_id,
                    "parent_id": parent_id,
                    "chunk_number": chunk_num,
                    "title": doc.get("title") or filename,
                    "content": chunk_content,
                    "merged_content": chunk_content,  # Store chunk content
                    "filepath": doc.get("filepath"),
                    "url": doc.get("url"),
                    "metadata_storage_name": doc.get("metadata_storage_name"),
                    "metadata_storage_path": doc.get("metadata_storage_path"),
                    "metadata_storage_content_type": doc.get("metadata_storage_content_type"),
                    "content_vector": embedding
                }
                
                chunks_to_upload.append(chunk_doc)

                # Upload in batches of 50
                if len(chunks_to_upload) >= 50:
                    print(f"      📤 Uploading batch of {len(chunks_to_upload)} chunks...")
                    try:
                        search_client.upload_documents(documents=chunks_to_upload)
                        print(f"      ✅ Batch uploaded")
                    except Exception as batch_error:
                        print(f"      ❌ Batch error: {batch_error}")
                        # Try one by one
                        for single_doc in chunks_to_upload:
                            try:
                                search_client.upload_documents(documents=[single_doc])
                            except Exception as doc_error:
                                print(f"        ❌ Failed chunk: {doc_error}")
                    
                    chunks_to_upload = []

        # Upload remaining chunks
        if chunks_to_upload:
            print(f"\n  📤 Uploading final batch of {len(chunks_to_upload)} chunks...")
            try:
                search_client.upload_documents(documents=chunks_to_upload)
                print(f"  ✅ Final batch uploaded")
            except Exception as batch_error:
                print(f"  ❌ Final batch error: {batch_error}")

        # Summary
        print("\n" + "=" * 70)
        print("✅ CHUNKED EMBEDDING GENERATION COMPLETE!")
        print("=" * 70)
        print(f"📊 Summary:")
        print(f"   ✓ Documents processed: {documents_processed}")
        print(f"   ✓ Total chunks created: {total_chunks_created}")
        print(f"   ✓ Average chunks per document: {total_chunks_created/documents_processed:.1f}")
        print(f"\n🎉 Your index now has {total_chunks_created} searchable chunks!")
        print(f"   Each chunk is ~{CHUNK_SIZE} characters")
        print(f"   Model: {config.AZURE_OPENAI_EMBEDDING_MODEL}")
        print(f"   Dimensions: {config.EMBEDDING_DIMENSIONS}")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(generate_embeddings_for_all_documents())