# backend/services/intent_service.py - NEW FILE

from openai import AzureOpenAI
import config

class IntentService:
    def __init__(self):
        self.client = AzureOpenAI(
            api_key=config.AZURE_OPENAI_API_KEY,
            api_version=config.AZURE_OPENAI_API_VERSION,
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT
        )
        self.model = config.AZURE_OPENAI_DEPLOYMENT_NAME
    
    async def classify_intent(self, query: str, has_uploaded_docs: bool) -> dict:
        """
        Classify user intent using LLM
        Returns: {
            'intent': 'casual' | 'upload_only' | 'policy_only' | 'comparison',
            'confidence': float
        }
        """
        
        system_prompt = f"""You are an intent classifier for a property management chatbot.
        
User has uploaded documents: {has_uploaded_docs}

Classify the query into ONE of these intents:

1. **casual**: Greetings, thanks, small talk (no document search needed)
2. **upload_only**: Query specifically about uploaded documents
   - Examples: "what is in the uploaded file", "describe this document", "latest upload"
3. **policy_only**: Query about company/Adara policies (not uploaded docs)
   - Examples: "what are Adara's policies", "company move-out procedures"
4. **comparison**: Comparing uploaded docs with company policies
   - Examples: "does this comply with our policy", "compare with company standards"

Respond ONLY with JSON:
{{"intent": "casual|upload_only|policy_only|comparison", "confidence": 0.0-1.0}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                temperature=0.1,
                max_tokens=50
            )
            
            result = response.choices[0].message.content.strip()
            
            # Parse JSON response
            import json
            intent_data = json.loads(result)
            
            return intent_data
            
        except Exception as e:
            print(f"⚠️  Intent classification error: {e}, falling back to 'policy_only'")
            return {"intent": "policy_only", "confidence": 0.5}