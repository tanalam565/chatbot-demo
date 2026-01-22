# backend/scripts/check_vectorization_status.py - NEW FILE

import asyncio
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

async def check_vectorization_status():
    """
    Check which documents have embeddings and which don't
    """
    
    print("🔍 Checking vectorization status...")
    print("="*60)
    
    search_client = SearchClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        index_name=config.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY)
    )
    
    try:
        # Get all documents
        results = search_client.search(
            search_text="*", 
            top=1000,
            select=["chunk_id", "metadata_storage_name", "title", "content_vector"]
        )
        
        vectorized_count = 0
        not_vectorized_count = 0
        vectorized_docs = []
        not_vectorized_docs = []
        
        for result in results:
            result_dict = dict(result)
            
            # Get filename
            filename = (
                result_dict.get("metadata_storage_name") or 
                result_dict.get("title") or 
                "Unknown"
            )
            
            # Check if content_vector exists and is not empty
            has_vector = False
            if "content_vector" in result_dict:
                vector = result_dict["content_vector"]
                if vector and len(vector) > 0:
                    # Check if it's not a zero vector
                    if any(v != 0.0 for v in vector):
                        has_vector = True
            
            if has_vector:
                vectorized_count += 1
                vectorized_docs.append(filename)
            else:
                not_vectorized_count += 1
                not_vectorized_docs.append(filename)
        
        # Display results
        total = vectorized_count + not_vectorized_count
        
        print(f"\n📊 VECTORIZATION STATUS:")
        print(f"Total documents: {total}")
        print(f"✅ Vectorized: {vectorized_count} ({vectorized_count/total*100:.1f}%)")
        print(f"❌ Not vectorized: {not_vectorized_count} ({not_vectorized_count/total*100:.1f}%)")
        
        if vectorized_docs:
            print(f"\n✅ VECTORIZED DOCUMENTS ({len(vectorized_docs)}):")
            # Show unique filenames
            unique_vectorized = list(set(vectorized_docs))
            for doc in sorted(unique_vectorized)[:20]:  # Show first 20
                print(f"  ✓ {doc}")
            if len(unique_vectorized) > 20:
                print(f"  ... and {len(unique_vectorized) - 20} more")
        
        if not_vectorized_docs:
            print(f"\n❌ NOT VECTORIZED DOCUMENTS ({len(not_vectorized_docs)}):")
            unique_not_vectorized = list(set(not_vectorized_docs))
            for doc in sorted(unique_not_vectorized):
                print(f"  ✗ {doc}")
        
        if not_vectorized_count > 0:
            print(f"\n⚠️  WARNING: {not_vectorized_count} documents need vectorization!")
            print("Run: python scripts/generate_embeddings_for_existing_documents.py")
        else:
            print(f"\n🎉 All documents are vectorized! Hybrid search is fully operational.")
        
    except Exception as e:
        print(f"❌ Error checking status: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(check_vectorization_status())