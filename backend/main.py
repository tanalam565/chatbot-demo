# main.py - Full Updated Code with Better Upload Detection

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
        print(f"\n{'='*60}")
        print(f"Chat request - session_id: {request.session_id}")
        print(f"Query: {request.message}")
        print(f"Available sessions: {list(session_documents.keys())}")
        
        query_lower = request.message.lower().strip()
        
        # ===== CHECK IF USER HAS UPLOADED DOCUMENTS =====
        has_uploaded_docs = bool(
            request.session_id and request.session_id in session_documents
        )
        print(f"Has uploaded docs: {has_uploaded_docs}")
        
        # ===== INTENT DETECTION =====
        
        # 1. Casual queries (no search needed)
        casual_queries = [
            "hi", "hello", "hey", "how are you", "good morning", "good afternoon",
            "good evening", "thanks", "thank you", "bye", "goodbye"
        ]
        is_casual = any(casual in query_lower for casual in casual_queries) and len(query_lower.split()) <= 5
        
        # 2. Upload-only queries (only use uploaded docs)
        upload_only_patterns = [
            # Direct upload references
            "upload", "uploaded", "the upload",
            "describe the upload", "explain the upload", "summarize the upload",
            "about the upload", "uploaded document", "uploaded file",
            
            # "This" references (when user has uploads, likely referring to them)
            "what is this", "what's this", "describe this", "explain this",
            "summarize this", "read this", "about this",
            "this document", "this file", "the document", "the file",
            
            # Possessive references
            "my document", "my file", "document i uploaded", "file i uploaded",
            "the document i", "the file i",
            
            # Question patterns about uploads
            "what is the uploaded", "what's the uploaded", "what does this",
            "what's in this", "what is in this", "tell me about this"
        ]
        
        is_upload_only = (
            has_uploaded_docs and 
            any(pattern in query_lower for pattern in upload_only_patterns)
        )
        
        # 3. Comparison queries (needs both uploaded + company docs)
        comparison_patterns = [
            "compare", "compliant", "comply", "compliance", "match", "matches",
            "differ", "difference", "vs", "versus", "according to our",
            "does this follow", "is this correct", "does this meet",
            "against our", "with our policy", "standard agreement",
            "does it comply", "is it compliant", "meets our", "follows our"
        ]
        is_comparison = any(pattern in query_lower for pattern in comparison_patterns)
        
        # 4. Policy/handbook queries (company docs only)
        policy_patterns = [
            "our policy", "our policies", "our handbook", "our procedure",
            "company policy", "how to", "how do i", "what are the steps",
            "what is the process", "standard procedure", "disaster management",
            "marketing", "close a deal", "record video", "laws", "regulations",
            "what are adara", "what is adara", "adara's policies", "adara policies"
        ]
        is_policy_only = (
            any(pattern in query_lower for pattern in policy_patterns) and 
            not is_comparison and
            not is_upload_only
        )
        
        print(f"Intent: casual={is_casual}, upload_only={is_upload_only}, comparison={is_comparison}, policy_only={is_policy_only}")
        
        # ===== GET SESSION DOCUMENTS (User Uploads) =====
        session_context = []
        if request.session_id and request.session_id in session_documents:
            session_context = [
                {
                    "content": doc["content"],
                    "filename": doc["filename"],
                    "score": 10.0,  # Shows as 100% in frontend
                    "source_type": "uploaded"
                }
                for doc in session_documents[request.session_id]
            ]
            print(f"Found {len(session_context)} uploaded documents")
        
        # ===== SEARCH INDEXED DOCUMENTS (Company Docs) =====
        indexed_results = []
        
        # Skip search for casual queries
        if is_casual:
            print("Casual query detected - skipping all document search")
        
        # Skip search for upload-only queries if user has uploads
        elif is_upload_only and session_context:
            print("Upload-only query with uploaded docs - skipping company search")
        
        # Search company docs for policy queries
        elif is_policy_only:
            print("Policy query - searching company docs only")
            indexed_results = await search_service.search(request.message)
        
        # Search company docs for comparison queries
        elif is_comparison:
            print("Comparison query - searching company docs to compare with uploads")
            indexed_results = await search_service.search(request.message)
        
        # Search company docs if no uploads exist
        elif not session_context:
            print("No uploads - searching company docs")
            indexed_results = await search_service.search(request.message)
        
        # Default: search if unclear intent
        else:
            print("Default: searching company docs")
            indexed_results = await search_service.search(request.message)
            
        # Mark company docs
        for doc in indexed_results:
            doc["source_type"] = "company"
        
        print(f"Found {len(indexed_results)} company documents")
        
        # ===== SMART CONTEXT SELECTION =====
        if is_upload_only and session_context:
            # Only uploaded docs
            all_context = session_context
            print(f"Context: Using {len(all_context)} uploaded docs ONLY")
            
        elif is_policy_only and not is_comparison:
            # Only company docs
            all_context = indexed_results
            print(f"Context: Using {len(all_context)} company docs ONLY")
            
        elif is_comparison and session_context and indexed_results:
            # Both sources for comparison - filter company docs to high relevance only
            filtered_company = [doc for doc in indexed_results if doc["score"] > 2.5]
            all_context = session_context + filtered_company[:3]  # Top 3 company docs
            print(f"Context: Using {len(session_context)} uploaded + {len(filtered_company[:3])} company docs (comparison mode)")
            
        elif session_context and indexed_results:
            # Both sources available - filter low relevance company docs
            filtered_company = [doc for doc in indexed_results if doc["score"] > 3.0]
            if filtered_company:
                all_context = session_context + filtered_company[:2]  # Top 2 company docs
                print(f"Context: Using {len(session_context)} uploaded + {len(filtered_company[:2])} high-relevance company docs")
            else:
                all_context = session_context
                print(f"Context: Using {len(session_context)} uploaded docs only (no relevant company docs)")
        else:
            # Default: use whatever is available
            all_context = session_context + indexed_results
            print(f"Context: Using all {len(all_context)} docs (default)")
        
        # ===== GENERATE RESPONSE =====
        print(f"Sending {len(all_context[:5])} documents to LLM")
        print(f"{'='*60}\n")
        
        response = await llm_service.generate_response(
            query=request.message,
            context=all_context[:5] if all_context else [],
            session_id=request.session_id,
            has_uploads=bool(session_context),
            is_comparison=is_comparison
        )
        
        return ChatResponse(
            response=response["answer"],
            sources=response["sources"],
            session_id=response["session_id"]
        )
        
    except Exception as e:
        print(f"❌ Chat error: {e}")
        import traceback
        traceback.print_exc()
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
        
        print(f"\n{'='*60}")
        print(f"Upload - session_id: {session_id}")
        print(f"Filename: {file.filename}")
        print(f"Content-Type: {file.content_type}")
        
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
            print(f"❌ Extraction failed: {extraction_result.get('error')}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to extract text: {extraction_result.get('error', 'Unknown error')}"
            )
        
        print(f"✅ Extracted {len(extraction_result['text'])} characters from {extraction_result['page_count']} pages")
        
        # Store in memory for this session
        if session_id not in session_documents:
            session_documents[session_id] = []
        
        session_documents[session_id].append({
            "filename": file.filename,
            "content": extraction_result['text'],
            "page_count": extraction_result['page_count']
        })
        
        print(f"✅ Stored document in session {session_id}")
        print(f"Total docs in session: {len(session_documents[session_id])}")
        print(f"Total active sessions: {len(session_documents)}")
        print(f"{'='*60}\n")
        
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
        print(f"❌ Error in upload_document: {e}")
        import traceback
        traceback.print_exc()
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
        print(f"\n{'='*60}")
        print(f"Cleanup request for session: {session_id}")
        
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
        
        # Remove from memory
        if session_id in session_documents:
            files_count = len(session_documents[session_id])
            del session_documents[session_id]
            print(f"✅ Deleted {files_count} documents from session {session_id}")
            print(f"Remaining active sessions: {len(session_documents)}")
            print(f"{'='*60}\n")
            
            return {
                "message": "Session cleaned up successfully",
                "session_id": session_id,
                "files_deleted": files_count
            }
        
        print(f"⚠️  No session found for {session_id}")
        print(f"{'='*60}\n")
        return {
            "message": "No session found",
            "session_id": session_id,
            "files_deleted": 0
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in cleanup_session: {e}")
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