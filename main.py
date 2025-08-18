# main.py (v5.1 - Final Release Candidate, No Omissions)

import os
import logging
import random
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
users_collection = None
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


# --- 게임 클래스 ---
class Card:
    def __init__(self, suit, rank): self.suit, self.rank = suit, rank
    def __str__(self): return f"{ {1: 'A', 11: 'J', 12: 'Q', 13: 'K'}.get(self.rank, str(self.rank))}{self.suit}"
    def __repr__(self): return str(self)

class BadugiGame:
    def __init__(self): self.reset()
    def reset(self):
        self.game_active = False

game = BadugiGame()

# --- DB 헬퍼 함수 ---
async def get_user_data(user_id, username):
    if not db: return {'user_id': user_id, 'username': username, 'chips': 10000, 'role': 'user'}
    user = await users_collection.find_one({"user_id": user_id})
    if not user:
        role = 'owner' if user_id == ADMIN_USER_ID else 'user'
        user_data = {
            'user_id': user_id, 'username': username,
            'chips': 100000 if role == 'owner' else 10000,
            'role': role, 'total_games': 0, 'wins': 0
        }
        await users_collection.insert_one(user_data)
        return user_data
    if user.get('username') != username and username:
        await users_collection.update_one({"user_id": user_id}, {"$set": {"username": username}})
    return user

async def get_user_role(user_id):
    user = await get_user_data(user_id, "")
    return user.get('role', 'user')

async def update_user_chips(user_id, amount):
    if db: await users_collection.update_one({"user_id": user_id}, {"$inc": {"chips": amount}})

# --- 명령어 핸들러 ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await get_user_data(user.id, user.first_name)
    await update.message.reply_text(f"안녕하세요, {user.first_name}님!\n'/바둑이' - 새 게임 시작\n'/내정보' - 내 정보 보기\n'/랭킹' - 칩 순위 보기\n'/송금' - 칩 보내기 (답장)")

async def badugi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"'/바둑이' 명령이 {update.effective_user.first_name}님으로부터 수신되었습니다.")
    if game.game_active:
        await update.message.reply_text("이미 진행 중인 게임이 있습니다.")
        return
    # 실제 게임 시작 로직은 여기에 구현됩니다. 지금은 플레이스홀더입니다.
    await update.message.reply_text("🎲 새로운 바둑이 게임 참가자를 모집합니다! (참가 기능 개발중)")
    game.game_active = True

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = await get_user_data(user.id, user.first_name)
    win_rate = (user_data['wins'] / user_data['total_games'] * 100) if user_data['total_games'] > 0 else 0
    stats_text = (
        f"📊 **{user.first_name}님의 정보**\n\n"
        f"💰 보유 칩: {user_data['chips']:,}칩\n"
        f"🎮 총 게임: {user_data['total_games']}판\n"
        f"🏆 승리: {user_data['wins']}회\n"
        f"📈 승률: {win_rate:.2f}%"
    )
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def ranking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db:
        await update.message.reply_text("데이터베이스가 연결되지 않았습니다.")
        return
    
    leaderboard = users_collection.find().sort("chips", -1).limit(10)
    ranking_text = "🏆 **칩 랭킹 TOP 10**\n\n"
    rank = 1
    async for user in leaderboard:
        emoji = ""
        if rank == 1: emoji = "🥇"
        elif rank == 2: emoji = "🥈"
        elif rank == 3: emoji = "🥉"
        else: emoji = f"**{rank}.**"
        
        ranking_text += f"{emoji} {user['username']}: {user['chips']:,}칩\n"
        rank += 1
        
    await update.message.reply_text(ranking_text, parse_mode='Markdown')

async def transfer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("칩을 보낼 사용자의 메시지에 답장하며 이 명령어를 사용해주세요.\n(예: /송금 1000)")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("보낼 칩의 개수를 숫자로 입력해주세요.\n(예: /송금 1000)")
        return

    sender = update.effective_user
    receiver = update.message.reply_to_message.from_user
    amount = int(context.args[0])

    if sender.id == receiver.id:
        await update.message.reply_text("자기 자신에게 칩을 보낼 수 없습니다.")
        return
    if amount <= 0:
        await update.message.reply_text("0보다 큰 금액을 보내야 합니다.")
        return

    sender_data = await get_user_data(sender.id, sender.first_name)
    if sender_data['chips'] < amount:
        await update.message.reply_text(f"칩이 부족합니다. (보유: {sender_data['chips']:,}칩)")
        return

    await get_user_data(receiver.id, receiver.first_name) # 받는 사람 DB에 없으면 생성

    await update_user_chips(sender.id, -amount)
    await update_user_chips(receiver.id, amount)

    await update.message.reply_text(f"{receiver.first_name}님에게 {amount:,}칩을 성공적으로 보냈습니다.")

async def force_reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_role = await get_user_role(update.effective_user.id)
    if user_role not in ['owner', 'admin']:
        await update.message.reply_text("관리자만 사용할 수 있는 명령어입니다.")
        return
    game.reset()
    await update.message.reply_text("🚨 관리자에 의해 게임 상태가 강제 초기화되었습니다.")

async def set_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_role = await get_user_role(update.effective_user.id)
    if user_role != 'owner':
        await update.message.reply_text("최고 관리자(Owner)만 사용할 수 있는 명령어입니다.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("관리자로 지정할 사용자의 메시지에 답장하며 사용해주세요.")
        return

    target_user = update.message.reply_to_message.from_user
    await users_collection.update_one({"user_id": target_user.id}, {"$set": {"role": "admin"}}, upsert=True)
    await get_user_data(target_user.id, target_user.first_name)
    await update.message.reply_text(f"✅ {target_user.first_name}님을 [일반 관리자]로 임명했습니다.")


# --- 메인 실행 함수 ---
async def main():
    if not all([TOKEN, MONGODB_URI, ADMIN_USER_ID]):
        logger.critical("필수 환경변수(BOT_TOKEN, MONGODB_URI, ADMIN_USER_ID)가 설정되지 않았습니다. 봇을 시작할 수 없습니다.")
        return
    
    application = Application.builder().token(TOKEN).build()
    
    # 봇 시작 시 쌓여있는 오래된 메시지들을 모두 청소
    await application.initialize()
    await application.bot.delete_webhook(drop_pending_updates=True)
    logger.info("오래된 업데이트 메시지를 모두 청소했습니다.")
    
    # 명령어 핸들러 등록
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/바둑이$'), badugi_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/내정보$'), stats_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/랭킹$'), ranking_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/송금'), transfer_command))
    
    # 관리자 명령어 핸들러 등록
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/강제초기화$'), force_reset_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/관리자임명$'), set_admin_command))

    print("🤖 바둑이 게임봇 v5.1 (Release Candidate)이 시작되었습니다.")
    
    # 봇 실행
    await application.run_polling(allowed_updates=Update.ALL_TYPES)


# 프로그램 시작점
if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"봇 실행 중 치명적인 오류 발생: {e}")
