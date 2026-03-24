import os
import logging
from openai import OpenAI
from app.schemas import MicrologSchema

logger = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class AgentMemoryService:
    @staticmethod
    def process_new_microlog(log_data: MicrologSchema) -> MicrologSchema:
        if not log_data.content or not log_data.content.strip():
            return log_data
            
        try:
            response = client.embeddings.create(
                input=log_data.content,
                model="text-embedding-3-small"
            )
            log_data.embedding = response.data[0].embedding
            return log_data
        except Exception as e:
            logger.error(f"OpenAI Embedding Error: {str(e)}")
            raise e