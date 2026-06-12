from dotenv import load_dotenv
import os

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '../.env'))

# Admin token — protects /api/line-oa/sync and /api/line-oa/rotate
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

# Base URL of this service — used to build webhook URLs shown to admins
SERVICE_BASE_URL = os.getenv("SERVICE_BASE_URL", "http://localhost:5002")

# PostgreSQL connection string
DATABASE_URL = os.getenv("DATABASE_URL")

# Redis URL
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
