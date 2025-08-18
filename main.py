# main.py (v6.2 - Fully Verified & Complete with Startup Fix)

import os
import logging
import asyncio
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from motor.motor_asyncio import AsyncIOMotorClient

# --- 1. 초기 설정 ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
MONGODB_URI = os.getenv("MONGODB_URI")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", 0))

# --- 2. 데이터베이스 연결 ---
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


# --- 3. 게임 상태 클래스 ---
class BadugiGame:
    def __init__(self):
        self.reset()

    def reset(self):
        self.game_active = False
        logger.info("게임 상태가 초기화되었습니다.")

game = BadugiGame()


# --- 4. 헬퍼 함수 (DB 관련) ---
async def get_user_data(user_id: int, username: str) -> dict:
    """사용자 정보를 가져오거나 새로 생성합니다."""
    if not db:
        return {"user_id": user_id, "username": username, "chips": 10000, "role": "user"}

    user = await users_collection.find_one({"user_id": user_id})
    if not user:
        role = "owner" if user_id == ADMIN_USER_ID else "user"
        user_data = {
            "user_id": user_id,
            "username": username,
            "chips": 100000 if role == "owner" else 10000,
            "role": role,
            "total_games": 0,
            "wins": 0,
        }
        await users_collection.insert_one(user_data)
        logger.info(f"새로운 사용자({username}, {user_id})를 데이터베이스에 등록했습니다.")
        return user_data

    if user.get("username") != username and username:
        await users_collection.update_one(
            {"user_id": user_id}, {"$set": {"username": username}}
        )
    return user

async def get_user_role(user_id: int) -> str:
    """사용자의 권한 등급을 반환합니다."""
    user = await get_user_data(user_id, "")
    return user.get("role", "user")

async def update_user_chips(user_id: int, amount: int):
    """사용자의 칩을 변경합니다."""
    if db:
        await users_collection.update_one({"user_id": user_id}, {"$inc": {"chips": amount}})


# --- 5. 명령어 핸들러 함수 ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """봇 시작 및 사용자 등록"""
    user = update.effective_user
    await get_user_data(user.id, user.first_name)
    await update.message.reply_text(
        f"안녕하세요, {user.first_name}님!\n\n"
        "'/바둑이' - 새 게임 시작\n"
        "'/내정보' - 내 정보 보기\n"
        "'/랭킹' - 칩 순위 보기\n"
        "'/송금' - 칩 보내기 (다른 사람 메시지에 답장)"
    )

async def badugi_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """새로운 바둑이 게임 시작"""
    logger.info(f"'/바둑이' 명령이 {update.effective_user.first_name}님으로부터 수신되었습니다.")
    if game.game_active:
        await update.message.reply_text("이미 진행 중인 게임이 있습니다.")
        return
    game.game_active = True
    await update.message.reply_text("🎲 새로운 바둑이 게임을 시작합니다! (현재 기능 개발 중)")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """사용자 정보 보기"""
    user = update.effective_user
    user_data = await get_user_data(user.id, user.first_name)
    total_games = user_data.get('total_games', 0)
    wins = user_data.get('wins', 0)
    win_rate = (wins / total_games * 100) if total_games > 0 else 0
    
    stats_text = (
        f"📊 **{user.first_name}님의 정보**\n\n"
        f"💰 보유 칩: {user_data.get('chips', 0):,}칩\n"
        f"🎮 총 게임: {total_games}판\n"
        f"🏆 승리: {wins}회\n"
        f"📈 승률: {win_rate:.2f}%"
    )
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def ranking_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """칩 랭킹 보기"""
    if not db:
        await update.message.reply_text("데이터베이스가 연결되지 않았습니다.")
        return
    
    leaderboard = users_collection.find().sort("chips", -1).limit(10)
    ranking_text = "🏆 **칩 랭킹 TOP 10**\n\n"
    rank = 1
    async for user in leaderboard:
        emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"**{rank}.**")
        ranking_text += f"{emoji} {user['username']}: {user['chips']:,}칩\n"
        rank += 1
        
    await update.message.reply_text(ranking_text, parse_mode='Markdown')

async def transfer_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """다른 사용자에게 칩 송금"""
    if not update.message.reply_to_message:
        await update.message.reply_text("칩을 보낼 사용자의 메시지에 답장하며 사용해주세요.\n(예: /송금 1000)")
        return
    
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("보낼 칩의 개수를 숫자로 입력해주세요.\n(예: /송금 1000)")
        return

    sender = update.effective_user
    receiver = update.message.reply_to_message.from_user
    amount = int(args[0])

    if sender.id == receiver.id:
        await update.message.reply_text("자기 자신에게 칩을 보낼 수 없습니다.")
        return
    if amount <= 0:
        await update.message.reply_text("0보다 큰 금액을 보내야 합니다.")
        return

    sender_data = await get_user_data(sender.id, sender.first_name)
    if sender_data.get('chips', 0) < amount:
        await update.message.reply_text(f"칩이 부족합니다. (보유: {sender_data.get('chips', 0):,}칩)")
        return

    await get_user_data(receiver.id, receiver.first_name)
    await update_user_chips(sender.id, -amount)
    await update_user_chips(receiver.id, amount)
    await update.message.reply_text(f"{receiver.first_name}님에게 {amount:,}칩을 성공적으로 보냈습니다.")

async def force_reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """게임 상태 강제 초기화 (관리자용)"""
    user_role = await get_user_role(update.effective_user.id)
    if user_role not in ["owner", "admin"]:
        await update.message.reply_text("관리자만 사용할 수 있는 명령어입니다.")
        return
    game.reset()
    await update.message.reply_text("🚨 관리자에 의해 게임 상태가 강제 초기화되었습니다.")

async def set_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """일반 관리자 임명 (최고 관리자용)"""
    user_role = await get_user_role(update.effective_user.id)
    if user_role != "owner":
        await update.message.reply_text("최고 관리자(Owner)만 사용할 수 있는 명령어입니다.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("관리자로 지정할 사용자의 메시지에 답장하며 사용해주세요.")
        return

    target_user = update.message.reply_to_message.from_user
    await get_user_data(target_user.id, target_user.first_name)
    await users_collection.update_one({"user_id": target_user.id}, {"$set": {"role": "admin"}})
    await update.message.reply_text(f"✅ {target_user.first_name}님을 [일반 관리자]로 임명했습니다.")


# --- 6. 메인 실행 함수 ---
async def main() -> None:
    """봇을 시작하고 실행합니다."""
    if not all([TOKEN, MONGODB_URI, ADMIN_USER_ID]):
        logger.critical("필수 환경변수(BOT_TOKEN, MONGODB_URI, ADMIN_USER_ID)가 설정되지 않았습니다.")
        return
    
    application = Application.builder().token(TOKEN).build()

    # 명령어 핸들러 등록
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r'^/바둑이$'), badugi_command))
    application.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r'^/내정보$'), stats_command))
    application.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r'^/랭킹$'), ranking_command))
    application.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r'^/송금'), transfer_command))
    application.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r'^/강제초기화$'), force_reset_command))
    application.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r'^/관리자임명$'), set_admin_command))

    # 봇 실행 (시작 시 오래된 메시지 자동 삭제 포함)
    await application.run_polling(drop_pending_updates=True)


# --- 7. 프로그램 시작점 ---
if __name__ == "__main__":
    print("🤖 바둑이 게임봇 v6.2 (Startup Fix) 시작 중...")
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("봇이 종료되었습니다.")
    except Exception as e:
        logger.critical(f"봇 실행 중 치명적인 오류 발생: {e}")
