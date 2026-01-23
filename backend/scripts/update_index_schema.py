# backend/scripts/update_index_schema.py - Updated for 3072 dimensions

from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SearchField,
    SearchFieldDataType,
    VectorSearch,
    VectorSearchProfile,
    HnswAlgorithmConfiguration,
)
from azure.core.credentials import AzureKeyCredential
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

def update_vector_dimensions():
    """
    Update vector field dimensions from 1536 to 3072
    WARNING: This will DELETE the existing index and recreate it!
    You'll need to re-run the indexer and regenerate embeddings.
    """
    
    print("="*70)
    print("⚠️  UPDATING VECTOR DIMENSIONS TO 3072")
    print("="*70)
    print("\n⚠️  WARNING: This will:")
    print("   1. Delete your existing index")
    print("   2. Create a new index with 3072 dimensions")
    print("   3. You'll need to re-run the indexer")
    print("   4. You'll need to regenerate all embeddings")
    print("\nℹ️  Your blob storage files are safe - only the search index is affected")
    
    response = input("\nContinue? (yes/no): ")
    if response.lower() != 'yes':
        print("❌ Aborted")
        return
    
    print("\n🔧 Connecting to Azure Search...")
    client = SearchIndexClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY)
    )
    
    try:
        # Delete existing index
        print(f"\n🗑️  Deleting existing index: {config.AZURE_SEARCH_INDEX_NAME}")
        try:
            client.delete_index(config.AZURE_SEARCH_INDEX_NAME)
            print("✓ Index deleted")
        except Exception as e:
            print(f"ℹ️  Index not found or already deleted: {e}")
        
        # Create new index with 3072 dimensions
        print(f"\n📋 Creating new index with 3072 dimensions...")
        
        fields = [
            SearchField(
                name="chunk_id",
                type=SearchFieldDataType.String,
                key=True,
                searchable=False,
                filterable=True,
                retrievable=True,
                sortable=False,
                facetable=False
            ),
            SearchField(
                name="parent_id",
                type=SearchFieldDataType.String,
                searchable=True,
                filterable=True,
                retrievable=True,
                sortable=False,
                facetable=True
            ),
            SearchField(
                name="title",
                type=SearchFieldDataType.String,
                searchable=True,
                filterable=True,
                retrievable=True,
                sortable=True,
                facetable=True
            ),
            SearchField(
                name="content",
                type=SearchFieldDataType.String,
                searchable=True,
                filterable=False,
                retrievable=True,
                sortable=False,
                facetable=False,
                analyzer_name="en.microsoft"
            ),
            SearchField(
                name="merged_content",
                type=SearchFieldDataType.String,
                searchable=True,
                filterable=False,
                retrievable=True,
                sortable=False,
                facetable=False,
                analyzer_name="en.microsoft"
            ),
            SearchField(
                name="filepath",
                type=SearchFieldDataType.String,
                searchable=True,
                filterable=True,
                retrievable=True,
                sortable=False,
                facetable=True
            ),
            SearchField(
                name="url",
                type=SearchFieldDataType.String,
                searchable=True,
                filterable=True,
                retrievable=True,
                sortable=False,
                facetable=False
            ),
            SearchField(
                name="metadata_storage_name",
                type=SearchFieldDataType.String,
                searchable=False,
                filterable=True,
                retrievable=True,
                sortable=False,
                facetable=True
            ),
            SearchField(
                name="metadata_storage_path",
                type=SearchFieldDataType.String,
                searchable=False,
                filterable=True,
                retrievable=True,
                sortable=False,
                facetable=False
            ),
            SearchField(
                name="metadata_storage_content_type",
                type=SearchFieldDataType.String,
                searchable=False,
                filterable=True,
                retrievable=True,
                sortable=False,
                facetable=True
            ),
            SearchField(
                name="content_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                filterable=False,
                retrievable=True,
                sortable=False,
                facetable=False,
                vector_search_dimensions=3072,  # ← Updated to 3072
                vector_search_profile_name="vector-profile"
            ),
        ]
        
        # Vector search configuration
        vector_search = VectorSearch(
            algorithms=[
                HnswAlgorithmConfiguration(
                    name="hnsw-config",
                    parameters={
                        "m": 4,
                        "ef_construction": 400,
                        "ef_search": 500,
                        "metric": "cosine"
                    }
                )
            ],
            profiles=[
                VectorSearchProfile(
                    name="vector-profile",
                    algorithm_configuration_name="hnsw-config"
                )
            ]
        )
        
        # Create index
        index = SearchIndex(
            name=config.AZURE_SEARCH_INDEX_NAME,
            fields=fields,
            vector_search=vector_search
        )
        
        client.create_or_update_index(index)
        print(f"✓ Created index: {config.AZURE_SEARCH_INDEX_NAME}")
        
        print("\n" + "="*70)
        print("✅ Index updated successfully with 3072 dimensions!")
        print("="*70)
        print("\n📌 Next Steps:")
        print("   1. Update config.py:")
        print("      EMBEDDING_DIMENSIONS = 3072")
        print("\n   2. Re-run indexer to populate text fields:")
        print("      Go to Azure Portal → Indexers → azureblob-indexer-yotta → Run")
        print("      (Wait 2-3 minutes)")
        print("\n   3. Generate embeddings with new dimensions:")
        print("      python scripts/generate_embeddings_for_existing_documents.py")
        print("\n   4. Verify:")
        print("      python scripts/list_docments.py")
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    update_vector_dimensions()