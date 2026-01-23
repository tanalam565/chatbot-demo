# backend/services/azure_search_service.py - UPDATED (No Scores)

from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexerClient
from azure.search.documents.models import VectorizedQuery
from azure.core.credentials import AzureKeyCredential
from typing import List, Dict
import urllib.parse
import config
from services.embedding_service import EmbeddingService

class AzureSearchService:
    def __init__(self):
        self.endpoint = config.AZURE_SEARCH_ENDPOINT
        self.key = config.AZURE_SEARCH_KEY
        self.index_name = config.AZURE_SEARCH_INDEX_NAME
        self.indexer_name = "azureblob-indexer-yotta"
        
        self.credential = AzureKeyCredential(self.key)
        
        self.search_client = SearchClient(
            endpoint=self.endpoint,
            index_name=self.index_name,
            credential=self.credential
        )
        
        self.indexer_client = SearchIndexerClient(
            endpoint=self.endpoint,
            credential=self.credential
        )
        
        self.embedding_service = EmbeddingService()
        
        print(f"✓ Connected to index: {self.index_name} (Hybrid Search enabled)")

    def _extract_filename(self, result_dict: dict) -> str:
        """Extract filename from search result - handle parent docs and chunks"""
        
        # Try title first
        title = result_dict.get("title")
        if title and title.strip():
            return title
        
        # Try filepath
        filepath = result_dict.get("filepath")
        if filepath and filepath.strip():
            return filepath.split("/")[-1] if "/" in filepath else filepath
        
        # Try parent_id
        parent_id = result_dict.get("parent_id")
        if parent_id and parent_id.strip():
            try:
                parsed = urllib.parse.urlparse(parent_id)
                path = parsed.path
                if '/' in path:
                    filename = path.split('/')[-1]
                    filename = urllib.parse.unquote(filename)
                    if filename:
                        return filename
            except:
                pass
        
        return "Unknown Document"

    async def search(self, query: str, top: int = config.MAX_SEARCH_RESULTS) -> List[Dict]:
        """Perform hybrid search (keyword + vector) on indexed documents"""
        try:
            print(f"Hybrid search for: '{query}' in index '{self.index_name}'")
            
            query_embedding = self.embedding_service.generate_embedding(query)
            
            vector_query = VectorizedQuery(
                vector=query_embedding,
                k_nearest_neighbors=top * 3,
                fields="content_vector"
            )
            
            results = self.search_client.search(
                search_text=query,
                vector_queries=[vector_query],
                top=top * 3,
                include_total_count=True
            )
            
            search_results = []
            for result in results:
                result_dict = dict(result)
                
                content = result_dict.get("content", "")
                if isinstance(content, list):
                    content = " ".join(str(item) for item in content)
                
                filename = self._extract_filename(result_dict)
                
                # Skip chunks with no identifiable filename
                if filename == "Unknown Document":
                    print(f"  ⚠️  Skipping chunk with no filename")
                    continue
                
                if content:
                    search_results.append({
                        "content": str(content)[:5000],
                        "filename": filename,
                        "source_type": "company"
                    })
                    print(f"  ✓ Found: {filename}")
                
                if len(search_results) >= top:
                    break
            
            print(f"✓ Hybrid search returned {len(search_results)} results")
            return search_results
            
        except Exception as e:
            print(f"❌ Hybrid search error: {e}")
            import traceback
            traceback.print_exc()
            return await self._fallback_keyword_search(query, top)
    
    async def _fallback_keyword_search(self, query: str, top: int) -> List[Dict]:
        """Fallback to keyword-only search if hybrid search fails"""
        try:
            results = self.search_client.search(
                search_text=query,
                top=top * 2,
                include_total_count=True
            )
            
            search_results = []
            for result in results:
                result_dict = dict(result)
                content = result_dict.get("content", "")
                if isinstance(content, list):
                    content = " ".join(str(item) for item in content)
                
                filename = self._extract_filename(result_dict)
                
                # Skip unknown documents in fallback too
                if filename == "Unknown Document":
                    continue
                
                if content:
                    search_results.append({
                        "content": str(content)[:5000],
                        "filename": filename,
                        "source_type": "company"
                    })
                
                if len(search_results) >= top:
                    break
            
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