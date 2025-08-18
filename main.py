# main.py (v3.3 - Korean Command Fix)

import os
import logging
import random
import asyncio
# ... (다른 import 구문들은 이전과 동일)
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# --- (Card, BadugiGame 클래스 및 다른 모든 게임 로직 함수들은 이전과 동일) ---
# ...
# (코드가 매우 길어 변경된 부분인 main() 함수 위주로 보여드립니다. 다른 부분은 v3.2와 동일합니다.)
# ...

# --- 메인 실행 함수 ---
def main():
    if not all([TOKEN, MONGODB_URI, ADMIN_USER_ID]):
        print("필수 환경변수(BOT_TOKEN, MONGODB_URI, ADMIN_USER_ID)가 설정되지 않았습니다.")
        return
        
    application = Application.builder().token(TOKEN).build()
    
    # [변경] CommandHandler -> MessageHandler로 변경하여 한글 명령어 지원
    # 영어 명령어는 CommandHandler로 유지
    application.add_handler(CommandHandler("start", start_command))
    
    # 한글 명령어는 MessageHandler로 등록
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/바둑이$'), badugi_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/송금'), transfer_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/내정보$'), stats_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/랭킹$'), ranking_command))
    
    # 관리자 명령어 (한글)
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/강제초기화$'), force_reset_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/관리자임명$'), set_admin_command))

    # 콜백 핸들러 (버튼 처리)
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    
    # 레이즈 금액 처리를 위한 메시지 핸들러 (이전과 동일)
    application.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r'/bet'), handle_raise_amount))
    
    print("🤖 바둑이 게임봇 v3.3 (Korean Command Fix)이 시작되었습니다.")
    application.run_polling()

if __name__ == '__main__':
    main()
