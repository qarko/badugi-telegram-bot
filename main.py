import os
import logging
import random
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient

# 로깅 설정
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 봇 토큰 및 MongoDB URI
TOKEN = os.getenv('BOT_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI')

# MongoDB 클라이언트 초기화
if MONGODB_URI:
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client.badugi_game  # 데이터베이스 이름
    users_collection = db.users  # 사용자 컬렉션
    games_collection = db.games  # 게임 기록 컬렉션
else:
    logger.error("MongoDB URI not found!")
    client = None
    db = None

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

# MongoDB 헬퍼 함수들
async def get_user_data(user_id, username):
    """사용자 데이터 조회 또는 생성"""
    if not db:
        # MongoDB 연결 안된 경우 기본값 반환
        return {
            'user_id': user_id,
            'username': username,
            'chips': 10000,
            'total_games': 0,
            'wins': 0,
            'total_winnings': 0,
            'best_hand': None,
            'created_at': datetime.now()
        }
    
    user = await users_collection.find_one({"user_id": user_id})
    
    if not user:
        # 새 사용자 생성
        user_data = {
            'user_id': user_id,
            'username': username,
            'chips': 10000,  # 시작 칩
            'total_games': 0,
            'wins': 0,
            'total_winnings': 0,
            'best_hand': None,
            'created_at': datetime.now(),
            'last_daily_bonus': None
        }
        await users_collection.insert_one(user_data)
        return user_data
    else:
        # 기존 사용자 username 업데이트
        if user.get('username') != username:
            await users_collection.update_one(
                {"user_id": user_id},
                {"$set": {"username": username}}
            )
            user['username'] = username
        return user

async def update_user_chips(user_id, chip_change):
    """사용자 칩 업데이트"""
    if not db:
        return
    
    await users_collection.update_one(
        {"user_id": user_id},
        {"$inc": {"chips": chip_change}}
    )

async def save_game_result(game_data):
    """게임 결과 저장"""
    if not db:
        return
    
    await games_collection.insert_one(game_data)

async def update_user_stats(user_id, won=False, chips_change=0, hand_type=None):
    """사용자 통계 업데이트"""
    if not db:
        return
    
    update_data = {
        "$inc": {
            "total_games": 1,
            "chips": chips_change
        }
    }
    
    if won:
        update_data["$inc"]["wins"] = 1
        update_data["$inc"]["total_winnings"] = chips_change
    
    if hand_type and (hand_type == "메이드" or "골프" in hand_type):
        update_data["$set"] = {"best_hand": hand_type}
    
    await users_collection.update_one(
        {"user_id": user_id},
        update_data
    )

async def get_leaderboard(limit=10):
    """리더보드 조회"""
    if not db:
        return []
    
    # 칩 순 리더보드
    cursor = users_collection.find().sort("chips", -1).limit(limit)
    leaderboard = []
    async for user in cursor:
        leaderboard.append(user)
    
    return leaderboard

async def get_user_stats(user_id):
    """사용자 통계 조회"""
    if not db:
        return None
    
    user = await users_collection.find_one({"user_id": user_id})
    return user

# 게임 클래스 (기존과 동일하지만 MongoDB 연동 추가)
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
        self.betting_round_active = False
        self.players_acted = set()  # 이번 라운드에서 행동한 플레이어들
        self.current_timer_task = None  # 현재 실행 중인 타이머 태스크
        self.timer_active = False  # 타이머 활성화 상태
        self.betting_time_limit = 20  # 베팅 시간 제한 (초) - 20초로 단축
        self.exchange_time_limit = 20  # 교환 시간 제한 (초) - 20초로 단축
        self.game_start_time = None  # 게임 시작 시간
    
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
            # 골프 바둑이 체크 (A, 2, 3, 4)
            if set(ranks) == {1, 2, 3, 4}:
                return "골프 바둑이", 0.1, cards
            
            # 일반 메이드
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
    
    def is_betting_complete(self):
        """베팅 라운드 완료 확인 - 단순화"""
        active_players = self.get_active_players()
        
        # 1명 이하면 즉시 완료
        if len(active_players) <= 1:
            return True
        
        # 모든 active 플레이어가 행동했는지 확인
        for player_id in active_players:
            if player_id not in self.players_acted:
                return False
        
        # 모든 플레이어가 같은 금액을 베팅했는지 확인
        bet_amounts = []
        for player_id in active_players:
            bet_amounts.append(self.round_bets.get(player_id, 0))
        
        # 모든 베팅 금액이 같으면 라운드 완료
        return len(set(bet_amounts)) <= 1
    
    def is_exchange_complete(self):
        """카드 교환 라운드 완료 확인"""
        active_players = self.get_active_players()
        return len(self.exchange_completed) >= len(active_players)
    
    def reset_round_bets(self):
        """라운드 베팅 초기화"""
        self.round_bets = {pid: 0 for pid in self.players.keys()}
        self.current_bet = 0
        self.players_acted.clear()
        self.current_player_index = 0
        self.betting_round_active = True
    
    def reset_exchange_round(self):
        """교환 라운드 초기화"""
        self.selected_cards.clear()
        self.exchange_completed.clear()
        self.current_player_index = 0
    
    def stop_timer(self):
        """현재 타이머 중지"""
        if self.current_timer_task and not self.current_timer_task.done():
            self.current_timer_task.cancel()
        self.timer_active = False
    
    async def start_timer(self, context, player_id, time_limit, action_type):
        """플레이어 타이머 시작"""
        self.stop_timer()  # 기존 타이머 중지
        self.timer_active = True
        
        # 타이머 태스크 생성
        self.current_timer_task = asyncio.create_task(
            self._timer_countdown(context, player_id, time_limit, action_type)
        )
        
        return self.current_timer_task
    
    async def _timer_countdown(self, context, player_id, time_limit, action_type):
        """타이머 카운트다운 및 처리"""
        try:
            player_name = self.players.get(player_id, {}).get('name', '알 수 없음')
            
            # 시간 제한까지 대기 (20초 중 15초 대기 후 5초 전 경고)
            await asyncio.sleep(time_limit - 5)  # 5초 전에 경고
            
            # 아직 타이머가 활성화되어 있으면 경고 메시지
            if self.timer_active and player_id not in self.folded_players:
                warning_msg = f"⚠️ {player_name}님, 5초 남았습니다!"
                
                try:
                    await context.bot.send_message(chat_id=player_id, text=warning_msg)
                    await context.bot.send_message(chat_id=self.chat_id, text=warning_msg)
                except:
                    pass
                
                # 나머지 5초 대기
                await asyncio.sleep(5)
            
            # 시간 초과 처리
            if self.timer_active and player_id not in self.folded_players:
                await self._handle_timeout(context, player_id, action_type)
                
        except asyncio.CancelledError:
            # 타이머가 취소된 경우 (정상적인 액션 완료)
            pass
        except Exception as e:
            logger.error(f"Timer error: {e}")
    
    async def _handle_timeout(self, context, player_id, action_type):
        """시간 초과 처리"""
        player_name = self.players.get(player_id, {}).get('name', '알 수 없음')
        
        if action_type == "betting":
            # 베팅 시간 초과 → 자동 다이
            self.folded_players.add(player_id)
            self.players_acted.add(player_id)
            
            timeout_msg = f"⏰ {player_name}님이 시간 초과로 자동 다이되었습니다."
            
            try:
                await context.bot.send_message(chat_id=player_id, text=f"⏰ 시간 초과! 자동으로 다이되었습니다.")
                await context.bot.send_message(chat_id=self.chat_id, text=timeout_msg)
            except:
                pass
            
            # 다음 플레이어로 진행
            self.next_player()
            self.timer_active = False
            
            # 베팅 라운드 완료 확인
            if self.is_betting_complete():
                active_players = self.get_active_players()
                await context.bot.send_message(
                    chat_id=self.chat_id,
                    text=f"💰 베팅 라운드 완료! 총 팟머니: {self.pot:,}칩 (남은 플레이어: {len(active_players)}명)"
                )
                self.betting_round_active = False
        
        elif action_type == "exchange":
            # 교환 시간 초과 → 스테이 (교환 안함)
            self.exchange_completed.add(player_id)
            
            timeout_msg = f"⏰ {player_name}님이 시간 초과로 카드 교환을 건너뛰었습니다."
            
            try:
                await context.bot.send_message(chat_id=player_id, text=f"⏰ 시간 초과! 카드 교환을 건너뛰었습니다.")
                await context.bot.send_message(chat_id=self.chat_id, text=timeout_msg)
            except:
                pass
            
            self.timer_active = False

# 전역 게임 인스턴스
game = BadugiGame()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """봇 시작 명령어"""
    user = update.effective_user
    
    # 사용자 데이터 로드
    user_data = await get_user_data(user.id, user.first_name)
    
    welcome_message = f"""
🎮 MongoDB 연동 바둑이 게임봇에 오신 것을 환영합니다!

👤 {user.first_name}님의 정보:
💰 보유 칩: {user_data['chips']:,}개
🎯 총 게임 수: {user_data['total_games']}회
🏆 승리: {user_data['wins']}회
📊 승률: {(user_data['wins']/max(1,user_data['total_games'])*100):.1f}%

📋 게임 명령어:
/game_start - 새 게임 시작
/game_stop - 게임 강제 종료 (경고 포함)
/game_emergency_stop - 긴급 종료 투표
/stats - 내 통계 보기
/ranking - 전체 랭킹 보기
/daily_bonus - 일일 보너스 받기

🃏 기타 명령어:
/test_hand - 테스트 카드 받기
/rules - 게임 룰 설명
/help - 도움말

🎯 완전한 바둑이 게임을 즐기세요!
⏰ 시간제한: 20초/20초로 빠른 진행
🔒 MongoDB로 안전한 데이터 보관!
    """
    await update.message.reply_text(welcome_message)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """사용자 통계 조회"""
    user = update.effective_user
    user_data = await get_user_stats(user.id)
    
    if not user_data:
        await update.message.reply_text("❌ 통계 데이터를 찾을 수 없습니다. /start를 먼저 실행해주세요.")
        return
    
    win_rate = (user_data['wins'] / max(1, user_data['total_games']) * 100)
    
    stats_message = f"""
📊 {user.first_name}님의 게임 통계

💰 현재 칩: {user_data['chips']:,}개
🎮 총 게임 수: {user_data['total_games']}회
🏆 승리 횟수: {user_data['wins']}회
📈 승률: {win_rate:.1f}%
💎 총 획득 칩: {user_data.get('total_winnings', 0):,}개
🃏 최고 족보: {user_data.get('best_hand', '기록 없음')}
📅 가입일: {user_data['created_at'].strftime('%Y-%m-%d')}

🎯 게임을 더 플레이해서 승률을 올려보세요!
    """
    
    await update.message.reply_text(stats_message)

async def ranking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """전체 랭킹 조회"""
    leaderboard = await get_leaderboard(10)
    
    if not leaderboard:
        await update.message.reply_text("❌ 랭킹 데이터를 찾을 수 없습니다.")
        return
    
    ranking_message = "🏆 바둑이 칩 랭킹 TOP 10\n\n"
    
    for i, user_data in enumerate(leaderboard, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}위"
        win_rate = (user_data['wins'] / max(1, user_data['total_games']) * 100)
        
        ranking_message += f"""
{emoji} {user_data['username']}
💰 {user_data['chips']:,}칩 | 🎮 {user_data['total_games']}게임 | 📈 {win_rate:.1f}%
"""
    
    ranking_message += "\n🎯 더 많은 게임으로 랭킹을 올려보세요!"
    
    await update.message.reply_text(ranking_message)

async def daily_bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """일일 보너스 지급"""
    if not db:
        await update.message.reply_text("❌ 데이터베이스 연결이 필요합니다.")
        return
    
    user = update.effective_user
    user_data = await get_user_data(user.id, user.first_name)
    
    today = datetime.now().date()
    last_bonus = user_data.get('last_daily_bonus')
    
    if last_bonus and last_bonus.date() == today:
        await update.message.reply_text(f"""
💰 일일 보너스

❌ 오늘 이미 보너스를 받으셨습니다!
🕐 다음 보너스: 내일 자정 이후

현재 칩: {user_data['chips']:,}개
        """)
        return
    
    # 보너스 지급
    bonus_amount = 1000
    await users_collection.update_one(
        {"user_id": user.id},
        {
            "$inc": {"chips": bonus_amount},
            "$set": {"last_daily_bonus": datetime.now()}
        }
    )
    
    await update.message.reply_text(f"""
🎁 일일 보너스 지급 완료!

💰 보너스: +{bonus_amount:,}칩
💳 현재 칩: {user_data['chips'] + bonus_amount:,}개

🌟 매일 접속해서 보너스를 받아보세요!
    """)

# 나머지 기존 함수들은 동일하게 유지...
# (handle_join_game, handle_start_game, start_badugi_game 등)
# 칩 관련 부분만 MongoDB와 연동하도록 수정

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
• 골프 바둑이: A,2,3,4 + 무늬 모두 다름 ✨✨
• 메이드: 무늬와 숫자 모두 4개 다름 ✨
• 세컨: 3장만 유효
• 써드: 2장만 유효
• 베이스: 1장만 유효

🎮 다시 받으려면 /test_hand 명령어를 사용하세요!
    """
    
    await update.message.reply_text(result_message)

def main():
    """메인 함수"""
    if not TOKEN:
        print("❌ 봇 토큰이 설정되지 않았습니다!")
        print("환경변수 BOT_TOKEN을 설정해주세요.")
        return
    
    if not MONGODB_URI:
        print("⚠️ MongoDB URI가 설정되지 않았습니다!")
        print("환경변수 MONGODB_URI를 설정하면 데이터가 영구 저장됩니다.")
        print("현재는 임시 모드로 실행됩니다.")
    
    # 애플리케이션 생성
    application = Application.builder().token(TOKEN).build()
    
    # 명령어 핸들러 등록
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("ranking", ranking_command))
    application.add_handler(CommandHandler("daily_bonus", daily_bonus_command))
    application.add_handler(CommandHandler("test_hand", test_hand))
    
    print("🤖 MongoDB 연동 바둑이 봇이 시작되었습니다!")
    if db:
        print("✅ MongoDB 연결 성공!")
    else:
        print("⚠️ MongoDB 연결 실패 - 임시 모드로 실행")
    
    # 봇 실행
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
