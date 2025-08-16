import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# 로깅 설정
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 봇 토큰 (환경변수에서 가져오기)
TOKEN = os.getenv('BOT_TOKEN')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """봇 시작 명령어"""
    welcome_message = """
🎮 바둑이 게임봇에 오신 것을 환영합니다!

📋 사용 가능한 명령어:
/start - 봇 시작
/help - 도움말
/hello - 인사하기

🚧 현재 개발 중입니다...
    """
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """도움말 명령어"""
    help_text = """
🎯 바둑이 게임봇 도움말

🃏 바둑이란?
- 4장의 카드로 하는 게임
- 무늬와 숫자가 모두 달라야 함
- 낮은 숫자가 좋은 패

📞 문의사항이 있으시면 개발자에게 연락하세요!
    """
    await update.message.reply_text(help_text)

async def hello(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """인사 명령어"""
    user = update.effective_user
    await update.message.reply_text(f"안녕하세요, {user.first_name}님! 🎮")

def main():
    """메인 함수"""
    if not TOKEN:
        print("❌ 봇 토큰이 설정되지 않았습니다!")
        print("환경변수 BOT_TOKEN을 설정해주세요.")
        return
    
    # 애플리케이션 생성
    application = Application.builder().token(TOKEN).build()
    
    # 명령어 핸들러 등록
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("hello", hello))
    
    print("🤖 봇이 시작되었습니다!")
    
    # 봇 실행
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
