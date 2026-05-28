import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN       = os.getenv("TELEGRAM_TOKEN", "")
GROQ_API_KEY         = os.getenv("GROQ_API_KEY", "")
SITE_API_URL         = os.getenv("SITE_API_URL", "https://quris23.github.io/System")
DB_PATH              = os.getenv("DB_PATH", "bot.db")
AI_PROVIDER          = os.getenv("AI_PROVIDER", "groq")   # "groq" | "claude"

# Supabase (для записи задач в SYSTEM)
SUPABASE_URL         = os.getenv("SUPABASE_URL", "https://hebhndizvzqxlxuepedm.supabase.co")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")  # service_role key
