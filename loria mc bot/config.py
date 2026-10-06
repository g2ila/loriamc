import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
ATERNOS_SESSION = os.getenv("ATERNOS_SESSION", "").strip()
ATERNOS_SERVER_NAME = os.getenv("ATERNOS_SERVER_NAME", "LORIAMC.aternos.me").strip()
ATERNOS_SERVER_ID = os.getenv("ATERNOS_SERVER_ID", "LGudtxzl0I5KrSIe").strip()
NOTIFICATION_ROLE_ID = os.getenv("NOTIFICATION_ROLE_ID", "").strip()

# قراءة رتب المشرفين وتحويلها إلى قائمة من الأرقام (IDs)
raw_admin_roles = os.getenv("ADMIN_ROLE_IDS", "1518016293893308589,1518015831055798403").strip()
ADMIN_ROLE_IDS = [
    int(r.strip()) for r in raw_admin_roles.split(",") if r.strip().isdigit()
]

if not DISCORD_TOKEN:
    raise ValueError("⚠️ لم يتم العثور على DISCORD_TOKEN في ملف .env!")

if not ATERNOS_SESSION:
    raise ValueError("⚠️ لم يتم العثور على ATERNOS_SESSION في ملف .env!")
