# backend/services/llm_service.py - UPDATED (No Scores)

from typing import List, Dict, Optional
from openai import AzureOpenAI
import uuid
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
    
    def _build_system_prompt(self, has_uploads: bool = False, is_comparison: bool = False) -> str:
        base_prompt = """You are an AI assistant for YottaReal property management software, helping leasing agents, property managers, and district managers retrieve information.

Your role:
- Answer questions based ONLY on the provided context from documents
- Be concise and professional
- If information is not in the provided context, clearly state that you don't have that information
- Focus on practical, actionable information

IMPORTANT: Do NOT use Markdown formatting (no **, -, #, etc.) unless explicitly required.

Guidelines:
- Prioritize accuracy over completeness
- Use bullet points for procedures or lists when appropriate
- Include relevant policy numbers or section references when available
- For ambiguous queries, ask clarifying questions
- Always ground your answers in the provided documents"""

        if has_uploads and is_comparison:
            base_prompt += """

COMPARISON MODE:
You have access to BOTH uploaded documents AND company policy documents.
- When comparing, explicitly state differences and compliance status
- Format: "Your uploaded document [states X]. According to company policy [Y], this [complies/does not comply] because [reason]."
- Be specific about which document each piece of information comes from
- If documents conflict, clearly state the discrepancy"""

        elif has_uploads:
            base_prompt += """

SOURCE ATTRIBUTION:
- When referencing UPLOADED documents, say "According to your uploaded document..." or "Your [document name] shows..."
- When referencing COMPANY documents (policies, handbooks), say "According to [policy/handbook name]..." or "Company policy states..."
- Be clear about which source each piece of information comes from"""

        else:
            base_prompt += """

SOURCE ATTRIBUTION:
- When referencing information, naturally mention the source (e.g., "According to the Move-Out Policy..." or "As stated in the Team Member Handbook...")"""

        return base_prompt
    
    def _build_prompt(self, query: str, context: List[Dict], has_uploads: bool = False) -> str:
        # Separate uploaded vs company documents
        uploaded_docs = [doc for doc in context if doc.get("source_type") == "uploaded"]
        company_docs = [doc for doc in context if doc.get("source_type") == "company"]
        
        context_text = ""
        
        # Add uploaded documents first (higher priority)
        if uploaded_docs:
            context_text += "=== UPLOADED DOCUMENTS (User's Files) ===\n"
            for i, doc in enumerate(uploaded_docs, 1):
                context_text += f"\n[Uploaded Document {i}: {doc['filename']}]\n"
                context_text += f"{doc['content'][:3000]}\n"
                if len(doc['content']) > 3000:
                    context_text += "... (content truncated)\n"
        
        # Add company documents
        if company_docs:
            if uploaded_docs:
                context_text += "\n" + "="*60 + "\n\n"
            context_text += "=== COMPANY DOCUMENTS (Policies, Handbooks, Procedures) ===\n"
            for i, doc in enumerate(company_docs, 1):
                context_text += f"\n[Company Document {i}: {doc['filename']}]\n"
                context_text += f"{doc['content'][:3000]}\n"
                if len(doc['content']) > 3000:
                    context_text += "... (content truncated)\n"
        
        prompt = f"""Context from documents:

{context_text}

User question: {query}

Answer (be specific about sources):"""
        
        return prompt
    
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
        
        system_prompt = self._build_system_prompt(has_uploads, is_comparison)
        user_prompt = self._build_prompt(query, context, has_uploads)
        
        try:
            response = await self._generate_azure_openai(
                system_prompt, 
                user_prompt, 
                session_id
            )
            
            # Store conversation
            self.conversation_history[session_id].append({
                "query": query,
                "response": response
            })
            
            # Build sources WITHOUT scores
            sources = []
            seen_files = set()
            
            # Add uploaded docs first
            for doc in context:
                if doc.get("source_type") == "uploaded":
                    filename = doc["filename"]
                    if filename not in seen_files:
                        seen_files.add(filename)
                        sources.append({
                            "filename": f"📤 {filename}",
                            "type": "uploaded"
                        })
            
            # Then add company docs
            for doc in context:
                if doc.get("source_type") == "company":
                    filename = doc["filename"]
                    if filename not in seen_files:
                        seen_files.add(filename)
                        sources.append({
                            "filename": f"📁 {filename}",
                            "type": "company"
                        })
            
            # If no source_type (fallback for old data)
            for doc in context:
                if "source_type" not in doc:
                    filename = doc["filename"]
                    if filename not in seen_files:
                        seen_files.add(filename)
                        sources.append({
                            "filename": filename,
                            "type": "unknown"
                        })
            
            print(f"Generated response with {len(sources)} sources")
            
            return {
                "answer": response,
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
            max_tokens=1000
        )
        
        return response.choices[0].message.content