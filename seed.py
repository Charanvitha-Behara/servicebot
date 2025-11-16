# seed.py
from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))
db = client[os.getenv("DB_NAME")]

knowledge_store = db["knowledge_store"]

# clear existing dynamic memory (optionally)
knowledge_store.delete_many({})

# index for performance / uniqueness
knowledge_store.create_index("question", unique=False)

print("✅ knowledge_store initialized empty (dynamic learning only).")
