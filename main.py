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

# 게임 상태 상수
GAME_STATES = {
    'WAITING': 'waiting',
    'DEALING': 'dealing', 
    'BETTING_1': 'betting_1',
    'EXCHANGE_1': 'exchange_1',
    'BETTING_2': 'betting_2',
    'EXCHANGE_2': 'exchange_2', 
    'BETTING_3': 'betting_3',
    'EXCHANGE_3': 'exchange_3',
    'FINAL_BETTING': 'final_betting',
    'SHOWDOWN': 'showdown',
    'FINISHED': 'finished'
}

# 게임 클래스
class BadugiGame:
    def __init__(self):
        self.players = {}  # user_id: player_data
        self.deck = []
        self.game_active = False
        self.current_state = GAME_STATES['WAITING']
        self.current_player_index = 0
        self.pot = 0
        self.current_bet = 0
        self.round_bets = {}  # user_id: bet_amount
        self.folded_players = set()
        self.chat_id = None
        self.exchange_round = 0
        self.selected_cards = {}  # user_id: [selected_indices]
        self.exchange_completed = set()  # user_id who completed exchange
        self.betting_completed = set()  # user_id who completed betting
        
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
            rank_type = "세컨"
        elif card_count == 2:
            rank_type = "써드"
        else:
            rank_type = "베이스"
        
        # 순위 계산 (카드 개수가 많을수록, 숫자가 낮을수록 좋음)
        rank_sum = sum(card.rank if card.rank != 1 else 0.5 for card in valid_cards)
        final_rank = (4 - card_count) * 1000 + rank_sum
        
        return rank_type, final_rank, valid_cards
    
    def get_active_players(self):
        """폴드하지 않은 플레이어 목록"""
        return [pid for pid in self.players.keys() if pid not in self.folded_players]
    
    def get_current_player_id(self):
        """현재 턴 플레이어 ID"""
        active_players = self.get_active_players()
        if not active_players:
            return None
        return active_players[self.current_player_index % len(active_players)]
    
    def next_player(self):
        """다음 플레이어로 턴 이동"""
        active_players = self.get_active_players()
        if len(active_players) > 1:
            self.current_player_index = (self.current_player_index + 1) % len(active_players)
    
    def reset_round_bets(self):
        """라운드 베팅 초기화"""
        self.round_bets = {pid: 0 for pid in self.players.keys()}
        self.current_bet = 0
    
    def is_betting_complete(self):
        """베팅 라운드 완료 확인"""
        active_players = self.get_active_players()
        if len(active_players) <= 1:
            return True
        
        # 모든 active 플레이어가 베팅을 완료했는지 확인
        for player_id in active_players:
            if player_id not in self.betting_completed:
                return False
        
        # 모든 플레이어가 같은 금액을 베팅했는지 확인 (폴드한 플레이어 제외)
        betting_amounts = []
        for player_id in active_players:
            if player_id not in self.folded_players:
                betting_amounts.append(self.round_bets.get(player_id, 0))
        
        return len(set(betting_amounts)) <= 1
    
    def is_exchange_complete(self):
        """카드 교환 라운드 완료 확인"""
        active_players = self.get_active_players()
        return len(self.exchange_completed) >= len(active_players)
    
    def reset_exchange_round(self):
        """교환 라운드 초기화"""
        self.selected_cards.clear()
        self.exchange_completed.clear()
        self.current_player_index = 0

# 전역 게임 인스턴스
game = BadugiGame()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """봇 시작 명령어"""
    welcome_message = """
🎮 완전한 바둑이 게임봇에 오신 것을 환영합니다!

📋 게임 명령어:
/game_start - 새 게임 시작
/game_stop - 게임 강제 종료
/game_status - 현재 게임 상태 확인
/game_reset - 게임 완전 리셋

🃏 기타 명령어:
/test_hand - 테스트 카드 받기
/rules - 게임 룰 설명
/help - 도움말

🎯 완전한 바둑이 게임을 즐기세요!
베팅, 카드 교환, 승부까지 모든 기능이 포함되어 있습니다.
    """
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """도움말 명령어"""
    help_text = """
🎯 바둑이 게임봇 도움말

🃏 바둑이 족보 (좋은 순서):
1️⃣ 골프 바둑이: A♠2♣3♦4♥ (최고의 패)
2️⃣ 메이드: 무늬 4개, 숫자 4개 모두 다름
3️⃣ 세컨: 3장만 유효 (1장 중복)
4️⃣ 써드: 2장만 유효 (2장 중복)
5️⃣ 베이스: 1장만 유효 (3장 중복)

🎮 게임 진행:
1. /game_start로 게임 시작
2. 참가 버튼으로 참여 (2~4명)
3. 💰 참가비 500칩 자동 차감
4. 카드 4장 받기
5. 베팅 → 카드교환 → 베팅 (3라운드)
6. 최종 베팅 후 승부 결정

💰 베팅 액션:
• 체크: 베팅하지 않고 넘기기
• 콜: 상대방과 같은 금액 베팅
• 레이즈: 더 많은 금액 베팅
• 올인: 모든 칩 베팅
• 🚪 다이: 게임 포기 (언제든지 가능)

🔄 카드 교환:
• 라운드마다 0~4장 교환 가능
• 더 좋은 족보를 만들기 위해 사용

💡 팁: 낮은 숫자일수록 좋습니다!
    """
    await update.message.reply_text(help_text)

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """게임 룰 설명"""
    rules_text = """
📖 완전한 바둑이 게임 룰

🎯 목표: 4장의 카드로 가장 좋은 족보 만들기

💰 게임 시작:
• 참가비(앤티): 500칩 자동 차감
• 모든 플레이어가 참가비를 내고 시작
• 참가비가 초기 팟머니가 됨

🎮 게임 진행 순서:
1️⃣ 카드 4장 딜링
2️⃣ 1차 베팅 라운드
3️⃣ 1차 카드 교환 (0~4장)
4️⃣ 2차 베팅 라운드
5️⃣ 2차 카드 교환 (0~4장)
6️⃣ 3차 베팅 라운드
7️⃣ 3차 카드 교환 (0~4장)
8️⃣ 최종 베팅 라운드
9️⃣ 쇼다운 (결과 공개)

💰 베팅 시스템:
• 시작 칩: 10,000개
• 참가비: 500칩 (자동 차감)
• 기본 레이즈: 100칩, 500칩, 1000칩
• 🚪 다이: 언제든지 게임 포기 가능
• 팟머니는 승자가 가져감

🔄 카드 교환:
• 각 라운드마다 0~4장 교환 가능
• 교환하지 않아도 됨 (스테이)
• 새 카드는 덱에서 랜덤하게

🏆 승부 결정:
1. 족보 종류 (메이드 > 세컨 > 써드 > 베이스)
2. 같은 족보면 낮은 숫자가 승리
3. 마지막까지 남은 플레이어가 승리

💡 전략 팁:
• A(에이스)가 가장 좋은 카드
• 무늬와 숫자가 겹치지 않게 관리
• 상대방의 베팅 패턴 관찰
• 다이 타이밍이 중요함
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
• 세컨: 3장만 유효
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
    game.current_state = GAME_STATES['WAITING']
    game.chat_id = update.effective_chat.id
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
💰 참가비: 500칩 (자동 차감)
🏆 시작 칩: 10,000개

💡 참가하려면 "게임 참가하기" 버튼을 클릭하세요!
🔥 완전한 바둑이: 앤티 + 베팅 + 카드교환 + 다이!

⚠️ 모든 플레이어가 500칩 이상 보유해야 합니다.
    """
    
    await update.message.reply_text(start_message, reply_markup=reply_markup)

async def game_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """게임 강제 종료"""
    user = update.effective_user
    
    if not game.game_active and not game.players:
        await update.message.reply_text("❌ 현재 진행 중인 게임이 없습니다.")
        return
    
    # 게임 초기화
    game.game_active = False
    game.players.clear()
    game.current_state = GAME_STATES['WAITING']
    game.folded_players.clear()
    game.pot = 0
    game.betting_completed.clear()
    game.exchange_completed.clear()
    game.selected_cards.clear()
    
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
        active_players = game.get_active_players()
        current_player_id = game.get_current_player_id()
        current_player_name = game.players.get(current_player_id, {}).get('name', '없음')
        
        status_message = f"""
📊 게임 상태: {game.current_state}

👥 참가자 ({len(game.players)}명):
{', '.join(player_names) if player_names else '없음'}

💰 팟머니: {game.pot:,}칩
🎯 현재 턴: {current_player_name}
⚡ 활성 플레이어: {len(active_players)}명

🛠️ 관리 명령어:
/game_stop - 게임 강제 종료
/game_reset - 완전 리셋
        """
    
    await update.message.reply_text(status_message)

async def game_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """게임 완전 리셋 (관리자용)"""
    user = update.effective_user
    
    # 모든 게임 데이터 초기화
    game.game_active = False
    game.players.clear()
    game.deck.clear()
    game.current_state = GAME_STATES['WAITING']
    game.current_player_index = 0
    game.pot = 0
    game.current_bet = 0
    game.round_bets.clear()
    game.folded_players.clear()
    game.chat_id = None
    game.selected_cards.clear()
    game.exchange_completed.clear()
    game.betting_completed.clear()
    
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

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """인라인 키보드 버튼 처리"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    data = query.data
    
    if data == "join_game":
        await handle_join_game(query, user, context)
    elif data == "start_game":
        await handle_start_game(query, context)
    elif data == "cancel_game":
        await handle_cancel_game(query)
    elif data.startswith("bet_"):
        await handle_betting(query, user, context)
    elif data.startswith("exchange_"):
        await handle_card_exchange(query, user, context)
    elif data == "next_round":
        await handle_next_round(query, context)

async def handle_join_game(query, user, context):
    """게임 참가 처리"""
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

async def handle_start_game(query, context):
    """게임 시작 처리"""
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
    
    if failed_players:
        warning_message = f"""
⚠️ 개인 메시지 전송 실패!

❌ 다음 플레이어들이 봇과 개인 대화를 시작해야 합니다:
{', '.join(failed_players)}

📱 해결 방법:
1. 텔레그램에서 이 봇을 검색
2. "START" 버튼 클릭 또는 /start 전송
3. 모든 참가자가 완료 후 다시 게임 시작
        """
        
        keyboard = [
            [InlineKeyboardButton("🎮 다시 게임 시작", callback_data="start_game")],
            [InlineKeyboardButton("❌ 게임 취소", callback_data="cancel_game")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(warning_message, reply_markup=reply_markup)
        return
    
    # 게임 실제 시작
    await start_badugi_game(query, context)

async def start_badugi_game(query, context):
    """실제 바둑이 게임 시작"""
    # 게임 상태 설정
    game.current_state = GAME_STATES['DEALING']
    game.pot = 0
    game.reset_round_bets()
    game.folded_players.clear()
    
    # 앤티(참가비) 500칩 징수
    ante_amount = 500
    insufficient_players = []
    
    for player_id in game.players:
        player = game.players[player_id]
        if player['chips'] >= ante_amount:
            player['chips'] -= ante_amount
            game.pot += ante_amount
        else:
            insufficient_players.append(player['name'])
    
    # 칩 부족한 플레이어가 있으면 게임 취소
    if insufficient_players:
        error_message = f"""
❌ 참가비 부족으로 게임을 시작할 수 없습니다!

💰 참가비: {ante_amount}칩
❌ 칩 부족 플레이어: {', '.join(insufficient_players)}

💡 모든 플레이어가 최소 {ante_amount}칩 이상 보유해야 합니다.
        """
        await query.edit_message_text(error_message)
        
        # 이미 차감한 칩 되돌리기
        for player_id in game.players:
            player = game.players[player_id]
            if player['name'] not in insufficient_players:
                player['chips'] += ante_amount
        game.pot = 0
        return
    
    # 카드 딜링
    player_hands = game.deal_cards(len(game.players))
    player_ids = list(game.players.keys())
    
    # 각 플레이어에게 카드 할당
    for i, player_id in enumerate(player_ids):
        game.players[player_id]['hand'] = player_hands[i]
    
    # 게임 시작 알림 (앤티 정보 포함)
    ante_message = f"""
🎮 바둑이 게임이 시작되었습니다!

💰 참가비 징수 완료:
- 각자 {ante_amount}칩 차감
- 초기 팟머니: {game.pot:,}칩

🃏 카드가 딜링되었습니다. 1차 베팅 라운드를 시작합니다!
    """
    
    await query.edit_message_text(ante_message)
    
    # 각 플레이어에게 개인 메시지로 카드 전송
    for player_id in game.players:
        await send_player_status(context, player_id)
    
    # 1차 베팅 라운드 시작
    game.current_state = GAME_STATES['BETTING_1']
    await start_betting_round(context, "1차 베팅 라운드")

async def send_player_status(context, player_id):
    """플레이어에게 현재 상태 전송"""
    player = game.players[player_id]
    hand = player['hand']
    hand_type, rank_value, valid_cards = game.evaluate_hand(hand)
    
    cards_text = " ".join(str(card) for card in hand)
    valid_cards_text = " ".join(str(card) for card in valid_cards)
    
    is_current_player = game.get_current_player_id() == player_id
    
    message = f"""
🃏 {player['name']}님의 현재 상황:

📇 보유 카드: {cards_text}
🎯 현재 족보: {hand_type}
✨ 유효 카드: {valid_cards_text}
📊 점수: {rank_value:.1f}

💰 보유 칩: {player['chips']:,}개
💳 이번 라운드 베팅: {game.round_bets.get(player_id, 0):,}칩
🏆 팟머니: {game.pot:,}칩

🎮 게임 상태: {game.current_state}
{"🎯 당신의 턴입니다!" if is_current_player else "⏳ 다른 플레이어의 턴을 기다리는 중..."}
    """
    
    # 현재 플레이어에게만 액션 버튼 제공
    if is_current_player and game.current_state.startswith('betting'):
        keyboard = await get_betting_keyboard(player_id)
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id=player_id, text=message, reply_markup=reply_markup)
    elif is_current_player and game.current_state.startswith('exchange'):
        keyboard = await get_exchange_keyboard(player_id)
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id=player_id, text=message, reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=player_id, text=message)

async def get_betting_keyboard(player_id):
    """베팅 액션 키보드"""
    player = game.players[player_id]
    current_player_bet = game.round_bets.get(player_id, 0)
    call_amount = max(0, game.current_bet - current_player_bet)
    
    keyboard = []
    
    # 체크/콜
    if call_amount == 0:
        keyboard.append([InlineKeyboardButton("✅ 체크", callback_data="bet_check")])
    else:
        if player['chips'] >= call_amount:
            keyboard.append([InlineKeyboardButton(f"📞 콜 ({call_amount:,}칩)", callback_data="bet_call")])
        else:
            keyboard.append([InlineKeyboardButton("❌ 콜 불가 (칩부족)", callback_data="bet_insufficient")])
    
    # 레이즈 옵션들
    raise_buttons = []
    for raise_amount in [100, 500, 1000]:
        total_needed = call_amount + raise_amount
        if player['chips'] >= total_needed:
            raise_buttons.append(InlineKeyboardButton(f"⬆️ +{raise_amount}", callback_data=f"bet_raise_{raise_amount}"))
    
    if raise_buttons:
        # 2개씩 나누어서 배치
        for i in range(0, len(raise_buttons), 2):
            keyboard.append(raise_buttons[i:i+2])
    
    # 올인
    if player['chips'] > call_amount:
        remaining_chips = player['chips'] - call_amount
        keyboard.append([InlineKeyboardButton(f"💥 올인 (+{remaining_chips:,}칩)", callback_data="bet_allin")])
    elif player['chips'] == call_amount and call_amount > 0:
        keyboard.append([InlineKeyboardButton(f"💥 올인 (콜)", callback_data="bet_allin")])
    
    # 다이 (폴드)
    keyboard.append([InlineKeyboardButton("🚪 다이", callback_data="bet_die")])
    
    return keyboard

async def get_exchange_keyboard(player_id):
    """카드 교환 키보드"""
    selected = game.selected_cards.get(player_id, [])
    player = game.players[player_id]
    
    # 카드별 버튼 (선택된 카드는 ✅ 표시)
    card_buttons = []
    for i in range(4):
        card = player['hand'][i]
        if i in selected:
            card_buttons.append(InlineKeyboardButton(f"✅ {i+1}번({card})", callback_data=f"exchange_toggle_{i}"))
        else:
            card_buttons.append(InlineKeyboardButton(f"◻️ {i+1}번({card})", callback_data=f"exchange_toggle_{i}"))
    
    keyboard = [
        card_buttons[:2],  # 1,2번 카드
        card_buttons[2:],  # 3,4번 카드
        [
            InlineKeyboardButton(f"🔄 선택한 {len(selected)}장 교환", callback_data="exchange_confirm"),
            InlineKeyboardButton("⏭️ 교환 안함 (스테이)", callback_data="exchange_skip")
        ]
    ]
    return keyboard

async def handle_betting(query, user, context):
    """베팅 액션 처리"""
    if not game.current_state.startswith('betting'):
        await query.answer("❌ 지금은 베팅 시간이 아닙니다!", show_alert=True)
        return
        
    if user.id in game.folded_players:
        await query.answer("❌ 이미 다이하셨습니다!", show_alert=True)
        return
        
    if user.id in game.betting_completed:
        await query.answer("❌ 이미 베팅을 완료하셨습니다!", show_alert=True)
        return

    action = query.data.split("_")[1]
    player = game.players[user.id]
    current_player_bet = game.round_bets.get(user.id, 0)
    
    bet_success = False
    action_message = ""
    
    if action == "check":
        if game.current_bet == current_player_bet:
            action_message = "✅ 체크했습니다."
            bet_success = True
        else:
            await query.answer("❌ 베팅이 있어서 체크할 수 없습니다. 콜하거나 다이하세요!", show_alert=True)
            return
            
    elif action == "call":
        call_amount = game.current_bet - current_player_bet
        if call_amount <= 0:
            await query.answer("❌ 콜할 베팅이 없습니다. 체크하세요!", show_alert=True)
            return
        if player['chips'] >= call_amount:
            player['chips'] -= call_amount
            game.round_bets[user.id] = game.current_bet
            game.pot += call_amount
            action_message = f"📞 {call_amount:,}칩 콜했습니다."
            bet_success = True
        else:
            await query.answer("❌ 칩이 부족합니다!", show_alert=True)
            return
            
    elif action.startswith("raise"):
        raise_amount = int(action.split("_")[1])
        new_bet = game.current_bet + raise_amount
        bet_diff = new_bet - current_player_bet
        
        if player['chips'] >= bet_diff:
            player['chips'] -= bet_diff
            game.round_bets[user.id] = new_bet
            game.current_bet = new_bet
            game.pot += bet_diff
            action_message = f"⬆️ {raise_amount:,}칩 레이즈했습니다. (총 베팅: {new_bet:,}칩)"
            bet_success = True
            
            # 레이즈 시 다른 플레이어들의 베팅 완료 상태 초기화 (본인 제외)
            game.betting_completed.clear()
        else:
            await query.answer("❌ 칩이 부족합니다!", show_alert=True)
            return
            
    elif action == "allin":
        all_chips = player['chips']
        if all_chips <= 0:
            await query.answer("❌ 올인할 칩이 없습니다!", show_alert=True)
            return
            
        total_bet = current_player_bet + all_chips
        player['chips'] = 0
        game.round_bets[user.id] = total_bet
        
        if total_bet > game.current_bet:
            game.current_bet = total_bet
            # 올인으로 레이즈된 경우 다른 플레이어들의 베팅 완료 상태 초기화
            game.betting_completed.clear()
            
        game.pot += all_chips
        action_message = f"💥 {all_chips:,}칩 올인했습니다! (총 베팅: {total_bet:,}칩)"
        bet_success = True
        
    elif action == "fold" or action == "die":
        game.folded_players.add(user.id)
        action_message = "🚪 다이했습니다. (게임 포기)"
        bet_success = True
    
    elif action == "insufficient":
        await query.answer("❌ 칩이 부족해서 콜할 수 없습니다!", show_alert=True)
        return
    
    if bet_success:
        # 베팅 완료 표시
        game.betting_completed.add(user.id)
        
        # 결과 메시지 업데이트
        player = game.players[user.id]
        result_message = f"""
{action_message}

💰 현재 상황:
- 보유 칩: {player['chips']:,}개
- 이번 라운드 베팅: {game.round_bets.get(user.id, 0):,}칩
- 현재 팟머니: {game.pot:,}칩
- 현재 최고 베팅: {game.current_bet:,}칩

✅ 액션이 완료되었습니다. 다른 플레이어를 기다리는 중...
        """
        
        await query.edit_message_text(result_message)
        
        # 다이한 플레이어가 있으면 그룹에 알림
        if action == "fold" or action == "die":
            await context.bot.send_message(
                chat_id=game.chat_id,
                text=f"🚪 {player['name']}님이 다이했습니다."
            )
        
        # 베팅 라운드 완료 확인
        if game.is_betting_complete():
            # 그룹 채팅에 라운드 완료 알림
            active_players = game.get_active_players()
            await context.bot.send_message(
                chat_id=game.chat_id,
                text=f"💰 베팅 라운드 완료! 총 팟머니: {game.pot:,}칩 (남은 플레이어: {len(active_players)}명)"
            )
            await advance_game_state(query, context)
        else:
            # 아직 베팅하지 않은 플레이어들에게 알림
            active_players = game.get_active_players()
            for player_id in active_players:
                if player_id not in game.betting_completed and player_id not in game.folded_players:
                    await send_betting_status(context, player_id)

async def send_betting_status(context, player_id):
    """플레이어에게 베팅 상태 전송"""
    player = game.players[player_id]
    current_player_bet = game.round_bets.get(player_id, 0)
    call_amount = max(0, game.current_bet - current_player_bet)
    
    message = f"""
🎰 {player['name']}님의 베팅 턴:

💰 현재 상황:
- 보유 칩: {player['chips']:,}개
- 이번 라운드 베팅: {current_player_bet:,}칩
- 현재 팟머니: {game.pot:,}칩
- 현재 최고 베팅: {game.current_bet:,}칩
- 콜하려면: {call_amount:,}칩

🎯 액션을 선택하세요:
💡 카드가 마음에 들지 않으면 언제든지 다이할 수 있습니다.
    """
    
    keyboard = await get_betting_keyboard(player_id)
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(chat_id=player_id, text=message, reply_markup=reply_markup)

async def handle_card_exchange(query, user, context):
    """카드 교환 처리"""
    if not game.current_state.startswith('exchange'):
        await query.answer("❌ 지금은 카드 교환 시간이 아닙니다!", show_alert=True)
        return
    
    if user.id in game.folded_players:
        await query.answer("❌ 폴드한 플레이어는 교환할 수 없습니다!", show_alert=True)
        return
    
    action_parts = query.data.split("_")
    action = action_parts[1]
    
    if action == "toggle":
        # 카드 선택/해제 토글
        card_index = int(action_parts[2])
        
        if user.id not in game.selected_cards:
            game.selected_cards[user.id] = []
        
        selected = game.selected_cards[user.id]
        
        if card_index in selected:
            selected.remove(card_index)
            await query.answer(f"◻️ {card_index + 1}번 카드 선택 해제")
        else:
            selected.append(card_index)
            await query.answer(f"✅ {card_index + 1}번 카드 선택")
        
        # 키보드 업데이트
        keyboard = await get_exchange_keyboard(user.id)
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 메시지 내용도 업데이트
        player = game.players[user.id]
        hand = player['hand']
        hand_type, rank_value, valid_cards = game.evaluate_hand(hand)
        
        cards_text = " ".join(str(card) for card in hand)
        selected_cards_text = ", ".join([f"{i+1}번({hand[i]})" for i in selected]) if selected else "없음"
        
        message = f"""
🃏 {player['name']}님의 카드 교환 ({game.exchange_round}차):

📇 현재 카드: {cards_text}
🎯 현재 족보: {hand_type} (점수: {rank_value:.1f})
✅ 선택한 카드: {selected_cards_text}

💡 교환할 카드를 선택하고 "교환" 버튼을 누르세요!
📊 낮은 점수가 좋은 패입니다.
        """
        
        await query.edit_message_text(message, reply_markup=reply_markup)
        
    elif action == "confirm":
        # 실제 카드 교환
        if user.id not in game.selected_cards:
            game.selected_cards[user.id] = []
        
        selected = game.selected_cards[user.id]
        player = game.players[user.id]
        
        if not selected:
            await query.answer("❌ 교환할 카드를 선택해주세요!", show_alert=True)
            return
        
        # 선택한 카드들을 새 카드로 교환
        exchanged_cards = []
        for card_index in sorted(selected, reverse=True):  # 뒤에서부터 교환
            if game.deck:
                old_card = player['hand'][card_index]
                new_card = game.deck.pop()
                player['hand'][card_index] = new_card
                exchanged_cards.append(f"{card_index+1}번: {old_card} → {new_card}")
        
        game.exchange_completed.add(user.id)
        
        # 교환 결과 메시지
        exchange_result = "\n".join(exchanged_cards)
        new_hand_type, new_rank_value, _ = game.evaluate_hand(player['hand'])
        
        result_message = f"""
🔄 카드 교환 완료!

🔀 교환된 카드:
{exchange_result}

🃏 새로운 카드: {" ".join(str(card) for card in player['hand'])}
🎯 새로운 족보: {new_hand_type} (점수: {new_rank_value:.1f})

✅ 교환이 완료되었습니다. 다른 플레이어를 기다리는 중...
        """
        
        await query.edit_message_text(result_message)
        
        # 모든 플레이어 교환 완료 확인
        if game.is_exchange_complete():
            await advance_game_state(query, context)
                
    elif action == "skip":
        # 카드 교환 건너뛰기
        game.exchange_completed.add(user.id)
        
        await query.edit_message_text("⏭️ 카드 교환을 건너뛰었습니다. 다른 플레이어를 기다리는 중...")
        
        # 모든 플레이어 교환 완료 확인
        if game.is_exchange_complete():
            await advance_game_state(query, context)

def is_exchange_complete():
    """카드 교환 라운드 완료 확인"""
    # 간단 구현: 모든 active 플레이어가 교환 완료했다고 가정
    return True

async def advance_game_state(query, context):
    """게임 상태 진행"""
    if game.current_state == GAME_STATES['BETTING_1']:
        game.current_state = GAME_STATES['EXCHANGE_1']
        game.exchange_round = 1
        game.reset_exchange_round()
        await start_exchange_round(context, "1차 카드 교환")
        
    elif game.current_state == GAME_STATES['EXCHANGE_1']:
        game.current_state = GAME_STATES['BETTING_2']
        game.reset_round_bets()
        game.current_player_index = 0
        await start_betting_round(context, "2차 베팅 라운드")
        
    elif game.current_state == GAME_STATES['BETTING_2']:
        game.current_state = GAME_STATES['EXCHANGE_2']
        game.exchange_round = 2
        game.reset_exchange_round()
        await start_exchange_round(context, "2차 카드 교환")
        
    elif game.current_state == GAME_STATES['EXCHANGE_2']:
        game.current_state = GAME_STATES['BETTING_3']
        game.reset_round_bets()
        game.current_player_index = 0
        await start_betting_round(context, "3차 베팅 라운드")
        
    elif game.current_state == GAME_STATES['BETTING_3']:
        game.current_state = GAME_STATES['EXCHANGE_3']
        game.exchange_round = 3
        game.reset_exchange_round()
        await start_exchange_round(context, "3차 카드 교환")
        
    elif game.current_state == GAME_STATES['EXCHANGE_3']:
        game.current_state = GAME_STATES['FINAL_BETTING']
        game.reset_round_bets()
        game.current_player_index = 0
        await start_betting_round(context, "최종 베팅 라운드")
        
    elif game.current_state == GAME_STATES['FINAL_BETTING']:
        await start_showdown(context)

async def start_betting_round(context, round_name):
    """베팅 라운드 시작"""
    # 그룹 채팅에 알림
    await context.bot.send_message(
        chat_id=game.chat_id,
        text=f"🎰 {round_name} 시작!\n💰 현재 팟머니: {game.pot:,}칩"
    )
    
    # 모든 active 플레이어에게 동시에 베팅 메시지 전송
    active_players = game.get_active_players()
    for player_id in active_players:
        if player_id not in game.folded_players:
            await send_betting_status(context, player_id)

async def send_exchange_status(context, player_id):
    """플레이어에게 카드 교환 상태 전송"""
    player = game.players[player_id]
    hand = player['hand']
    hand_type, rank_value, valid_cards = game.evaluate_hand(hand)
    
    cards_text = " ".join(str(card) for card in hand)
    selected = game.selected_cards.get(player_id, [])
    selected_cards_text = ", ".join([f"{i+1}번({hand[i]})" for i in selected]) if selected else "없음"
    
    message = f"""
🃏 {player['name']}님의 카드 교환 ({game.exchange_round}차):

📇 현재 카드: {cards_text}
🎯 현재 족보: {hand_type} (점수: {rank_value:.1f})
✅ 선택한 카드: {selected_cards_text}

💡 교환할 카드를 선택하고 "교환" 버튼을 누르세요!
📊 낮은 점수가 좋은 패입니다.
    """
    
    keyboard = await get_exchange_keyboard(player_id)
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(chat_id=player_id, text=message, reply_markup=reply_markup)

async def start_exchange_round(context, round_name):
    """카드 교환 라운드 시작"""
    # 그룹 채팅에 알림
    await context.bot.send_message(
        chat_id=game.chat_id,
        text=f"🔄 {round_name} 시작!\n카드를 교환해서 더 좋은 패를 만드세요!"
    )
    
    # 모든 active 플레이어에게 동시에 교환 메시지 전송
    active_players = game.get_active_players()
    for player_id in active_players:
        await send_exchange_status(context, player_id)

async def start_showdown(context):
    """최종 승부 및 결과 발표"""
    game.current_state = GAME_STATES['SHOWDOWN']
    
    # 폴드하지 않은 플레이어들 결과 계산
    active_players = game.get_active_players()
    results = []
    
    for player_id in active_players:
        player = game.players[player_id]
        hand_type, rank_value, valid_cards = game.evaluate_hand(player['hand'])
        results.append({
            'player_id': player_id,
            'name': player['name'],
            'hand': player['hand'],
            'hand_type': hand_type,
            'rank_value': rank_value,
            'valid_cards': valid_cards
        })
    
    # 승자 결정 (낮은 점수가 승리)
    results.sort(key=lambda x: x['rank_value'])
    winner = results[0]
    
    # 승자에게 팟머니 지급
    game.players[winner['player_id']]['chips'] += game.pot
    
    # 결과 메시지 생성
    result_message = "🏆 바둑이 게임 결과 🏆\n\n"
    
    for i, result in enumerate(results):
        cards_text = " ".join(str(card) for card in result['hand'])
        valid_cards_text = " ".join(str(card) for card in result['valid_cards'])
        
        if i == 0:
            result_message += f"🥇 승자: {result['name']}\n"
        else:
            result_message += f"🥈 {result['name']}\n"
            
        result_message += f"   🃏 카드: {cards_text}\n"
        result_message += f"   🎯 족보: {result['hand_type']}\n"
        result_message += f"   ✨ 유효카드: {valid_cards_text}\n"
        result_message += f"   📊 점수: {result['rank_value']:.1f}\n\n"
    
    result_message += f"💰 승자가 획득한 팟머니: {game.pot:,}칩\n"
    result_message += f"🎮 게임이 종료되었습니다!"
    
    # 결과 발표
    await context.bot.send_message(chat_id=game.chat_id, text=result_message)
    
    # 게임 종료
    game.current_state = GAME_STATES['FINISHED']
    game.game_active = False

async def handle_cancel_game(query):
    """게임 취소 처리"""
    game.game_active = False
    game.players.clear()
    game.current_state = GAME_STATES['WAITING']
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
    application.add_handler(CommandHandler("game_stop", game_stop))
    application.add_handler(CommandHandler("game_status", game_status))
    application.add_handler(CommandHandler("game_reset", game_reset))
    
    # 버튼 핸들러 등록
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("🤖 완전한 바둑이 봇이 시작되었습니다!")
    
    # 봇 실행
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
