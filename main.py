import os
import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# 로깅 설정
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 봇 토큰
TOKEN = os.getenv('BOT_TOKEN')

# 카드 클래스
class Card:
    def __init__(self, suit, rank):
        self.suit = suit  # ♠♣♦♥
        self.rank = rank  # 1(A)~13(K)
    
    def __str__(self):
        rank_names = {1: 'A', 11: 'J', 12: 'Q', 13: 'K'}
        rank_str = rank_names.get(self.rank, str(self.rank))
        return f"{rank_str}{self.suit}"
    
    def __repr__(self):
        return str(self)

# 게임 클래스
class BadugiGame:
    def __init__(self):
        self.players = {}  # user_id: player_data
        self.deck = []
        self.game_active = False
        
    def create_deck(self):
        """새로운 덱 생성"""
        suits = ['♠', '♣', '♦', '♥']
        self.deck = []
        for suit in suits:
            for rank in range(1, 14):  # A(1) ~ K(13)
                self.deck.append(Card(suit, rank))
        random.shuffle(self.deck)
    
    def deal_cards(self, player_count):
        """플레이어들에게 카드 4장씩 딜링"""
        hands = []
        for _ in range(player_count):
            hand = []
            for _ in range(4):
                if self.deck:
                    hand.append(self.deck.pop())
            hands.append(hand)
        return hands
    
    def evaluate_hand(self, cards):
        """바둑이 족보 판정"""
        if len(cards) != 4:
            return "잘못된 카드 수", 0, []
            
        # 무늬와 숫자 확인
        suits = [card.suit for card in cards]
        ranks = [card.rank for card in cards]
        
        # 중복 제거
        unique_suits = list(set(suits))
        unique_ranks = list(set(ranks))
        
        # 메이드 체크 (무늬 4개, 숫자 4개 모두 다름)
        if len(unique_suits) == 4 and len(unique_ranks) == 4:
            # 가장 낮은 숫자 4개의 합계로 순위 결정 (낮을수록 좋음)
            rank_sum = sum(min(13, rank) if rank == 1 else rank for rank in ranks)
            return "메이드", rank_sum, cards
        
        # 베이스 - 중복 카드 제거하고 가장 좋은 조합
        valid_cards = []
        used_suits = set()
        used_ranks = set()
        
        # 낮은 숫자부터 정렬
        sorted_cards = sorted(cards, key=lambda x: (x.rank if x.rank != 1 else 0.5))
        
        for card in sorted_cards:
            if card.suit not in used_suits and card.rank not in used_ranks:
                valid_cards.append(card)
                used_suits.add(card.suit)
                used_ranks.add(card.rank)
        
        card_count = len(valid_cards)
        if card_count == 3:
            rank_type = "세컨드"
        elif card_count == 2:
            rank_type = "써드"
        else:
            rank_type = "베이스"
        
        # 순위 계산 (카드 개수가 많을수록, 숫자가 낮을수록 좋음)
        rank_sum = sum(card.rank if card.rank != 1 else 0.5 for card in valid_cards)
        final_rank = (4 - card_count) * 1000 + rank_sum
        
        return rank_type, final_rank, valid_cards

# 전역 게임 인스턴스
game = BadugiGame()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """봇 시작 명령어"""
    welcome_message = """
🎮 바둑이 게임봇에 오신 것을 환영합니다!

📋 게임 명령어:
/game_start - 새 게임 시작
/test_hand - 테스트 카드 받기
/rules - 게임 룰 설명
/help - 도움말

🎯 바둑이는 4장의 카드로 하는 게임입니다!
무늬와 숫자가 모두 달라야 가장 좋은 패가 됩니다.
    """
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """도움말 명령어"""
    help_text = """
🎯 바둑이 게임봇 도움말

🃏 바둑이 족보 (좋은 순서):
1️⃣ 골프 바둑이: A♠2♣3♦4♥ (최고의 패)
2️⃣ 메이드: 무늬 4개, 숫자 4개 모두 다름
3️⃣ 세컨드: 3장만 유효 (1장 중복)
4️⃣써드: 2장만 유효 (2장 중복)
5️⃣ 베이스: 1장만 유효 (3장 중복)

🎮 게임 방법:
1. /game_start로 게임 시작
2. 카드 4장 받기
3. 족보 확인하기
4. (향후) 베팅하고 카드 교환하기

💡 팁: 낮은 숫자일수록 좋습니다!
    """
    await update.message.reply_text(help_text)

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """게임 룰 설명"""
    rules_text = """
📖 바둑이 게임 룰

🎯 목표: 4장의 카드로 가장 좋은 족보 만들기

🃏 족보 설명:
• 메이드: 무늬♠♣♦♥ 4개, 숫자 4개 모두 다름
• 세컨드: 3장만 서로 다름 (1장 중복)
• 써드: 2장만 서로 다름 (2장 중복)  
• 베이스: 1장만 유효 (3장 중복)

📊 순위 결정:
1. 족보 종류 (메이드 > 세컨드 > 써드 > 베이스)
2. 같은 족보면 낮은 숫자가 승리
3. A(에이스)가 가장 낮은 숫자 (1)

🎮 게임 진행:
1. 각자 카드 4장 받기
2. 1차 베팅
3. 카드 교환 (0~4장)
4. 2차 베팅 및 교환
5. 3차 베팅 및 교환  
6. 최종 베팅 후 결과 확인

🏆 예시:
A♠2♣3♦4♥ (골프 바둑이) > A♠2♣3♦5♥ (메이드)
    """
    await update.message.reply_text(rules_text)

async def test_hand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """테스트용 카드 받기"""
    user = update.effective_user
    
    # 새 덱 생성하고 카드 4장 딜링
    game.create_deck()
    hand = game.deal_cards(1)[0]  # 1명에게 카드 4장
    
    # 족보 판정
    hand_type, rank_value, valid_cards = game.evaluate_hand(hand)
    
    # 카드 시각화
    cards_text = " ".join(str(card) for card in hand)
    valid_cards_text = " ".join(str(card) for card in valid_cards)
    
    result_message = f"""
🃏 {user.first_name}님의 테스트 카드:

📇 받은 카드: {cards_text}
🎯 족보: {hand_type}
✨ 유효 카드: {valid_cards_text}
📊 점수: {rank_value:.1f} (낮을수록 좋음)

💡 족보 설명:
• 메이드: 무늬와 숫자 모두 4개 다름 ✨
• 세컨드: 3장만 유효
• 써드: 2장만 유효
• 베이스: 1장만 유효

🎮 다시 받으려면 /test_hand 명령어를 사용하세요!
    """
    
    await update.message.reply_text(result_message)

async def game_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """새 게임 시작"""
    user = update.effective_user
    
    if game.game_active:
        await update.message.reply_text("❌ 이미 진행 중인 게임이 있습니다!")
        return
    
    # 게임 초기화
    game.game_active = True
    game.create_deck()
    
    keyboard = [
        [InlineKeyboardButton("🎮 게임 참가", callback_data="join_game")],
        [InlineKeyboardButton("❌ 게임 취소", callback_data="cancel_game")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    start_message = f"""
🎮 새로운 바둑이 게임이 시작되었습니다!

👤 게임 호스트: {user.first_name}
👥 현재 참가자: 0명
🎯 필요 인원: 2~4명

⏰ 2분 내에 참가자를 모집합니다.
참가하려면 아래 버튼을 클릭하세요!
    """
    
    await update.message.reply_text(start_message, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """인라인 키보드 버튼 처리"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    if query.data == "join_game":
        if user.id in game.players:
            await query.edit_message_text("❌ 이미 게임에 참가하셨습니다!")
            return
        
        # 플레이어 추가
        game.players[user.id] = {
            'name': user.first_name,
            'hand': [],
            'chips': 10000
        }
        
        player_count = len(game.players)
        player_names = [game.players[pid]['name'] for pid in game.players]
        
        if player_count >= 2:
            keyboard = [
                [InlineKeyboardButton("🎮 게임 시작", callback_data="start_game")],
                [InlineKeyboardButton("🔄 더 기다리기", callback_data="wait_more")],
                [InlineKeyboardButton("❌ 게임 취소", callback_data="cancel_game")]
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("🔄 참가자 대기 중...", callback_data="waiting")],
                [InlineKeyboardButton("❌ 게임 취소", callback_data="cancel_game")]
            ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        updated_message = f"""
🎮 바둑이 게임 대기실

👥 참가자 ({player_count}명):
{', '.join(player_names)}

{"🎯 게임 시작 가능!" if player_count >= 2 else "⏰ 최소 2명이 필요합니다."}
        """
        
        await query.edit_message_text(updated_message, reply_markup=reply_markup)
    
    elif query.data == "start_game":
        if len(game.players) < 2:
            await query.edit_message_text("❌ 최소 2명이 필요합니다!")
            return
        
        # 실제 게임 시작
        player_hands = game.deal_cards(len(game.players))
        player_ids = list(game.players.keys())
        
        # 각 플레이어에게 카드 할당
        for i, player_id in enumerate(player_ids):
            game.players[player_id]['hand'] = player_hands[i]
        
        # 게임 시작 메시지
        await query.edit_message_text("🎮 게임이 시작되었습니다! 각자 개인 메시지를 확인하세요!")
        
        # 각 플레이어에게 개인 메시지로 카드 전송
        for player_id in game.players:
            try:
                hand = game.players[player_id]['hand']
                hand_type, rank_value, valid_cards = game.evaluate_hand(hand)
                
                cards_text = " ".join(str(card) for card in hand)
                valid_cards_text = " ".join(str(card) for card in valid_cards)
                
                private_message = f"""
🃏 당신의 카드:

📇 받은 카드: {cards_text}
🎯 현재 족보: {hand_type}
✨ 유효 카드: {valid_cards_text}
📊 점수: {rank_value:.1f}

💰 보유 칩: {game.players[player_id]['chips']:,}개

🎮 게임이 진행 중입니다...
                """
                
                await context.bot.send_message(chat_id=player_id, text=private_message)
            except Exception as e:
                logger.error(f"개인 메시지 전송 실패: {e}")
    
    elif query.data == "cancel_game":
        game.game_active = False
        game.players.clear()
        await query.edit_message_text("❌ 게임이 취소되었습니다.")

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
    application.add_handler(CommandHandler("rules", rules))
    application.add_handler(CommandHandler("test_hand", test_hand))
    application.add_handler(CommandHandler("game_start", game_start))
    
    # 버튼 핸들러 등록
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("🤖 바둑이 봇이 시작되었습니다!")
    
    # 봇 실행
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
