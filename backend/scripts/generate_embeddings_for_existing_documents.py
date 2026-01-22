# backend/scripts/generate_embeddings_for_existing_documents.py - FULL UPDATED CODE

import asyncio
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from services.embedding_service import EmbeddingService

# backend/scripts/generate_embeddings_for_existing_documents.py
# Update extract_filename function:

def extract_filename(result_dict):
    """Extract filename - handle both parent docs and child chunks"""
    
    # Try title FIRST
    title = result_dict.get("title")
    if title and title.strip():
        return title
    
    # Try filepath
    filepath = result_dict.get("filepath")
    if filepath and filepath.strip():
        return filepath.split("/")[-1] if "/" in filepath else filepath
    
    # Extract from parent_id (for chunks)
    parent_id = result_dict.get("parent_id")
    if parent_id and parent_id.strip():
        try:
            import urllib.parse
            # Parse URL from parent_id
            parsed = urllib.parse.urlparse(parent_id)
            path = parsed.path
            if '/' in path:
                filename = path.split('/')[-1]
                filename = urllib.parse.unquote(filename)
                if filename:
                    return filename  # ✅ Return any filename, not just specific extensions
        except:
            pass
    
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
        # Get first document to identify key field
        print(f"Fetching documents from index: {config.AZURE_SEARCH_INDEX_NAME}")
        results = search_client.search(search_text="*", top=1000)
        
        first_result = None
        for result in results:
            first_result = dict(result)
            break
        
        if not first_result:
            print("❌ No documents found in index")
            return
        
        # Find key field
        key_field = None
        possible_keys = ['chunk_id', 'metadata_storage_path', 'id', 'document_id', 'key']
        
        for possible_key in possible_keys:
            if possible_key in first_result:
                key_field = possible_key
                print(f"✓ Found key field: {key_field}")
                break
        
        if not key_field:
            print(f"❌ Could not identify key field. Available fields: {list(first_result.keys())}")
            return
        
        # Process all documents
        print(f"Re-fetching all documents...")
        results = search_client.search(search_text="*", top=1000)
        
        documents_to_update = []
        count = 0
        unknown_count = 0
        
        for result in results:
            count += 1
            result_dict = dict(result)
            
            # Get content
            content = result_dict.get("content", "")
            if isinstance(content, list):
                content = " ".join(str(item) for item in content)
            
            if not content:
                print(f"  ⚠️  Skipping document {count} - no content")
                continue
            
            # Get key value
            key_value = result_dict.get(key_field)
            if not key_value:
                print(f"  ⚠️  Skipping document {count} - no key value")
                continue
            
            # Extract filename
            filename = extract_filename(result_dict)
            
            if filename == "Unknown Document":
                unknown_count += 1
            
            # Generate embedding
            print(f"  Processing document {count}: {filename[:60]}...")
            embedding = embedding_service.generate_embedding(str(content)[:32000])
            
            # Verify embedding dimensions
            if len(embedding) != config.EMBEDDING_DIMENSIONS:
                print(f"    ⚠️  Warning: Expected {config.EMBEDDING_DIMENSIONS} dimensions, got {len(embedding)}")
            
            # Prepare document update
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
                    print(f"  ✅ Batch uploaded successfully")
                except Exception as batch_error:
                    print(f"  ❌ Batch upload error: {batch_error}")
                    # Try uploading one by one
                    for doc in documents_to_update:
                        try:
                            search_client.merge_or_upload_documents(documents=[doc])
                        except Exception as doc_error:
                            print(f"    ❌ Failed to upload doc: {doc_error}")
                
                documents_to_update = []
        
        # Upload remaining documents
        if documents_to_update:
            print(f"  📤 Uploading final batch of {len(documents_to_update)} embeddings...")
            try:
                search_client.merge_or_upload_documents(documents=documents_to_update)
                print(f"  ✅ Final batch uploaded successfully")
            except Exception as batch_error:
                print(f"  ❌ Final batch upload error: {batch_error}")
                # Try uploading one by one
                for doc in documents_to_update:
                    try:
                        search_client.merge_or_upload_documents(documents=[doc])
                    except Exception as doc_error:
                        print(f"    ❌ Failed to upload doc: {doc_error}")
        
        print(f"\n" + "="*60)
        print(f"✅ Successfully processed {count} documents!")
        if unknown_count > 0:
            print(f"⚠️  {unknown_count} documents could not extract filename (but embeddings were generated)")
        print(f"🎉 Hybrid search is now fully operational!")
        print(f"="*60)
        
    except Exception as e:
        print(f"❌ Error generating embeddings: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(generate_embeddings_for_all_documents())