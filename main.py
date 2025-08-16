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
/game_stop - 게임 강제 종료
/game_status - 현재 게임 상태 확인
/game_reset - 게임 완전 리셋

🃏 기타 명령어:
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

🎮 게임 명령어:
/game_start - 새 게임 시작
/game_stop - 게임 강제 종료
/game_status - 현재 상태 확인
/game_reset - 완전 리셋

🔧 게임 방법:
1. /game_start로 게임 시작
2. 참가 버튼으로 참여
3. 2명 이상 모이면 게임 시작
4. 개인 메시지로 카드 확인

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

async def game_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """게임 강제 종료"""
    user = update.effective_user
    
    if not game.game_active and not game.players:
        await update.message.reply_text("❌ 현재 진행 중인 게임이 없습니다.")
        return
    
    # 게임 초기화
    game.game_active = False
    game.players.clear()
    
    stop_message = f"""
🛑 게임이 강제 종료되었습니다.

👤 종료 요청자: {user.first_name}
🔄 새 게임을 시작하려면 /game_start 명령어를 사용하세요.
    """
    
    await update.message.reply_text(stop_message)

async def game_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """현재 게임 상태 확인"""
    
    if not game.game_active and not game.players:
        status_message = """
📊 게임 상태: 대기 중

🎮 현재 진행 중인 게임이 없습니다.
🚀 새 게임을 시작하려면 /game_start 명령어를 사용하세요.
        """
    else:
        player_names = [game.players[pid]['name'] for pid in game.players]
        status_message = f"""
📊 게임 상태: {"진행 중" if game.game_active else "모집 중"}

👥 참가자 ({len(game.players)}명):
{', '.join(player_names) if player_names else '없음'}

🛠️ 관리 명령어:
/game_stop - 게임 강제 종료
/game_status - 현재 상태 확인
        """
    
    await update.message.reply_text(status_message)

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

async def game_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """게임 완전 리셋 (관리자용)"""
    user = update.effective_user
    
    # 모든 게임 데이터 초기화
    game.game_active = False
    game.players.clear()
    game.deck.clear()
    
    reset_message = f"""
🔄 게임이 완전히 리셋되었습니다.

👤 리셋 요청자: {user.first_name}
🧹 모든 게임 데이터가 초기화되었습니다.

🎮 게임 명령어:
/game_start - 새 게임 시작
/game_status - 게임 상태 확인
/game_stop - 게임 종료
    """
    
    await update.message.reply_text(reset_message)
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
        [InlineKeyboardButton("➕ 게임 참가하기", callback_data="join_game")],
        [InlineKeyboardButton("❌ 게임 취소", callback_data="cancel_game")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    start_message = f"""
🎮 새로운 바둑이 게임 모집 중!

👤 게임 호스트: {user.first_name}
👥 현재 참가자: 0/4명 
🎯 필요 인원: 최소 2명

💡 참가하려면 아래 "게임 참가하기" 버튼을 클릭하세요!
⏰ 다른 사람들도 이 메시지에서 바로 참가할 수 있습니다.
    """
    
    await update.message.reply_text(start_message, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """인라인 키보드 버튼 처리"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    if query.data == "join_game":
        if user.id in game.players:
            await query.answer("❌ 이미 게임에 참가하셨습니다!", show_alert=True)
            return
        
        if len(game.players) >= 4:
            await query.answer("❌ 게임이 가득 참! (최대 4명)", show_alert=True)
            return
        
        # 플레이어 추가
        game.players[user.id] = {
            'name': user.first_name,
            'hand': [],
            'chips': 10000
        }
        
        player_count = len(game.players)
        player_names = [game.players[pid]['name'] for pid in game.players]
        
        # 항상 참가 버튼 유지 (최대 4명까지)
        if player_count >= 4:
            keyboard = [
                [InlineKeyboardButton("🎮 게임 시작 (4명 풀방)", callback_data="start_game")],
                [InlineKeyboardButton("❌ 게임 취소", callback_data="cancel_game")]
            ]
        elif player_count >= 2:
            keyboard = [
                [InlineKeyboardButton("🎮 게임 시작", callback_data="start_game")],
                [InlineKeyboardButton("➕ 더 참가하기", callback_data="join_game")],
                [InlineKeyboardButton("❌ 게임 취소", callback_data="cancel_game")]
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("➕ 게임 참가하기", callback_data="join_game")],
                [InlineKeyboardButton("❌ 게임 취소", callback_data="cancel_game")]
            ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        updated_message = f"""
🎮 바둑이 게임 대기실

👥 현재 참가자 ({player_count}/4명):
{', '.join(player_names)}

💡 {f"게임 시작 가능! (2명 이상)" if player_count >= 2 else "최소 2명이 필요합니다."}
🔄 다른 사람들도 아래 버튼으로 참가할 수 있습니다!
        """
        
        await query.edit_message_text(updated_message, reply_markup=reply_markup)
    
    elif query.data == "start_game":
        if len(game.players) < 2:
            await query.edit_message_text("❌ 최소 2명이 필요합니다!")
            return
        
        # 개인 메시지 가능 여부 사전 체크
        failed_players = []
        for player_id in game.players:
            try:
                await context.bot.send_message(
                    chat_id=player_id, 
                    text="🔄 개인 메시지 테스트 중..."
                )
            except Exception as e:
                failed_players.append(game.players[player_id]['name'])
                logger.error(f"개인 메시지 전송 실패 ({player_id}): {e}")
        
        # 개인 메시지 실패한 플레이어가 있으면 경고
        if failed_players:
            warning_message = f"""
⚠️ 개인 메시지 전송 실패!

❌ 다음 플레이어들이 봇과 개인 대화를 시작해야 합니다:
{', '.join(failed_players)}

📱 해결 방법:
1. 텔레그램에서 이 봇을 검색
2. "START" 버튼 클릭 또는 /start 전송
3. 모든 참가자가 완료 후 다시 게임 시작

🔄 또는 아래 "공개 게임" 버튼으로 그룹에서 진행
            """
            
            keyboard = [
                [InlineKeyboardButton("🎮 다시 게임 시작", callback_data="start_game")],
                [InlineKeyboardButton("🌐 공개 게임 (그룹에서)", callback_data="public_game")],
                [InlineKeyboardButton("❌ 게임 취소", callback_data="cancel_game")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(warning_message, reply_markup=reply_markup)
            return
        
        # 모든 플레이어 개인 메시지 가능 - 게임 시작
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
    
    elif query.data == "public_game":
        # 그룹에서 공개로 게임 진행
        if len(game.players) < 2:
            await query.edit_message_text("❌ 최소 2명이 필요합니다!")
            return
            
        player_hands = game.deal_cards(len(game.players))
        player_ids = list(game.players.keys())
        
        # 각 플레이어에게 카드 할당
        for i, player_id in enumerate(player_ids):
            game.players[player_id]['hand'] = player_hands[i]
        
        # 공개 게임 결과 메시지
        result_message = "🎮 공개 바둑이 게임 결과:\n\n"
        
        for player_id in game.players:
            hand = game.players[player_id]['hand']
            hand_type, rank_value, valid_cards = game.evaluate_hand(hand)
            cards_text = " ".join(str(card) for card in hand)
            
            result_message += f"""
👤 {game.players[player_id]['name']}:
🃏 카드: {cards_text}
🎯 족보: {hand_type}
📊 점수: {rank_value:.1f}

"""
        
        # 승자 결정 (가장 낮은 점수)
        winner_id = min(game.players.keys(), 
                       key=lambda pid: game.evaluate_hand(game.players[pid]['hand'])[1])
        winner_name = game.players[winner_id]['name']
        
        result_message += f"🏆 승자: {winner_name}님!"
        
        await query.edit_message_text(result_message)
    
    elif query.data == "cancel_game":
        game.game_active = False
        game.players.clear()
        await query.edit_message_text("❌ 게임이 취소되었습니다.")
    
    elif query.data == "waiting" or query.data == "wait_more":
        await query.answer("다른 플레이어를 기다리는 중입니다... 🕐", show_alert=False)

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
    application.add_handler(CommandHandler("game_stop", game_stop))
    application.add_handler(CommandHandler("game_status", game_status))
    application.add_handler(CommandHandler("game_reset", game_reset))
    
    # 버튼 핸들러 등록
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("🤖 바둑이 봇이 시작되었습니다!")
    
    # 봇 실행
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
