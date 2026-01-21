from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.core.credentials import AzureKeyCredential
import base64
import config

class DocumentIntelligenceService:
    def __init__(self):
        self.endpoint = config.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
        self.key = config.AZURE_DOCUMENT_INTELLIGENCE_KEY
        # Use 2024 API version
        self.client = DocumentIntelligenceClient(
            endpoint=self.endpoint,
            credential=AzureKeyCredential(self.key),
            api_version="2024-11-30"
        )
    
    async def extract_text(self, file_content: bytes, filename: str) -> dict:
        try:
            # Encode to base64
            base64_source = base64.b64encode(file_content).decode('utf-8')
            
            # Create analyze request
            analyze_request = AnalyzeDocumentRequest(
                base64_source=base64_source
            )
            
            # Call with 2024 API
            poller = self.client.begin_analyze_document(
                model_id="prebuilt-read",
                analyze_request=analyze_request
            )
            
            result = poller.result()
            
            # Extract text
            full_text = result.content if hasattr(result, 'content') else ""
            page_count = len(result.pages) if hasattr(result, 'pages') else 0
            
            return {
                "text": full_text.strip(),
                "page_count": page_count,
                "filename": filename,
                "success": True
            }
            
        except Exception as e:
            print(f"Error extracting text from {filename}: {e}")
            return {
                "text": "",
                "page_count": 0,
                "filename": filename,
                "success": False,
                "error": str(e)
            }