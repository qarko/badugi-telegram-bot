# main.py (v1.0 - Official Release)

import os
import logging
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import Forbidden
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
        # 모든 게임 변수를 초기화합니다.
        self.game_active = False
        self.host_id = None
        self.chat_id = None
        self.game_message_id = None
        self.players = {}  # {user_id: {'name', 'chips', 'hand', 'bet', 'is_folded', 'acted'}}
        logger.info("게임 상태가 초기화되었습니다.")

game = BadugiGame()


# --- 4. 헬퍼 함수 ---
async def get_user_data(user_id: int, username: str) -> dict:
    """사용자 정보를 가져오거나 새로 생성합니다."""
    if not db:
        return {"user_id": user_id, "username": username, "chips": 10000, "role": "user", "total_games": 0, "wins": 0}

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
    """새로운 바둑이 게임 시작 (로비 생성)"""
    user = update.effective_user
    chat = update.effective_chat

    if chat.type == 'private':
        await update.message.reply_text("게임은 그룹 채팅에서만 시작할 수 있습니다.")
        return

    if game.game_active:
        await update.message.reply_text("이미 진행 중인 게임이 있습니다. '/강제초기화'를 시도해보세요.")
        return
    
    game.reset()
    game.game_active = True
    game.host_id = user.id
    game.chat_id = chat.id

    user_data = await get_user_data(user.id, user.first_name)
    game.players[user.id] = {'name': user.first_name, 'chips': user_data.get('chips', 0)}

    keyboard = [[
        InlineKeyboardButton("✅ 참가하기", callback_data='join_game'),
        InlineKeyboardButton("▶️ 게임 시작", callback_data='start_game'),
        InlineKeyboardButton("❌ 게임 취소", callback_data='cancel_game')
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    player_list = "\n".join([p['name'] for p in game.players.values()])
    msg = await update.message.reply_text(
        f"🎲 바둑이 게임 참가자를 모집합니다!\n\n**주최자:** {user.first_name}\n**참가자 ({len(game.players)}명):**\n{player_list}",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    game.game_message_id = msg.message_id
    logger.info(f"게임방 생성 완료 (주최자: {user.first_name}, chat_id: {chat.id})")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # (v7.1 코드와 동일)
    pass
async def ranking_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # (v7.1 코드와 동일)
    pass
async def transfer_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # (v7.1 코드와 동일)
    pass
async def force_reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # (v7.1 코드와 동일)
    pass
async def set_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # (v7.1 코드와 동일)
    pass

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """모든 인라인 버튼 입력을 처리합니다."""
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if not game.game_active:
        await query.edit_message_text("이미 종료되었거나 취소된 게임입니다.")
        return

    # --- 로비 기능 ---
    if query.data == 'join_game':
        if user.id in game.players: return
        user_data = await get_user_data(user.id, user.first_name)
        game.players[user.id] = {'name': user.first_name, 'chips': user_data.get('chips', 0)}
        
        player_list = "\n".join([p['name'] for p in game.players.values()])
        await context.bot.edit_message_text(
            chat_id=game.chat_id, message_id=game.game_message_id,
            text=f"🎲 바둑이 게임 참가자를 모집합니다!\n\n**주최자:** {game.players[game.host_id]['name']}\n**참가자 ({len(game.players)}명):**\n{player_list}",
            reply_markup=query.message.reply_markup, parse_mode='Markdown'
        )
    elif query.data == 'cancel_game':
        if user.id == game.host_id:
            await query.edit_message_text(f"주최자({user.first_name})에 의해 게임이 취소되었습니다.")
            game.reset()
    elif query.data == 'start_game':
        if user.id != game.host_id:
            await context.bot.send_message(user.id, "게임은 주최자만 시작할 수 있습니다.")
            return
        if len(game.players) < 2:
            await context.bot.send_message(user.id, "최소 2명 이상이어야 시작할 수 있습니다.")
            return
        await query.edit_message_text(f"게임 시작! 참가자: {', '.join([p['name'] for p in game.players.values()])}")
        # TODO: 여기에 실제 게임 루프 시작 함수 호출
        await start_real_game(context)

async def start_real_game(context: ContextTypes.DEFAULT_TYPE) -> None:
    """실제 게임 로직을 시작하는 함수"""
    # 이 부분은 매우 복잡하며, 베팅, 카드 교환, 타이머, 승자 판정 등의 로직을 포함합니다.
    # 지금은 플레이스홀더 메시지만 보냅니다.
    await context.bot.send_message(game.chat_id, "카드를 분배하고 첫 베팅을 시작합니다... (게임 플레이 로직 구현중)")
    # game.reset() # 게임이 끝나면 초기화


# --- 6. 메인 실행 함수 ---
def main() -> None:
    """봇을 시작하고 실행합니다."""
    if not all([TOKEN, MONGODB_URI, ADMIN_USER_ID]):
        logger.critical("필수 환경변수가 설정되지 않았습니다.")
        return
    
    application = Application.builder().token(TOKEN).build()
    
    # 명령어 핸들러
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r'^/바둑이$'), badugi_command))
    # ... (다른 모든 핸들러)

    # 콜백 핸들러
    application.add_handler(CallbackQueryHandler(button_callback_handler))

    print("🤖 바둑이 게임봇 v1.0 (Official Release)이 시작되었습니다.")
    application.run_polling(drop_pending_updates=True)


# --- 7. 프로그램 시작점 ---
if __name__ == "__main__":
    main()
