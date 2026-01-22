# backend/services/azure_search_service.py - FULL UPDATED CODE

from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexerClient
from azure.search.documents.models import VectorizedQuery
from azure.core.credentials import AzureKeyCredential
from typing import List, Dict
import config
from services.embedding_service import EmbeddingService

class AzureSearchService:
    def __init__(self):
        self.endpoint = config.AZURE_SEARCH_ENDPOINT
        self.key = config.AZURE_SEARCH_KEY
        self.index_name = config.AZURE_SEARCH_INDEX_NAME
        self.indexer_name = "azureblob-indexer-yotta"
        
        self.credential = AzureKeyCredential(self.key)
        
        # Search client for querying
        self.search_client = SearchClient(
            endpoint=self.endpoint,
            index_name=self.index_name,
            credential=self.credential
        )
        
        # Indexer client for management
        self.indexer_client = SearchIndexerClient(
            endpoint=self.endpoint,
            credential=self.credential
        )
        
        # Embedding service for vector search
        self.embedding_service = EmbeddingService()
        
        print(f"✓ Connected to index: {self.index_name} (Hybrid Search enabled)")

# backend/services/azure_search_service.py - Update the search method

    async def search(self, query: str, top: int = config.MAX_SEARCH_RESULTS) -> List[Dict]:
        """
        Perform hybrid search (keyword + vector) on indexed documents
        """
        try:
            print(f"Hybrid search for: '{query}' in index '{self.index_name}'")
            
            # Generate embedding for the query
            query_embedding = self.embedding_service.generate_embedding(query)
            
            # Create vector query
            vector_query = VectorizedQuery(
                vector=query_embedding,
                k_nearest_neighbors=top * 2,
                fields="content_vector"
            )
            
            # Perform hybrid search
            results = self.search_client.search(
                search_text=query,
                vector_queries=[vector_query],
                top=top,
                include_total_count=True
            )
            
            search_results = []
            for result in results:
                result_dict = dict(result)
                
                # Extract content
                content = result_dict.get("content", "")
                if isinstance(content, list):
                    content = " ".join(str(item) for item in content)
                
                # Extract filename - try ALL possible fields
                filename = None
                
                # Try metadata_storage_name first (most common)
                if result_dict.get("metadata_storage_name"):
                    filename = result_dict.get("metadata_storage_name")
                
                # Try title
                elif result_dict.get("title"):
                    filename = result_dict.get("title")
                
                # Try filepath
                elif result_dict.get("filepath"):
                    filepath = result_dict.get("filepath")
                    filename = filepath.split("/")[-1] if "/" in filepath else filepath
                
                # Try to decode chunk_id (base64 encoded URL)
                elif result_dict.get("chunk_id"):
                    chunk_id = result_dict.get("chunk_id")
                    try:
                        import base64
                        decoded = base64.b64decode(chunk_id).decode('utf-8', errors='ignore')
                        # Extract filename from URL in chunk_id
                        if '/' in decoded:
                            parts = decoded.split('/')
                            for part in reversed(parts):
                                if any(ext in part.lower() for ext in ['.pdf', '.png', '.jpg', '.jpeg', '.docx', '.txt']):
                                    # URL decode the filename
                                    import urllib.parse
                                    filename = urllib.parse.unquote(part)
                                    break
                    except:
                        pass
                
                # If still no filename, use "Unknown Document"
                if not filename:
                    filename = "Unknown Document"
                
                # Get hybrid search score
                score = result_dict.get("@search.score", 0)
                
                # Get reranker score if available (better)
                reranker_score = result_dict.get("@search.reranker_score")
                if reranker_score:
                    score = reranker_score
                
                if content:
                    search_results.append({
                        "content": str(content)[:5000],
                        "filename": filename,
                        "score": score,
                        "source_type": "company"
                    })
                    print(f"  ✓ Found: {filename} (score: {score:.2f})")
            
            print(f"✓ Hybrid search returned {len(search_results)} results")
            return search_results
            
        except Exception as e:
            print(f"❌ Hybrid search error: {e}")
            import traceback
            traceback.print_exc()
            return await self._fallback_keyword_search(query, top)
    
    async def _fallback_keyword_search(self, query: str, top: int) -> List[Dict]:
        """
        Fallback to keyword-only search if hybrid search fails
        """
        try:
            results = self.search_client.search(
                search_text=query,
                top=top,
                include_total_count=True
            )
            
            search_results = []
            for result in results:
                result_dict = dict(result)
                content = result_dict.get("content", "")
                if isinstance(content, list):
                    content = " ".join(str(item) for item in content)
                
                filename = (
                    result_dict.get("metadata_storage_name") or
                    result_dict.get("title") or
                    "Unknown Document"
                )
                
                score = result_dict.get("@search.score", 0)
                
                if content:
                    search_results.append({
                        "content": str(content)[:5000],
                        "filename": filename,
                        "score": score,
                        "source_type": "company"
                    })
            
            print(f"✓ Keyword search returned {len(search_results)} results")
            return search_results
            
        except Exception as e:
            print(f"❌ Fallback search error: {e}")
            return []
    
    async def get_indexer_status(self):
        """Get status of the Azure Search indexer"""
        try:
            status = self.indexer_client.get_indexer_status(self.indexer_name)
            return {
                "name": status.name,
                "status": status.status,
                "last_result": {
                    "status": status.last_result.status if status.last_result else None,
                    "error_message": status.last_result.error_message if status.last_result else None
                }
            }
        except Exception as e:
            print(f"Error getting indexer status: {e}")
            return {"error": str(e)}
    
    async def run_indexer(self):
        """Manually trigger the indexer to process new documents"""
        try:
            self.indexer_client.run_indexer(self.indexer_name)
            print(f"✓ Indexer '{self.indexer_name}' triggered successfully")
            return True
        except Exception as e:
            print(f"❌ Error running indexer: {e}")
            return False