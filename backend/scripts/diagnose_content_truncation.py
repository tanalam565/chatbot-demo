# backend/scripts/diagnose_content_truncation.py
# This script compares blob storage content vs search index content

import asyncio
from azure.storage.blob import BlobServiceClient
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


async def diagnose_content_truncation():
    """
    Compare what's in blob storage vs what's in the search index
    to identify truncation issues
    """
    
    print("=" * 70)
    print("🔍 Content Truncation Diagnostic")
    print("=" * 70)
    
    # Connect to blob storage
    blob_service = BlobServiceClient.from_connection_string(
        config.AZURE_STORAGE_CONNECTION_STRING
    )
    container_client = blob_service.get_container_client(
        config.AZURE_STORAGE_CONTAINER_NAME
    )
    
    # Connect to search index
    search_client = SearchClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        index_name=config.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY)
    )
    
    print(f"\n📦 Blob Storage: {config.AZURE_STORAGE_CONTAINER_NAME}")
    print(f"🔎 Search Index: {config.AZURE_SEARCH_INDEX_NAME}")
    
    # List all PDFs in blob storage
    print(f"\n📥 Analyzing blob storage files...")
    blobs = list(container_client.list_blobs())
    pdf_blobs = [b for b in blobs if b.name.lower().endswith('.pdf')]
    
    print(f"   Found {len(pdf_blobs)} PDF files\n")
    
    # For each blob, compare with search index
    print("-" * 70)
    print(f"{'FILE NAME':<50} {'BLOB SIZE':<12} {'INDEX SIZE':<12} {'COVERAGE'}")
    print("-" * 70)
    
    total_blob_size = 0
    total_index_size = 0
    
    for blob_info in pdf_blobs:
        blob_name = blob_info.name
        blob_size = blob_info.size
        total_blob_size += blob_size
        
        # Search for this file in the index
        search_results = search_client.search(
            search_text="*",
            filter=f"metadata_storage_name eq '{blob_name}'",
            select=["content", "merged_content"],
            top=1000
        )
        
        # Collect all content from all chunks
        index_content = []
        for result in search_results:
            r = dict(result)
            content = r.get("merged_content") or r.get("content") or ""
            if isinstance(content, list):
                content = " ".join(str(x) for x in content)
            index_content.append(str(content))
        
        index_size = sum(len(c) for c in index_content)
        total_index_size += index_size
        
        # Calculate coverage
        if blob_size > 0:
            # Rough estimate: 1 byte ≈ 0.5 chars for text content
            estimated_text_size = blob_size * 0.5
            coverage = (index_size / estimated_text_size) * 100
        else:
            coverage = 0
        
        # Color code based on coverage
        if coverage < 20:
            status = "🔴"
        elif coverage < 50:
            status = "🟡"
        else:
            status = "🟢"
        
        # Truncate filename for display
        display_name = blob_name[:47] + "..." if len(blob_name) > 50 else blob_name
        
        print(f"{display_name:<50} {blob_size:>10}b  {index_size:>10}c  {status} {coverage:>5.1f}%")
    
    print("-" * 70)
    print(f"\n📊 Summary:")
    print(f"   Total blob storage: {total_blob_size:,} bytes")
    print(f"   Total index content: {total_index_size:,} characters")
    print(f"   Estimated coverage: {(total_index_size / (total_blob_size * 0.5)) * 100:.1f}%")
    
    print(f"\n🔴 Red: <20% coverage (CRITICAL - most content missing)")
    print(f"🟡 Yellow: 20-50% coverage (WARNING - significant content missing)")  
    print(f"🟢 Green: >50% coverage (GOOD - reasonable coverage)")
    
    print("\n" + "=" * 70)
    print("💡 If you see red/yellow indicators:")
    print("   → Run generate_embeddings_from_blob_storage.py")
    print("   → This will index the FULL content of each PDF")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(diagnose_content_truncation())