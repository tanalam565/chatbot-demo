# backend/scripts/generate_embeddings_for_existing_documents.py - FIXED VERSION

import asyncio
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from services.embedding_service import EmbeddingService

async def generate_embeddings_for_all_documents():
    """
    Generate embeddings for all documents in the search index
    """
    
    print("🚀 Starting embedding generation for existing documents...")
    
    # Initialize services
    embedding_service = EmbeddingService()
    
    search_client = SearchClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        index_name=config.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY)
    )
    
    try:
        # Get all documents from index
        print(f"Fetching documents from index: {config.AZURE_SEARCH_INDEX_NAME}")
        results = search_client.search(search_text="*", top=1000)
        
        # First, let's identify the key field
        first_result = None
        for result in results:
            first_result = dict(result)
            break
        
        if not first_result:
            print("❌ No documents found in index")
            return
        
        # Find the key field (look for common key field names)
        key_field = None
        possible_keys = ['metadata_storage_path', 'chunk_id', 'id', 'document_id', 'key']
        
        for possible_key in possible_keys:
            if possible_key in first_result:
                key_field = possible_key
                print(f"✓ Found key field: {key_field}")
                break
        
        if not key_field:
            print(f"❌ Could not identify key field. Available fields: {list(first_result.keys())}")
            return
        
        # Now process all documents
        print(f"Re-fetching all documents...")
        results = search_client.search(search_text="*", top=1000)
        
        documents_to_update = []
        count = 0
        
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
            
            # Generate embedding
            print(f"  Processing document {count}: {result_dict.get('metadata_storage_name', 'Unknown')[:50]}...")
            embedding = embedding_service.generate_embedding(str(content)[:32000])
            
            # Prepare document update using the correct key field
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
        
        print(f"\n✅ Successfully processed {count} documents!")
        print("🎉 Hybrid search is now fully operational!")
        
    except Exception as e:
        print(f"❌ Error generating embeddings: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(generate_embeddings_for_all_documents())