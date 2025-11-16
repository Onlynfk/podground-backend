import os
import logging
import asyncio
from typing import Optional, Dict, List, Any
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

logger = logging.getLogger(__name__)

class AICategorization:
    def __init__(self):
        self.api_key = os.getenv('GEMINI_API_KEY')
        self.model_name = os.getenv('GEMINI_MODEL_NAME', 'gemini-1.5-flash')
        
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not found in environment variables")
            self.enabled = False
            return
            
        try:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(self.model_name)
            self.enabled = True
            logger.info(f"Gemini AI categorization service initialized successfully with model: {self.model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini AI with model {self.model_name}: {str(e)}")
            self.enabled = False
    
    async def categorize_post(self, content: str, available_categories: List[Dict[str, Any]]) -> Optional[str]:
        """
        Categorize a post using Gemini AI
        
        Args:
            content: The post content to categorize
            available_categories: List of available categories with their info
            
        Returns:
            category_id of the best matching category, or None if categorization fails
        """
        if not self.enabled:
            logger.warning("AI categorization is disabled - no API key or initialization failed")
            return None
            
        if not content.strip():
            logger.warning("Empty content provided for categorization")
            return None
            
        try:
            # Prepare the categorization prompt
            categories_info = []
            for category in available_categories:
                keywords = ", ".join(category.get("keywords", []))
                categories_info.append(f"- {category['name']}: {category['description']} (Keywords: {keywords})")
            
            categories_list = "\n".join(categories_info)
            
            prompt = f"""
You are a content categorization AI. Your job is to classify social media posts into the most appropriate category.

Available Categories:
{categories_list}

Post Content:
"{content}"

Instructions:
1. Analyze the post content carefully
2. Choose the MOST appropriate single category from the list above
3. Respond with ONLY the category name (e.g., "technology", "business", etc.)
4. If the content doesn't clearly fit any specific category, use "general"
5. Do not provide explanations, just the category name

Category:"""

            # Generate response with safety settings
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            }
            
            response = await asyncio.to_thread(
                self.model.generate_content,
                prompt,
                safety_settings=safety_settings,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,  # Low temperature for consistent categorization
                    max_output_tokens=50,  # We only need a short response
                )
            )
            
            if not response or not response.text:
                logger.warning("Empty response from Gemini AI")
                return None
                
            # Extract and validate the category
            predicted_category = response.text.strip().lower()
            
            # Find matching category by name
            for category in available_categories:
                if category["name"].lower() == predicted_category:
                    logger.info(f"Post categorized as '{category['name']}' by AI")
                    return category["id"]
            
            # If no exact match found, try partial matching
            for category in available_categories:
                if predicted_category in category["name"].lower() or category["name"].lower() in predicted_category:
                    logger.info(f"Post categorized as '{category['name']}' by AI (partial match)")
                    return category["id"]
            
            # Fallback to 'general' category
            for category in available_categories:
                if category["name"].lower() == "general":
                    logger.warning(f"AI returned unrecognized category '{predicted_category}', using 'general'")
                    return category["id"]
            
            logger.error(f"No suitable category found for AI prediction '{predicted_category}'")
            return None
            
        except Exception as e:
            logger.error(f"AI categorization error: {str(e)}")
            return None
    
    async def get_fallback_category(self, available_categories: List[Dict[str, Any]]) -> Optional[str]:
        """
        Get the fallback 'general' category ID
        """
        for category in available_categories:
            if category["name"].lower() == "general":
                return category["id"]
        
        # If no 'general' category exists, return the first available category
        if available_categories:
            return available_categories[0]["id"]
            
        return None
    
    def is_enabled(self) -> bool:
        """Check if AI categorization is enabled"""
        return self.enabled

# Global instance
ai_categorization = AICategorization()