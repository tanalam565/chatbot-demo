# backend/scripts/list_documents.py

import asyncio
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

async def list_all_documents():
    search_client = SearchClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        index_name=config.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY)
    )
    
    results = search_client.search(search_text="*", top=1000, select=["title", "parent_id"])
    
    # Collect unique document names
    documents = set()
    
    for result in results:
        r = dict(result)
        title = r.get("title")
        
        if title:
            documents.add(title)
        else:
            # Extract from parent_id if no title
            parent_id = r.get("parent_id")
            if parent_id:
                try:
                    import urllib.parse
                    parsed = urllib.parse.urlparse(parent_id)
                    filename = parsed.path.split('/')[-1]
                    filename = urllib.parse.unquote(filename)
                    if filename:
                        documents.add(filename)
                except:
                    pass
    
    print(f"\n📚 Found {len(documents)} unique documents:\n")
    for i, doc in enumerate(sorted(documents), 1):
        print(f"{i}. {doc}")

if __name__ == "__main__":
    asyncio.run(list_all_documents())