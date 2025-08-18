# main.py (v3.1 - Tiered Admin Permissions)

import os
import logging
# ... (이전과 동일한 import)
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# --- 초기 설정 ---
# ... (이전과 동일)
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', 0))

# --- 데이터베이스 연결 ---
# ... (이전과 동일)

# --- 게임 상수 및 클래스 ---
# ... (이전과 동일)

game = BadugiGame()

# --- DB 헬퍼 함수 ---
async def get_user_data(user_id, username):
    if db is None: return {'user_id': user_id, 'username': username, 'chips': 10000, 'role': 'user'}
    user = await users_collection.find_one({"user_id": user_id})
    if not user:
        # [변경] 최초 사용자가 ADMIN_USER_ID와 일치하면 'owner' 권한 부여
        role = 'owner' if user_id == ADMIN_USER_ID else 'user'
        user_data = {
            'user_id': user_id, 'username': username, 
            'chips': 100000 if role == 'owner' else 10000, 
            'role': role, 'total_games': 0, 'wins': 0
        }
        await users_collection.insert_one(user_data)
        return user_data
    if user.get('username') != username: 
        await users_collection.update_one({"user_id": user_id}, {"$set": {"username": username}})
    return user

async def get_user_role(user_id):
    """[신규] 사용자의 권한 등급을 반환하는 함수"""
    user = await get_user_data(user_id, "") # username은 중요하지 않음
    return user.get('role', 'user')

async def update_user_chips(user_id, amount):
    # ... (이전과 동일)

# --- 핵심 게임 진행 함수 ---
# ... (게임 로직 전체는 변경사항 없음)

# --- 명령어 핸들러 (관리자 기능 수정) ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    # ... (이전과 동일)
async def badugi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (이전과 동일)
async def transfer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (이전과 동일)

async def force_reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_role = await get_user_role(user.id)
    
    # [변경] 'owner' 또는 'admin' 권한이 있으면 실행 가능
    if user_role not in ['owner', 'admin']:
        await update.message.reply_text("이 명령어를 사용할 권한이 없습니다."); return
    
    chat_id = game.chat_id if game.game_active else update.message.chat_id
    if chat_id: 
        await context.bot.send_message(chat_id, f"🚨 관리자({user.first_name})에 의해 게임이 강제 초기화되었습니다.")
    game.reset()
    await update.message.reply_text("모든 게임 상태를 초기화했습니다.")

async def set_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_role = await get_user_role(user.id)
    
    # [변경] 오직 'owner' 권한만 실행 가능
    if user_role != 'owner':
        await update.message.reply_text("최고 관리자(Owner)만 사용할 수 있는 명령어입니다."); return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("관리자로 지정할 사용자의 메시지에 답장하며 사용해주세요."); return

    target_user = update.message.reply_to_message.from_user
    # [변경] 새로 임명된 관리자는 'admin' 등급을 받음
    await users_collection.update_one({"user_id": target_user.id}, {"$set": {"role": "admin"}}, upsert=True)
    await get_user_data(target_user.id, target_user.first_name) # DB에 없는 유저일 경우를 대비해 정보 생성
    
    await update.message.reply_text(f"✅ {target_user.first_name}님을 [일반 관리자]로 임명했습니다.")

# --- 레이즈, 콜백, 메인 함수 ---
# ... (이하 모든 코드는 이전 버전과 동일)

def main():
    # ...
    # 명령어 핸들러 등록
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("바둑이", badugi_command))
    application.add_handler(CommandHandler("송금", transfer_command))
    
    # 관리자 명령어
    application.add_handler(CommandHandler("강제초기화", force_reset_command))
    application.add_handler(CommandHandler("관리자임명", set_admin_command))

    # 콜백 및 메시지 핸들러
    # ...
    
    print("🤖 바둑이 게임봇 v3.1 (Tiered Admin)이 시작되었습니다.")
    application.run_polling()

if __name__ == '__main__':
    main()
