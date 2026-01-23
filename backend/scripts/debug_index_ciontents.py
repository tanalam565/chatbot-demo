# backend/scripts/show_indexer_status.py - CORRECTED

from azure.search.documents.indexes import SearchIndexerClient
from azure.core.credentials import AzureKeyCredential
import os, sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

def main():
    client = SearchIndexerClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY)
    )

    status = client.get_indexer_status(config.AZURE_SEARCH_INDEXER_NAME)

    last = status.last_result
    print("\n📌 Indexer:", config.AZURE_SEARCH_INDEXER_NAME)
    if last:
        print("Status:", last.status)
        print("Start:", last.start_time)
        print("End:", last.end_time)
        
        # Print all available attributes to see what exists
        print("\nAvailable attributes:")
        print(dir(last))
        
        # Try common attribute names
        for attr in ['item_count', 'items_count', 'failed_item_count', 'failure_count', 'success_count']:
            if hasattr(last, attr):
                print(f"{attr}: {getattr(last, attr)}")

        if hasattr(last, 'errors') and last.errors:
            print("\n❌ Errors (first 10):")
            for e in last.errors[:10]:
                print("-", e.key if hasattr(e, 'key') else 'unknown', "|", 
                      e.error_message if hasattr(e, 'error_message') else e)

        if hasattr(last, 'warnings') and last.warnings:
            print("\n⚠️ Warnings (first 10):")
            for w in last.warnings[:10]:
                print("-", w.key if hasattr(w, 'key') else 'unknown', "|", 
                      w.message if hasattr(w, 'message') else w)
    else:
        print("No last_result found.")

if __name__ == "__main__":
    main()