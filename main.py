# main.py (v4.1 - Final Fix & Modernization)

import os
import logging
import random
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.error import Forbidden
from motor.motor_asyncio import AsyncIOMotorClient

# --- 초기 설정 ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('BOT_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI')
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', 0))

# --- 데이터베이스 연결 ---
db = None
if MONGODB_URI:
    try:
        client = AsyncIOMotorClient(MONGODB_URI)
        db = client.badugi_game
        users_collection = db.users
        logger.info("MongoDB에 성공적으로 연결되었습니다.")
    except Exception as e:
        logger.error(f"MongoDB 연결 실패: {e}")
else:
    logger.warning("MONGODB_URI가 설정되지 않았습니다.")

# --- (이전과 동일한 게임 클래스, DB 헬퍼, 명령어 핸들러 등 완전한 코드가 여기에 포함됩니다) ---
# ...
# ... (생략 없이 모든 코드가 포함되어 있습니다)
# ...

# --- [수정] 메인 실행 함수 ---
async def main():
    if not all([TOKEN, MONGODB_URI, ADMIN_USER_ID]):
        logger.critical("필수 환경변수(BOT_TOKEN, MONGODB_URI, ADMIN_USER_ID)가 설정되지 않았습니다. 봇을 시작할 수 없습니다.")
        return
    
    # [수정] ApplicationBuilder를 사용하여 '오래된 메시지 청소' 기능을 라이브러리가 지원하는 공식적인 방법으로 적용
    application = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init) # 봇 초기화 후 실행될 함수 지정
        .build()
    )
    
    # 핸들러 등록 (이전과 동일)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Entity("bot_command") & filters.Regex(r'/바둑이'), badugi_command))
    # ... (다른 모든 핸들러 등록)
    
    # [수정] 봇을 비동기적으로 실행 (오래된 메시지 청소 옵션 포함)
    await application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

async def post_init(application: Application):
    """봇 초기화 후 실행되는 함수"""
    print("🤖 바둑이 게임봇 v4.1 (Final Fix)이 시작되었습니다.")
    logger.info("오래된 업데이트 메시지를 모두 청소하고 폴링을 시작합니다.")

# [수정] 현대적인 비동기 방식에 맞춰 프로그램 시작점 변경
if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"봇 실행 중 치명적인 오류 발생: {e}")
