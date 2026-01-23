# backend/services/llm_service.py - FIXED with Citation Tracking

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
- Be concise and professional
- If information is not in the provided context, clearly state that you don't have that information
- Focus on practical, actionable information

CRITICAL CITATION REQUIREMENT:
When you reference information from a document, you MUST cite it using this format:
[DOC_N] where N is the document number (1, 2, 3, etc.)

Example: "According to the Move-Out Policy [DOC_1], residents must provide 60 days notice."

IMPORTANT: Do NOT use Markdown formatting (no **, -, #, etc.) unless explicitly required.

Guidelines:
- Prioritize accuracy over completeness
- Use bullet points for procedures or lists when appropriate
- Include relevant policy numbers or section references when available
- For ambiguous queries, ask clarifying questions
- Always ground your answers in the provided documents
- ALWAYS include [DOC_N] citations when referencing specific information"""

        if has_uploads:
            base_prompt += """

SOURCE ATTRIBUTION:
- When referencing UPLOADED documents, say "According to your uploaded document [DOC_N]..." or "In [document name] [DOC_N]..."
- When referencing COMPANY documents (policies, handbooks), say "According to [policy/handbook name] [DOC_N]..." or "Company policy [DOC_N] states..."
- Be clear about which source each piece of information comes from
- If there are multiple uploaded documents and the query is ambiguous, describe ALL of them with their [DOC_N] citations"""
        else:
            base_prompt += """

SOURCE ATTRIBUTION:
- When referencing information, naturally mention the source with [DOC_N] citation (e.g., "According to the Move-Out Policy [DOC_1]..." or "As stated in the Team Member Handbook [DOC_3]...")"""

        return base_prompt
    
    def _build_prompt(self, query: str, context: List[Dict], has_uploads: bool = False) -> str:
        # Separate uploaded vs company documents
        uploaded_docs = [doc for doc in context if doc.get("source_type") == "uploaded"]
        company_docs = [doc for doc in context if doc.get("source_type") == "company"]
        
        context_text = ""
        doc_number = 1
        doc_mapping = {}  # Maps doc number to filename
        
        # Add uploaded documents first (higher priority)
        if uploaded_docs:
            context_text += "=== UPLOADED DOCUMENTS (User's Files) ===\n"
            for doc in uploaded_docs:
                context_text += f"\n[Document {doc_number}: {doc['filename']}]\n"
                doc_mapping[doc_number] = {
                    "filename": doc['filename'],
                    "type": "uploaded"
                }
                context_text += f"{doc['content']}\n"
                context_text += f"(End of Document {doc_number})\n"
                doc_number += 1
        
        # Add company documents
        if company_docs:
            if uploaded_docs:
                context_text += "\n" + "="*60 + "\n\n"
            context_text += "=== COMPANY DOCUMENTS (Policies, Handbooks, Procedures) ===\n"
            for doc in company_docs:
                context_text += f"\n[Document {doc_number}: {doc['filename']}]\n"
                doc_mapping[doc_number] = {
                    "filename": doc['filename'],
                    "type": "company"
                }
                # Allow up to 10,000 chars per company doc
                content = doc['content'][:10000]
                context_text += f"{content}\n"
                if len(doc['content']) > 10000:
                    context_text += f"... (content truncated, original length: {len(doc['content'])} chars)\n"
                context_text += f"(End of Document {doc_number})\n"
                doc_number += 1
        
        prompt = f"""Context from documents:

{context_text}

User question: {query}

Answer (remember to cite sources with [DOC_N] format):"""
        
        return prompt, doc_mapping
    
    def _extract_citations(self, response_text: str, doc_mapping: Dict) -> List[Dict]:
        """Extract [DOC_N] citations from LLM response"""
        # Find all [DOC_N] patterns in response
        citation_pattern = r'\[DOC_(\d+)\]'
        cited_doc_numbers = set(re.findall(citation_pattern, response_text))
        
        # Build sources list from cited documents
        sources = []
        for doc_num_str in sorted(cited_doc_numbers, key=int):
            doc_num = int(doc_num_str)
            if doc_num in doc_mapping:
                doc_info = doc_mapping[doc_num]
                icon = "📤" if doc_info["type"] == "uploaded" else "📁"
                sources.append({
                    "filename": f"{icon} {doc_info['filename']}",
                    "type": doc_info["type"]
                })
        
        return sources
    
    def _clean_response(self, response_text: str) -> str:
        """Remove [DOC_N] citations from response for cleaner display"""
        # Replace [DOC_N] with nothing
        cleaned = re.sub(r'\s*\[DOC_\d+\]\s*', ' ', response_text)
        # Clean up multiple spaces
        cleaned = re.sub(r'\s+', ' ', cleaned)
        return cleaned.strip()
    
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
            
            # Clean citations from response for display
            cleaned_response = self._clean_response(response)
            
            print(f"✅ Generated response")
            print(f"   Documents provided: {len(doc_mapping)}")
            print(f"   Documents cited: {len(sources)}")
            if sources:
                for i, src in enumerate(sources, 1):
                    print(f"     {i}. {src['filename']}")
            else:
                print(f"   ⚠️  No documents cited (LLM didn't use [DOC_N] format)")
            
            # Store conversation
            self.conversation_history[session_id].append({
                "query": query,
                "response": cleaned_response
            })
            
            # If no citations found, fall back to showing all docs (with warning)
            if not sources and context:
                print(f"   ⚠️  Falling back to showing all provided documents")
                sources = []
                seen_files = set()
                
                for doc in context:
                    filename = doc["filename"]
                    if filename not in seen_files:
                        seen_files.add(filename)
                        doc_type = doc.get("source_type", "unknown")
                        icon = "📤" if doc_type == "uploaded" else "📁"
                        sources.append({
                            "filename": f"{icon} {filename}",
                            "type": doc_type
                        })
            
            return {
                "answer": cleaned_response,
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
        
        # Add conversation history (last 3 exchanges)
        for msg in self.conversation_history[session_id][-3:]:
            messages.append({"role": "user", "content": msg["query"]})
            messages.append({"role": "assistant", "content": msg["response"]})
        
        messages.append({"role": "user", "content": user_prompt})
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
            max_tokens=2000
        )
        
        return response.choices[0].message.content