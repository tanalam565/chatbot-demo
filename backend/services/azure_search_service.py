from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexerClient
from azure.core.credentials import AzureKeyCredential
from typing import List, Dict
import config

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
        
        print(f"✓ Connected to existing index: {self.index_name}")
    
    async def search(self, query: str, top: int = config.MAX_SEARCH_RESULTS) -> List[Dict]:
        """Search indexed documents"""
        try:
            print(f"Searching for: '{query}' in index '{self.index_name}'")
            
            results = self.search_client.search(
                search_text=query,
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
                
                # Extract identifiers
                filepath = result_dict.get("filepath", "")
                title = result_dict.get("title", "")
                chunk_id = result_dict.get("chunk_id", "")
                parent_id = result_dict.get("parent_id", "")
                url = result_dict.get("url", "")
                
                # Get filename (priority order)
                filename = "Unknown Document"
                
                if filepath:
                    filename = filepath.split('/')[-1] if '/' in filepath else filepath
                    import urllib.parse
                    filename = urllib.parse.unquote(filename)
                elif title:
                    filename = title
                elif url:
                    filename = url.split('/')[-1] if '/' in url else url
                    import urllib.parse
                    filename = urllib.parse.unquote(filename)
                elif chunk_id:
                    # Decode base64 chunk_id to get URL
                    try:
                        import base64
                        import urllib.parse
                        
                        # Clean chunk_id - remove any trailing numbers/characters that break base64
                        clean_chunk_id = chunk_id.rstrip('0123456789')
                        
                        # Add padding if needed for base64
                        missing_padding = len(clean_chunk_id) % 4
                        if missing_padding:
                            clean_chunk_id += '=' * (4 - missing_padding)
                        
                        decoded = base64.b64decode(clean_chunk_id).decode('utf-8')
                        
                        # Extract filename from decoded URL
                        if '/' in decoded:
                            filename = decoded.split('/')[-1]
                            # Remove any trailing characters after .pdf
                            if '.pdf' in filename:
                                filename = filename.split('.pdf')[0] + '.pdf'
                            # URL decode
                            filename = urllib.parse.unquote(filename)
                    except Exception as e:
                        print(f"  ⚠️  Could not decode filename from chunk_id: {e}")
                        filename = "Unknown Document"
                elif parent_id:
                    filename = f"Document (ID: {parent_id})"
                
                score = result_dict.get("@search.score", 0)
                
                if content:
                    print(f"  ✓ Found: {filename} (score: {score:.2f}, {len(str(content))} chars)")
                    search_results.append({
                        "content": str(content)[:5000],
                        "filename": filename,
                        "score": score
                    })
            
            print(f"✓ Total search results: {len(search_results)}")
            return search_results
            
        except Exception as e:
            print(f"❌ Search error: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    async def run_indexer(self):
        """Manually trigger existing indexer"""
        try:
            print(f"Triggering indexer: {self.indexer_name}")
            self.indexer_client.run_indexer(self.indexer_name)
            print(f"✓ Indexer '{self.indexer_name}' started")
            return True
        except Exception as e:
            print(f"❌ Error running indexer: {e}")
            return False
    
    async def get_indexer_status(self):
        """Get indexer execution status"""
        try:
            status = self.indexer_client.get_indexer_status(self.indexer_name)
            
            result = {
                "status": status.status,
                "last_result": status.last_result.status if status.last_result else None,
                "execution_history": []
            }
            
            if status.execution_history:
                for exec in status.execution_history[:5]:
                    result["execution_history"].append({
                        "status": exec.status,
                        "error_message": exec.error_message,
                        "start_time": exec.start_time.isoformat() if exec.start_time else None,
                        "end_time": exec.end_time.isoformat() if exec.end_time else None
                    })
            
            return result
            
        except Exception as e:
            print(f"❌ Error getting indexer status: {e}")
            return {
                "status": "error",
                "last_result": None,
                "execution_history": [],
                "error": str(e)
            }