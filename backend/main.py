from fastapi import FastAPI, HTTPException, Security, Depends, UploadFile, File, Form
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
import uvicorn
import uuid

from services.azure_search_service import AzureSearchService
from services.llm_service import LLMService
from services.document_intelligence_service import DocumentIntelligenceService
import config

app = FastAPI(title="Property Management Chatbot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://fluffy-spoon-pj7rwgw4566xc7477-3000.app.github.dev",
        "https://*.app.github.dev"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

search_service = AzureSearchService()
llm_service = LLMService()
doc_intelligence_service = DocumentIntelligenceService()

# In-memory storage for session documents (temporary user uploads)
session_documents: Dict[str, list] = {}

# API Key Authentication
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str = Security(api_key_header)):
    """Verify API key for authentication"""
    if not config.CHATBOT_API_KEY:
        return True
    
    if api_key != config.CHATBOT_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return True

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    sources: List[dict]
    session_id: str

class CleanupRequest(BaseModel):
    session_id: str

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, authenticated: bool = Depends(verify_api_key)):
    try:
        print(f"Chat request - session_id: {request.session_id}")
        print(f"Available sessions: {list(session_documents.keys())}")
        
        # 1. Get session documents (user uploads - in memory)
        session_context = []
        if request.session_id and request.session_id in session_documents:
            session_context = [
                {
                    "content": doc["content"],
                    "filename": doc["filename"],
                    "score": 1.0  # High score for user-uploaded docs
                }
                for doc in session_documents[request.session_id]
            ]
            print(f"Found {len(session_context)} session documents")
        else:
            print(f"No session documents found for session_id: {request.session_id}")
        
        # 2. Search indexed documents (company docs from blob storage)
        indexed_results = await search_service.search(request.message)
        print(f"Found {len(indexed_results)} indexed documents")
        
        # 3. Combine both sources (prioritize user uploads)
        all_context = session_context + indexed_results
        print(f"Total context documents: {len(all_context)}")
        
        # 4. Generate response with LLM
        response = await llm_service.generate_response(
            query=request.message,
            context=all_context[:5],  # Top 5 results
            session_id=request.session_id
        )
        
        return ChatResponse(
            response=response["answer"],
            sources=response["sources"],
            session_id=response["session_id"]
        )
        
    except Exception as e:
        print(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload")
async def upload_document(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    authenticated: bool = Depends(verify_api_key)
):
    """
    Upload a document, extract text with Document Intelligence, 
    store in memory for immediate access
    """
    try:
        # Generate session ID if not provided
        if not session_id:
            session_id = str(uuid.uuid4())
        
        print(f"Upload - session_id: {session_id}, filename: {file.filename}")
        
        # Validate file type
        allowed_types = [
            'application/pdf',
            'image/jpeg',
            'image/jpg', 
            'image/png',
            'image/tiff',
            'image/bmp',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'text/plain'
        ]
        
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File type {file.content_type} not supported. Supported types: PDF, Images (JPG, PNG, TIFF, BMP), DOCX, TXT"
            )
        
        # Read file content
        file_content = await file.read()
        print(f"File size: {len(file_content)} bytes")
        
        # Extract text using Document Intelligence
        print(f"Extracting text from {file.filename}...")
        extraction_result = await doc_intelligence_service.extract_text(
            file_content,
            file.filename
        )
        
        if not extraction_result['success']:
            print(f"Extraction failed: {extraction_result.get('error')}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to extract text: {extraction_result.get('error', 'Unknown error')}"
            )
        
        print(f"Extracted {len(extraction_result['text'])} characters from {extraction_result['page_count']} pages")
        
        # Store in memory for this session
        if session_id not in session_documents:
            session_documents[session_id] = []
        
        session_documents[session_id].append({
            "filename": file.filename,
            "content": extraction_result['text'],
            "page_count": extraction_result['page_count']
        })
        
        print(f"Stored document in session {session_id}. Total docs in session: {len(session_documents[session_id])}")
        print(f"Total active sessions: {len(session_documents)}")
        
        return {
            "message": "File uploaded and ready for immediate queries!",
            "filename": file.filename,
            "session_id": session_id,
            "pages_extracted": extraction_result['page_count'],
            "text_length": len(extraction_result['text']),
            "immediate_access": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in upload_document: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/cleanup-session")
async def cleanup_session(
    request: CleanupRequest,
    authenticated: bool = Depends(verify_api_key)
):
    """
    Clean up session documents from memory.
    Called when user closes the chat or session ends.
    """
    try:
        session_id = request.session_id
        print(f"Cleanup request for session: {session_id}")
        
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
        
        # Remove from memory
        if session_id in session_documents:
            files_count = len(session_documents[session_id])
            del session_documents[session_id]
            print(f"Deleted {files_count} documents from session {session_id}")
            print(f"Remaining active sessions: {len(session_documents)}")
            
            return {
                "message": "Session cleaned up successfully",
                "session_id": session_id,
                "files_deleted": files_count
            }
        
        print(f"No session found for {session_id}")
        return {
            "message": "No session found",
            "session_id": session_id,
            "files_deleted": 0
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in cleanup_session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/indexer/status")
async def get_indexer_status(authenticated: bool = Depends(verify_api_key)):
    """Get status of Azure Search indexer (for company documents)"""
    try:
        status = await search_service.get_indexer_status()
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/indexer/run")
async def run_indexer(authenticated: bool = Depends(verify_api_key)):
    """Manually trigger Azure Search indexer (for company documents)"""
    try:
        success = await search_service.run_indexer()
        if success:
            return {"message": "Indexer triggered successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to trigger indexer")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
async def health_check():
    """Public health check endpoint - no authentication required"""
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)