# backend/scripts/debug_index_contents.py
import asyncio
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

async def debug_index():
    search_client = SearchClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        index_name=config.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY)
    )
    
    results = search_client.search(search_text="*", top=5)
    
    print("📋 First 5 documents in index:\n")
    for i, result in enumerate(results, 1):
        r = dict(result)
        print(f"Document {i}:")
        print(f"  Available fields: {list(r.keys())}")
        print(f"  chunk_id: {r.get('chunk_id', 'N/A')[:80]}...")
        print(f"  metadata_storage_name: {r.get('metadata_storage_name', 'N/A')}")
        print(f"  title: {r.get('title', 'N/A')}")
        print(f"  content (first 100 chars): {str(r.get('content', ''))[:100]}...")
        print()

if __name__ == "__main__":
    asyncio.run(debug_index())