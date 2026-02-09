# backend/services/llm_service.py - WITH INLINE CITATIONS AND CHUNK NUMBERS

from typing import List, Dict, Optional
from openai import AzureOpenAI
import uuid
import re
import config

class LLMService:
    def __init__(self):
        self.conversation_history = {}
        
        self.client = AzureOpenAI(
            api_key=config.AZURE_OPENAI_API_KEY,
            api_version=config.AZURE_OPENAI_API_VERSION,
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT
        )
        self.model = config.AZURE_OPENAI_DEPLOYMENT_NAME
    
    def _build_system_prompt(self, has_uploads: bool = False) -> str:
        base_prompt = """You are an AI assistant for YottaReal property management software, helping leasing agents, property managers, and district managers retrieve information.

Your role:
- Answer questions based ONLY on the provided context from documents
- Be thorough and detailed in your responses
- If information is not in the provided context, clearly state that you don't have that information
- Focus on practical, actionable information

FORMATTING REQUIREMENTS (CRITICAL):
- Do NOT use ** for bold text or any Markdown formatting
- DO use bullet points with this EXACT format:
  
  Main topic:
  - Bullet point 1 with details
  - Bullet point 2 with details
  - Bullet point 3 with details

- Each bullet point should be on its OWN LINE
- Add a blank line between major sections
- Use dashes (-) for bullet points
- Keep each bullet point to 2-3 sentences maximum
- Start each major section with a clear heading followed by a colon

Example of CORRECT formatting:

Customer Service Policy:
- All communications must be acknowledged within 24 hours, whether written, electronic, or by phone
- Team members should maintain professional and courteous communication at all times
- Specific guidelines are provided for telephone interactions and greetings

Resident Relations:
- Residents can submit grievances through the Resident Relations email
- Issues should first be addressed with onsite staff before escalation
- All complaints must be documented in writing for proper tracking

CRITICAL INLINE CITATION REQUIREMENT:
You MUST cite information inline using [N] where N is the document number.

Example: "Smoking is prohibited in all units [1]. Lost access cards cost $75 to replace [2]."

RULES:
- Place [N] at the END of the sentence or claim being cited
- Use [N] immediately after relevant information, before the period
- If multiple facts from same document, use same number multiple times
- Always cite factual claims, policies, or specific details
- Do NOT put citations on general statements or your own synthesis

Guidelines:
- Prioritize accuracy and completeness
- Use bullet points on separate lines for easy reading
- Include relevant policy numbers or section references when available
- Provide detailed explanations with context (2-3 sentences per bullet)
- For ambiguous queries, ask clarifying questions
- Always ground your answers in the provided documents
- ALWAYS include inline [N] citations when referencing specific information
- Make responses thorough and informative"""

        if has_uploads:
            base_prompt += """

SOURCE ATTRIBUTION:
- When referencing UPLOADED documents, cite them with their document number [N]
- When referencing COMPANY documents (policies, handbooks), cite with their document number [N]
- Be clear about which source each piece of information comes from
- If there are multiple uploaded documents and the query is ambiguous, describe ALL of them with citations
- Provide comprehensive details from the documents with inline [N] citations"""
        else:
            base_prompt += """

SOURCE ATTRIBUTION:
- When referencing information, cite with inline [N] numbers (e.g., "According to the Move-Out Policy, residents must provide 60 days notice [1].")
- Provide comprehensive information from the cited documents"""

        return base_prompt
    
    def _build_prompt(self, query: str, context: List[Dict], has_uploads: bool = False) -> tuple:
        # Separate uploaded vs company documents
        uploaded_docs = [doc for doc in context if doc.get("source_type") == "uploaded"]
        company_docs = [doc for doc in context if doc.get("source_type") == "company"]
        
        context_text = ""
        doc_number = 1
        doc_mapping = {}  # Maps doc number to filename, chunks, and download_url
        
        # Add uploaded documents first (higher priority)
        if uploaded_docs:
            context_text += "=== UPLOADED DOCUMENTS (User's Files) ===\n"
            for doc in uploaded_docs:
                context_text += f"\n[Document {doc_number}: {doc['filename']}]\n"
                
                # Initialize mapping for this document
                if doc_number not in doc_mapping:
                    doc_mapping[doc_number] = {
                        "filename": doc['filename'],
                        "type": "uploaded",
                        "download_url": doc.get('download_url'),
                        "chunks": []
                    }
                
                # Add chunk number if available
                chunk_num = doc.get('chunk_number')
                if chunk_num is not None:
                    doc_mapping[doc_number]["chunks"].append(chunk_num)
                    context_text += f"(Chunk {chunk_num})\n"
                
                context_text += f"{doc['content']}\n"
                context_text += f"(End of Document {doc_number})\n"
                doc_number += 1
        
        # Add company documents
        if company_docs:
            if uploaded_docs:
                context_text += "\n" + "="*60 + "\n\n"
            context_text += "=== COMPANY DOCUMENTS (Policies, Handbooks, Procedures) ===\n"
            
            # Group chunks by parent document
            parent_groups = {}
            for doc in company_docs:
                parent_id = doc.get('parent_id', 'unknown')
                if parent_id not in parent_groups:
                    parent_groups[parent_id] = {
                        'filename': doc['filename'],
                        'chunks': []
                    }
                parent_groups[parent_id]['chunks'].append(doc)
            
            # Add each parent document with its chunks
            for parent_id, group in parent_groups.items():
                filename = group['filename']
                chunks = group['chunks']
                
                context_text += f"\n[Document {doc_number}: {filename}]\n"
                
                # Initialize mapping for this document
                if doc_number not in doc_mapping:
                    doc_mapping[doc_number] = {
                        "filename": filename,
                        "type": "company",
                        "download_url": chunks[0].get('download_url'),
                        "chunks": []
                    }
                
                # Add all chunks from this document
                for chunk in chunks:
                    chunk_num = chunk.get('chunk_number')
                    if chunk_num is not None:
                        doc_mapping[doc_number]["chunks"].append(chunk_num)
                        context_text += f"\n--- Chunk {chunk_num} ---\n"
                    
                    # Allow up to 10,000 chars per chunk
                    content = chunk['content'][:10000]
                    context_text += f"{content}\n"
                    if len(chunk['content']) > 10000:
                        context_text += f"... (content truncated, original length: {len(chunk['content'])} chars)\n"
                
                context_text += f"(End of Document {doc_number})\n"
                doc_number += 1
        
        prompt = f"""Context from documents:

{context_text}

User question: {query}

Answer (use inline [N] citations and bullet points on separate lines):"""
        
        return prompt, doc_mapping
    
    def _extract_citations(self, response_text: str, doc_mapping: Dict) -> List[Dict]:
        """Extract [N] citations from LLM response and renumber them sequentially"""
        # Find all [N] patterns in response
        citation_pattern = r'\[(\d+)\]'
        cited_doc_numbers = set(re.findall(citation_pattern, response_text))
        
        # Build sources list with SEQUENTIAL numbering
        sources = []
        for new_num, doc_num_str in enumerate(sorted(cited_doc_numbers, key=int), start=1):
            doc_num = int(doc_num_str)
            if doc_num in doc_mapping:
                doc_info = doc_mapping[doc_num]
                icon = "📤" if doc_info["type"] == "uploaded" else "📁"
                
                # Build chunk info string
                chunks = doc_info.get("chunks", [])
                if chunks:
                    chunks_sorted = sorted(chunks)
                    if len(chunks_sorted) == 1:
                        chunk_info = f"Chunk {chunks_sorted[0]}"
                    elif len(chunks_sorted) <= 5:
                        chunk_list = ", ".join(str(c) for c in chunks_sorted)
                        chunk_info = f"Chunks {chunk_list}"
                    else:
                        # Too many chunks, show range
                        chunk_info = f"Chunks {chunks_sorted[0]}-{chunks_sorted[-1]} ({len(chunks_sorted)} total)"
                else:
                    chunk_info = ""
                
                # Build source entry with SEQUENTIAL number
                if chunk_info:
                    source_text = f"{icon} {doc_info['filename']} → {chunk_info}"
                else:
                    source_text = f"{icon} {doc_info['filename']}"
                
                sources.append({
                    "filename": source_text,
                    "type": doc_info["type"],
                    "download_url": doc_info.get("download_url"),
                    "citation_number": new_num  # ← CHANGED: Use sequential number, not original doc_num
                })
        
        return sources
    
    async def generate_response(
        self, 
        query: str, 
        context: List[Dict],
        session_id: Optional[str] = None,
        has_uploads: bool = False,
        is_comparison: bool = False
    ) -> Dict:
        if not session_id:
            session_id = str(uuid.uuid4())
        
        if session_id not in self.conversation_history:
            self.conversation_history[session_id] = []
        
        system_prompt = self._build_system_prompt(has_uploads)
        user_prompt, doc_mapping = self._build_prompt(query, context, has_uploads)
        
        # Calculate actual prompt size
        total_chars = len(user_prompt)
        estimated_tokens = total_chars // 4
        
        uploaded_chars = sum(len(doc['content']) for doc in context if doc.get('source_type') == 'uploaded')
        company_chars = sum(min(len(doc['content']), 10000) for doc in context if doc.get('source_type') == 'company')
        
        print(f"📊 Prompt Statistics:")
        print(f"   Total prompt: {total_chars:,} chars (~{estimated_tokens:,} tokens)")
        print(f"   Uploaded content: {uploaded_chars:,} chars (FULL, no truncation)")
        print(f"   Company content: {company_chars:,} chars")
        print(f"   Context window available: ~128,000 tokens")
        print(f"   Usage: {(estimated_tokens/128000)*100:.1f}%")
        print(f"   Documents provided: {len(doc_mapping)}")
        
        try:
            response = await self._generate_azure_openai(
                system_prompt, 
                user_prompt, 
                session_id
            )
            
            # Extract which documents were actually cited
            sources = self._extract_citations(response, doc_mapping)
            
            # Keep inline citations in the response for display
            # The frontend will render [1], [2] as superscript or styled citations
            
            print(f"✅ Generated response with inline citations")
            print(f"   Documents provided: {len(doc_mapping)}")
            print(f"   Documents cited: {len(sources)}")
            if sources:
                for i, src in enumerate(sources, 1):
                    print(f"     [{src['citation_number']}] {src['filename']}")
            else:
                print(f"   ⚠️  No documents cited (LLM didn't use [N] format)")
            
            # Store conversation
            self.conversation_history[session_id].append({
                "query": query,
                "response": response
            })
            
            # If no citations found, fall back to showing all docs (with warning)
            if not sources and context:
                print(f"   ⚠️  Falling back to showing all provided documents")
                sources = []
                seen_files = set()
                doc_num = 1
                
                for doc in context:
                    filename = doc["filename"]
                    if filename not in seen_files:
                        seen_files.add(filename)
                        doc_type = doc.get("source_type", "unknown")
                        icon = "📤" if doc_type == "uploaded" else "📁"
                        sources.append({
                            "filename": f"{icon} {filename}",
                            "type": doc_type,
                            "download_url": doc.get("download_url"),
                            "citation_number": doc_num
                        })
                        doc_num += 1
            
            return {
                "answer": response,  # Keep inline citations [1], [2], etc.
                "sources": sources,
                "session_id": session_id
            }
        
        except Exception as e:
            print(f"❌ LLM generation error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "answer": "I apologize, but I encountered an error processing your request.",
                "sources": [],
                "session_id": session_id
            }
    
    async def _generate_azure_openai(
        self, 
        system_prompt: str, 
        user_prompt: str,
        session_id: str
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add ALL conversation history
        for msg in self.conversation_history[session_id]:
            messages.append({"role": "user", "content": msg["query"]})
            messages.append({"role": "assistant", "content": msg["response"]})
        
        # Add current message
        messages.append({"role": "user", "content": user_prompt})
        
        # Log conversation length for monitoring
        total_history_messages = len(self.conversation_history[session_id])
        print(f"📝 Including {total_history_messages} previous exchanges in context")
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
            max_tokens=2500
        )
        
        return response.choices[0].message.content