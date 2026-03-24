from dotenv import load_dotenv
import os

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '../.env'))

CENTER_ACCESS_KEY = os.getenv("CENTER_ACCESS_KEY")
CENTER_URL = os.getenv("CENTER_URL")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

print(LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET)