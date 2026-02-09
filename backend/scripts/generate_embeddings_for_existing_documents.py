# backend/scripts/generate_embeddings_from_blob_storage.py - READ FROM BLOB, NOT INDEX

import asyncio
from azure.storage.blob import BlobServiceClient
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
import sys
import os
import base64
import hashlib

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from services.embedding_service import EmbeddingService


# CHUNKING CONFIGURATION
CHUNK_SIZE = 1000  # characters per chunk
CHUNK_OVERLAP = 200  # overlap between chunks


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list:
    """Split text into overlapping chunks"""
    if not text or len(text) <= chunk_size:
        return [text] if text else []
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # If not the last chunk, try to break at sentence/word boundary
        if end < len(text):
            # Look for sentence end (. ! ?)
            for i in range(end, max(start + chunk_size - 200, start), -1):
                if text[i] in '.!?\n':
                    end = i + 1
                    break
            else:
                # No sentence boundary, look for space
                for i in range(end, max(start + chunk_size - 100, start), -1):
                    if text[i] == ' ':
                        end = i
                        break
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap if end < len(text) else end
    
    return chunks


def generate_chunk_id(parent_id: str, chunk_number: int) -> str:
    """Generate unique chunk ID"""
    combined = f"{parent_id}_chunk_{chunk_number}"
    return base64.b64encode(combined.encode()).decode()


async def extract_text_from_blob(blob_client, filename: str, doc_intelligence_client) -> dict:
    """Download blob and extract text using Document Intelligence"""
    try:
        print(f"   📥 Downloading {filename}...")
        blob_data = blob_client.download_blob().readall()
        
        print(f"   📄 Extracting text (size: {len(blob_data)} bytes)...")
        
        # Encode to base64
        base64_source = base64.b64encode(blob_data).decode('utf-8')
        
        # Create analyze request
        analyze_request = AnalyzeDocumentRequest(
            base64_source=base64_source
        )
        
        # Call Document Intelligence
        poller = doc_intelligence_client.begin_analyze_document(
            model_id="prebuilt-read",
            analyze_request=analyze_request
        )
        
        result = poller.result()
        
        # Extract full text
        full_text = result.content if hasattr(result, 'content') else ""
        page_count = len(result.pages) if hasattr(result, 'pages') else 0
        
        print(f"   ✅ Extracted {len(full_text)} characters from {page_count} pages")
        
        return {
            "text": full_text.strip(),
            "page_count": page_count,
            "success": True
        }
        
    except Exception as e:
        print(f"   ❌ Extraction error: {e}")
        return {
            "text": "",
            "page_count": 0,
            "success": False,
            "error": str(e)
        }


async def generate_embeddings_from_blob_storage():
    """
    Generate embeddings by reading full documents from blob storage
    (not from truncated search index content)
    """

    print("=" * 70)
    print("🚀 Starting Full Document Embedding Generation from Blob Storage")
    print("=" * 70)
    print(f"📏 Chunk size: {CHUNK_SIZE} characters")
    print(f"🔗 Chunk overlap: {CHUNK_OVERLAP} characters")
    print(f"📦 Reading from: {config.AZURE_STORAGE_CONTAINER_NAME}")

    # Initialize services
    embedding_service = EmbeddingService()
    
    search_client = SearchClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        index_name=config.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY)
    )
    
    blob_service = BlobServiceClient.from_connection_string(
        config.AZURE_STORAGE_CONNECTION_STRING
    )
    container_client = blob_service.get_container_client(
        config.AZURE_STORAGE_CONTAINER_NAME
    )
    
    doc_intelligence_client = DocumentIntelligenceClient(
        endpoint=config.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT,
        credential=AzureKeyCredential(config.AZURE_DOCUMENT_INTELLIGENCE_KEY),
        api_version="2024-11-30"
    )

    try:
        # Clear existing index
        print(f"\n🗑️  Clearing existing index...")
        
        existing_results = search_client.search(
            search_text="*",
            select=["chunk_id"],
            top=10000
        )
        
        existing_ids = [dict(r)["chunk_id"] for r in existing_results]
        
        if existing_ids:
            print(f"   Found {len(existing_ids)} existing entries to delete...")
            batch_size = 1000
            for i in range(0, len(existing_ids), batch_size):
                batch = existing_ids[i:i+batch_size]
                docs_to_delete = [{"chunk_id": doc_id} for doc_id in batch]
                search_client.delete_documents(documents=docs_to_delete)
                print(f"   Deleted {min(i+batch_size, len(existing_ids))}/{len(existing_ids)}")
            print(f"   ✅ Index cleared")
        else:
            print(f"   Index is empty")

        # List all blobs in container
        print(f"\n📥 Listing files in blob storage...")
        
        blobs = list(container_client.list_blobs())
        pdf_blobs = [b for b in blobs if b.name.lower().endswith('.pdf')]
        
        print(f"✓ Found {len(pdf_blobs)} PDF files")

        # Process each blob
        total_chunks_created = 0
        documents_processed = 0
        chunks_to_upload = []

        print(f"\n⚙️  Processing PDFs and creating chunks...")
        print("-" * 70)

        for blob_info in pdf_blobs:
            blob_name = blob_info.name
            documents_processed += 1
            
            print(f"\n  [{documents_processed}/{len(pdf_blobs)}] Processing: {blob_name}")
            
            # Get blob client
            blob_client = container_client.get_blob_client(blob_name)
            
            # Extract full text from blob
            extraction_result = await extract_text_from_blob(
                blob_client, 
                blob_name,
                doc_intelligence_client
            )
            
            if not extraction_result['success'] or not extraction_result['text']:
                print(f"   ⚠️  Skipping: No text extracted")
                continue
            
            full_text = extraction_result['text']
            page_count = extraction_result['page_count']
            
            # Generate parent_id from blob name
            parent_id = f"blob://{config.AZURE_STORAGE_CONTAINER_NAME}/{blob_name}"
            
            # Split into chunks
            chunks = chunk_text(full_text)
            total_chunks_created += len(chunks)

            print(f"   📄 Document: {len(full_text)} chars, {page_count} pages")
            print(f"   ✂️  Created {len(chunks)} chunks")

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
                    "title": blob_name,
                    "content": chunk_content,
                    "merged_content": chunk_content,
                    "filepath": blob_name,
                    "url": f"https://{blob_service.account_name}.blob.core.windows.net/{config.AZURE_STORAGE_CONTAINER_NAME}/{blob_name}",
                    "metadata_storage_name": blob_name,
                    "metadata_storage_path": parent_id,
                    "metadata_storage_content_type": "application/pdf",
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
        print("✅ FULL DOCUMENT EMBEDDING GENERATION COMPLETE!")
        print("=" * 70)
        print(f"📊 Summary:")
        print(f"   ✓ PDF files processed: {documents_processed}")
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
    asyncio.run(generate_embeddings_from_blob_storage())