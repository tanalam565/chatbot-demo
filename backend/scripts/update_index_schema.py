# backend/scripts/update_index_schema.py - Updated for text-embedding-3-large

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

def update_index_with_vector_field():
    """
    Update existing Azure Search index to add vector field for hybrid search
    Using text-embedding-3-large with 1536 dimensions
    """
    
    print("Connecting to Azure Search...")
    client = SearchIndexClient(
        endpoint=config.AZURE_SEARCH_ENDPOINT,
        credential=AzureKeyCredential(config.AZURE_SEARCH_KEY)
    )
    
    try:
        # Get existing index
        print(f"Fetching existing index: {config.AZURE_SEARCH_INDEX_NAME}")
        existing_index = client.get_index(config.AZURE_SEARCH_INDEX_NAME)
        
        # Check if vector field already exists
        has_vector_field = any(field.name == "content_vector" for field in existing_index.fields)
        
        if has_vector_field:
            print("⚠️  Vector field already exists. Checking dimensions...")
            for field in existing_index.fields:
                if field.name == "content_vector":
                    if hasattr(field, 'vector_search_dimensions'):
                        current_dims = field.vector_search_dimensions
                        if current_dims == 1536:
                            print("✓ Vector field already configured correctly with 1536 dimensions!")
                            return
                        else:
                            print(f"⚠️  Vector field has {current_dims} dimensions, needs update to 1536")
                            # Remove old field
                            existing_index.fields = [f for f in existing_index.fields if f.name != "content_vector"]
                            break
        
        print("Adding vector field to index (1536 dimensions for text-embedding-3-large)...")
        
        # Add vector field with 1536 dimensions
        vector_field = SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=1536,  # text-embedding-3-large dimensions
            vector_search_profile_name="my-vector-profile"
        )
        
        existing_index.fields.append(vector_field)
        
        # Configure vector search with optimized parameters for larger dimensions
        existing_index.vector_search = VectorSearch(
            algorithms=[
                HnswAlgorithmConfiguration(
                    name="my-hnsw-config",
                    parameters={
                        "m": 4,  # Number of bi-directional links
                        "ef_construction": 400,  # Ef construction
                        "ef_search": 500,  # Ef search
                        "metric": "cosine"  # Similarity metric
                    }
                )
            ],
            profiles=[
                VectorSearchProfile(
                    name="my-vector-profile",
                    algorithm_configuration_name="my-hnsw-config"
                )
            ]
        )
        
        # Update the index
        print("Updating index schema...")
        client.create_or_update_index(existing_index)
        
        print("✅ Index updated successfully with vector field (1536 dimensions)!")
        print("\n⚠️  IMPORTANT: You need to reindex your documents to populate embeddings.")
        print("Run: python scripts/generate_embeddings_for_existing_docs.py")
        
    except Exception as e:
        print(f"❌ Error updating index: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    update_index_with_vector_field()