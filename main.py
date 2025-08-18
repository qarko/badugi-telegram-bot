# main.py (v5.0 - 사이드팟 + 사용자 입력 레이즈 + DM 전용 인터랙션 + 출석 + 다중 스테이크 방 + 랜덤 칩 지급)
# ✅ 반영 목록
# - 관리자 체계: 최초 관리자(PRIMARY_ADMIN_ID=ADMIN_USER_ID)는 /관리자임명, /강제초기화 가능
#                 임명된 관리자(보조)는 /강제초기화만 가능
# - DM 전용 인터랙션: 패/액션 안내는 DM 우선(막히면 그룹/채널로 대체)
# - 배팅: 콜/폴드/레이즈(프리셋 + 사용자 입력 + 올인). 사이드팟 지원.
# - 라운드: 딜 → BET1 → EXC1 → BET2 → EXC2 → BET3(최종) → 쇼다운
# - 교환: 0~4장 가능(개인 DM에서 선택)
# - /출석: 하루 1회 1000칩 지급(기본). KST 기준.
# - /바둑이 [min_or_preset]: 스테이크 방 생성.
#     · 미지정(기본방): ante=10, min_chips=1000, join_bonus=50  (출석만으로도 플레이 가능)
#     · 숫자 예: /바둑이 500 → min_chips=500, ante=25 (min/20 규칙), join_bonus=50
# - 채팅 랜덤 칩 지급: 1~100칩, 낮은 확률/쿨다운으로 과도 지급 방지.

import os
import logging
import random
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set, Any
from datetime import datetime, timedelta, timezone

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.error import BadRequest, Forbidden

# ======= 로깅 =======
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("badugi-bot")

# ======= 환경변수 =======
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGODB_URI = os.getenv("MONGODB_URI")
PRIMARY_ADMIN_ID = int(os.getenv("ADMIN_USER_ID", "0"))

BETTING_SECONDS = int(os.getenv("BETTING_SECONDS", "20"))
EXCHANGE_SECONDS = int(os.getenv("EXCHANGE_SECONDS", "20"))
ANTE_DEFAULT = int(os.getenv("ANTE", "10"))
STARTING_CHIPS = int(os.getenv("STARTING_CHIPS", "200"))
MIN_PLAYERS = int(os.getenv("MIN_PLAYERS", "2"))
MAX_PLAYERS = int(os.getenv("MAX_PLAYERS", "6"))
MIN_CHIPS_DEFAULT = int(os.getenv("MIN_CHIPS_DEFAULT", "1000"))
JOIN_BONUS = int(os.getenv("JOIN_BONUS", "50"))
CHECKIN_REWARD = int(os.getenv("CHECKIN_REWARD", "1000"))

# 랜덤 칩 지급 (채팅)
GIVEAWAY_PROB = float(os.getenv("GIVEAWAY_PROB", "0.004"))  # 0.4%
GIVEAWAY_MIN = int(os.getenv("GIVEAWAY_MIN", "1"))
GIVEAWAY_MAX = int(os.getenv("GIVEAWAY_MAX", "100"))
GIVEAWAY_USER_COOLDOWN_MIN = int(os.getenv("GIVEAWAY_USER_COOLDOWN_MIN", "30"))
GIVEAWAY_CHAT_COOLDOWN_SEC = int(os.getenv("GIVEAWAY_CHAT_COOLDOWN_SEC", "90"))

# 레이즈 프리셋(버튼)
RAISE_CHOICES = [int(x) for x in os.getenv("RAISE_CHOICES", "10,20,50").split(",") if x.strip().isdigit()]

# KST 타임존
KST = timezone(timedelta(hours=9))

# ======= DB (MongoDB 또는 인메모리) =======
try:
    from motor.motor_asyncio import AsyncIOMotorClient
except Exception:
    AsyncIOMotorClient = None

class Storage:
    def __init__(self):
        self.is_db = False
        self._mem_users: Dict[int, Dict[str, Any]] = {}
        self._mem_admins: Set[int] = set()
        self._mem_checkin: Dict[int, str] = {}
        self._mem_last_giveaway_user: Dict[int, datetime] = {}
        self._mem_last_giveaway_chat: Dict[int, datetime] = {}
        if MONGODB_URI and AsyncIOMotorClient is not None:
            try:
                self._client = AsyncIOMotorClient(MONGODB_URI)
                self._db = self._client["badugi_bot"]
                self.is_db = True
                logger.info("MongoDB 연결 성공")
            except Exception as e:
                logger.warning(f"MongoDB 연결 실패 → 인메모리 사용: {e}")

    async def ensure_user(self, user_id: int, username: str = ""):
        if self.is_db:
            col = self._db["users"]
            if not await col.find_one({"_id": user_id}):
                await col.insert_one({"_id": user_id, "username": username, "chips": STARTING_CHIPS, "wins": 0, "games": 0})
        else:
            self._mem_users.setdefault(user_id, {"username": username, "chips": STARTING_CHIPS, "wins": 0, "games": 0})

    async def get_profile(self, user_id: int) -> Dict[str, Any]:
        if self.is_db:
            doc = await self._db["users"].find_one({"_id": user_id})
            if not doc:
                doc = {"username": "", "chips": STARTING_CHIPS, "wins": 0, "games": 0}
            return {"user_id": user_id, **doc}
        return {"user_id": user_id, **self._mem_users.get(user_id, {"username": "", "chips": STARTING_CHIPS, "wins": 0, "games": 0})}

    async def add_chips(self, user_id: int, delta: int):
        if self.is_db:
            await self._db["users"].update_one({"_id": user_id}, {"$inc": {"chips": delta}})
        else:
            await self.ensure_user(user_id)
            self._mem_users[user_id]["chips"] = self._mem_users[user_id].get("chips", STARTING_CHIPS) + delta

    async def record_game(self, user_id: int, win: bool):
        if self.is_db:
            inc = {"games": 1}
            if win:
                inc["wins"] = 1
            await self._db["users"].update_one({"_id": user_id}, {"$inc": inc})
        else:
            await self.ensure_user(user_id)
            self._mem_users[user_id]["games"] = self._mem_users[user_id].get("games", 0) + 1
            if win:
                self._mem_users[user_id]["wins"] = self._mem_users[user_id].get("wins", 0) + 1

    async def top_rank(self, limit: int = 10):
        if self.is_db:
            cur = self._db["users"].find({}, sort=[("chips", -1)], limit=limit)
            return [doc async for doc in cur]
        rows = [{"_id": uid, **d} for uid, d in self._mem_users.items()]
        rows.sort(key=lambda x: x.get("chips", 0), reverse=True)
        return rows[:limit]

    async def transfer(self, sender: int, receiver: int, amount: int) -> bool:
        if amount <= 0:
            return False
        s = await self.get_profile(sender)
        if s["chips"] < amount:
            return False
        await self.add_chips(sender, -amount)
        await self.ensure_user(receiver)
        await self.add_chips(receiver, +amount)
        return True

    # ===== 관리자 =====
    async def set_secondary_admin(self, target_id: int):
        if target_id == PRIMARY_ADMIN_ID:
            return
        if self.is_db:
            await self._db["admins"].update_one({"_id": target_id}, {"$set": {"secondary": True}}, upsert=True)
        else:
            self._mem_admins.add(target_id)

    async def is_primary_admin(self, user_id: int) -> bool:
        return PRIMARY_ADMIN_ID != 0 and user_id == PRIMARY_ADMIN_ID

    async def is_admin(self, user_id: int) -> bool:
        if await self.is_primary_admin(user_id):
            return True
        if self.is_db:
            doc = await self._db["admins"].find_one({"_id": user_id})
            return bool(doc and doc.get("secondary"))
        return user_id in self._mem_admins

    # ===== 출석 =====
    async def can_checkin(self, user_id: int) -> bool:
        today = datetime.now(KST).strftime("%Y-%m-%d")
        if self.is_db:
            doc = await self._db["checkin"].find_one({"_id": user_id})
            last = doc.get("last", "") if doc else ""
            return last != today
        last = self._mem_checkin.get(user_id, "")
        return last != today

    async def mark_checkin(self, user_id: int):
        today = datetime.now(KST).strftime("%Y-%m-%d")
        if self.is_db:
            await self._db["checkin"].update_one({"_id": user_id}, {"$set": {"last": today}}, upsert=True)
        else:
            self._mem_checkin[user_id] = today

    # ===== 랜덤 칩 지급 쿨다운 =====
    async def can_giveaway(self, chat_id: int, user_id: int) -> bool:
        now = datetime.now(KST)
        last_user = self._mem_last_giveaway_user.get(user_id)
        last_chat = self._mem_last_giveaway_chat.get(chat_id)
        if last_user and (now - last_user) < timedelta(minutes=GIVEAWAY_USER_COOLDOWN_MIN):
            return False
        if last_chat and (now - last_chat) < timedelta(seconds=GIVEAWAY_CHAT_COOLDOWN_SEC):
            return False
        return True

    async def mark_giveaway(self, chat_id: int, user_id: int):
        now = datetime.now(KST)
        self._mem_last_giveaway_user[user_id] = now
        self._mem_last_giveaway_chat[chat_id] = now

storage = Storage()

# ======= 게임 모델 =======
SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K"]
RANK_VALUE = {r: i for i, r in enumerate(RANKS)}  # A=0

@dataclass
class Player:
    user_id: int
    username: str
    hand: List[Tuple[str, str]] = field(default_factory=list)
    folded: bool = False
    current_bet: int = 0  # 현재 라운드의 내 베팅액
    total_put: int = 0    # 현재 라운드 총 기여액(사이드팟 계산용)

@dataclass
class GameRoom:
    chat_id: int
    host_id: int
    state: str = "LOBBY"  # LOBBY, DEAL, BET1, EXC1, BET2, EXC2, BET3, SHOWDOWN
    players: Dict[int, Player] = field(default_factory=dict)
    deck: List[Tuple[str, str]] = field(default_factory=list)

    # 스테이크 설정
    ante: int = ANTE_DEFAULT
    min_chips: int = MIN_CHIPS_DEFAULT
    join_bonus: int = JOIN_BONUS

    pot: int = 0
    turn_order: List[int] = field(default_factory=list)
    turn_index: int = 0
    current_bet: int = 0

    awaiting_user: Optional[int] = None
    awaiting_custom_raise: Optional[int] = None  # 사용자 입력 레이즈 대기 user id

rooms: Dict[int, GameRoom] = {}

# (chat_id, user_id) → 커스텀 레이즈 입력 대기 플래그
pending_custom_raise: Set[Tuple[int, int]] = set()

# ======= 유틸 =======

def format_hand(hand: List[Tuple[str, str]]) -> str:
    return " ".join([f"{r}{s}" for r, s in hand])


def badugi_rank_key(hand: List[Tuple[str, str]]):
    cards = sorted(hand, key=lambda c: RANK_VALUE[c[0]])
    chosen = []
    seen_r, seen_s = set(), set()
    for r, s in cards:
        if r in seen_r or s in seen_s:
            continue
        chosen.append((r, s))
        seen_r.add(r)
        seen_s.add(s)
        if len(chosen) == 4:
            break
    return (-len(chosen), [RANK_VALUE[r] for r, _ in chosen])


def heuristic_discards(hand: List[Tuple[str, str]], count: int) -> List[int]:
    if count <= 0:
        return []
    ranks = [r for r, _ in hand]
    suits = [s for _, s in hand]
    scored = []
    for i, (r, s) in enumerate(hand):
        score = RANK_VALUE[r]
        if ranks.count(r) > 1:
            score += 5
        if suits.count(s) > 1:
            score += 5
        scored.append((score, i))
    scored.sort(reverse=True)
    return [i for _, i in scored[:count]]

# ======= 콜백 키 =======
CB_JOIN = "join"
CB_START = "start"
CB_CALL = "call"
CB_FOLD = "fold"
CB_RAISE = "raise_"  # 뒤에 금액
CB_RAISE_CUSTOM = "raise_custom"
CB_EXC = {i: f"exch_{i}" for i in range(5)}

# ======= 명령어 =======
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await storage.ensure_user(user.id, user.username or user.full_name)
    prof = await storage.get_profile(user.id)
    await update.message.reply_text(
        (
            f"안녕하세요 {user.mention_html()}! 바둑이 봇입니다.\n"
            f"/바둑이 로 로비를 만들거나 참가하세요.\n"
            f"/내정보 /랭킹 /송금 <상대ID> <금액>\n"
            f"보유 칩: {prof['chips']}개"
        ),
        parse_mode="HTML",
    )


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await storage.ensure_user(user.id, user.username or user.full_name)
    prof = await storage.get_profile(user.id)
    wr = 0.0
    if prof.get("games", 0) > 0:
        wr = round(100.0 * prof.get("wins", 0) / prof.get("games", 1), 1)
    await update.message.reply_text(
        f"👤 {user.mention_html()}
칩: {prof['chips']}
전적: {prof.get('wins',0)}승 / {prof.get('games',0)}판 (승률 {wr}%)",
        parse_mode="HTML",
    )

async def cmd_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = await storage.top_rank(10)
    lines = ["🏆 칩 랭킹 Top 10"]
    for i, row in enumerate(top, 1):
        name = row.get("username") or str(row.get("_id") or row.get("user_id"))
        lines.append(f"{i}. {name} - {row.get('chips',0)}칩")
    await update.message.reply_text("
".join(lines))

async def cmd_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if len(context.args) < 2:
        await update.message.reply_text("사용법: /송금 <상대ID> <금액>")
        return
    try:
        target = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("숫자를 올바르게 입력해주세요.")
        return
    ok = await storage.transfer(user.id, target, amount)
    if ok:
        await update.message.reply_text(f"✅ {target}에게 {amount}칩 송금 완료")
    else:
        await update.message.reply_text("❌ 송금 실패 (잔액 부족/잘못된 금액)")

async def cmd_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await storage.ensure_user(user.id, user.username or user.full_name)
    if await storage.can_checkin(user.id):
        await storage.add_chips(user.id, CHECKIN_REWARD)
        await storage.mark_checkin(user.id)
        await update.message.reply_text(f"🎁 출석 체크 완료! +{CHECKIN_REWARD}칩 지급")
    else:
        await update.message.reply_text("오늘은 이미 출석하셨습니다. 내일 다시 시도해주세요.")

async def cmd_force_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await storage.is_admin(user.id):
        await update.message.reply_text("권한이 없습니다. (관리자 전용)")
        return
    chat_id = update.effective_chat.id
    if chat_id in rooms:
        del rooms[chat_id]
    await update.message.reply_text("방 상태 초기화 완료")

async def cmd_set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await storage.is_primary_admin(user.id):
        await update.message.reply_text("최초 관리자만 임명할 수 있습니다.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("사용법: /관리자임명 <유저ID>")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("유저ID는 숫자입니다.")
        return
    await storage.set_secondary_admin(target)
    await update.message.reply_text(f"관리자 임명 완료: {target}")

# 로비/시작 (/바둑이 [min_chips])
async def cmd_badugi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    await storage.ensure_user(user.id, user.username or user.full_name)

    # 스테이크 파싱
    if context.args and len(context.args) >= 1 and context.args[0].isdigit():
        min_chips = int(context.args[0])
        ante = max(ANTE_DEFAULT, max(10, min_chips // 20))  # 간단한 스케일링 규칙
    else:
        min_chips = MIN_CHIPS_DEFAULT
        ante = ANTE_DEFAULT

    room = rooms.get(chat_id)
    if not room:
        room = GameRoom(chat_id=chat_id, host_id=user.id, ante=ante, min_chips=min_chips, join_bonus=JOIN_BONUS)
        rooms[chat_id] = room
    else:
        # 로비가 아니면 대기
        if room.state != "LOBBY":
            await update.message.reply_text("현재 라운드 진행 중입니다. 잠시만 기다려주세요.")
            return
        # 로비라면 스테이크 재설정 허용(호스트/최초관리자)
        if user.id == room.host_id or await storage.is_primary_admin(user.id):
            room.ante = ante
            room.min_chips = min_chips
            room.join_bonus = JOIN_BONUS

    keyboard = [
        [InlineKeyboardButton("참가", callback_data=CB_JOIN)],
        [InlineKeyboardButton("시작", callback_data=CB_START)],
    ]
    current_players = ", ".join([p.username or str(pid) for pid, p in room.players.items()]) or "(없음)"
    await update.message.reply_text(
        f"🎲 바둑이 로비 생성!
"
        f"스테이크: ante {room.ante}, 최소 보유칩 {room.min_chips}, 참가 보너스 +{room.join_bonus}
"
        f"참가 인원: {len(room.players)}/{MAX_PLAYERS}
현재 참가자: {current_players}
호스트: {room.host_id}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

# ======= 버튼 콜백 =======
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id
    user = query.from_user

    room = rooms.get(chat_id)
    if not room:
        await query.edit_message_text("방이 존재하지 않습니다. /바둑이 로 다시 시작")
        return

    # JOIN/START
    if data == CB_JOIN:
        if room.state != "LOBBY":
            return
        if len(room.players) >= MAX_PLAYERS:
            return
        if user.id not in room.players:
            prof = await storage.get_profile(user.id)
            # 최소 보유칩 검사
            if prof["chips"] < room.min_chips:
                await query.edit_message_text(f"최소 {room.min_chips}칩 이상 보유해야 참가할 수 있습니다. /출석 으로 칩을 모아보세요.")
                return
            # 참가 보너스
            await storage.add_chips(user.id, room.join_bonus)
            room.players[user.id] = Player(user_id=user.id, username=user.username or user.full_name)
        await refresh_lobby(query.message, room)
        return

    if data == CB_START:
        if user.id != room.host_id and not await storage.is_primary_admin(user.id):
            await query.edit_message_text("호스트 또는 최초 관리자만 시작할 수 있습니다.")
            return
        if len(room.players) < MIN_PLAYERS:
            await query.edit_message_text("최소 2명 이상 필요합니다.")
            return
        await query.edit_message_text("게임을 시작합니다! DM을 확인하세요.")
        await start_round(context, room)
        return

    # 배팅/교환 액션 (턴 기반)
    pid = user.id
    if room.awaiting_user != pid:
        return

    if data == CB_CALL:
        await handle_call(context, room, pid)
        return

    if data == CB_FOLD:
        await handle_fold(context, room, pid)
        return

    if data.startswith(CB_RAISE):
        try:
            amt = data.split("_")[1]
            amount = 0 if amt == "allin" else int(amt)
        except Exception:
            return
        await handle_raise(context, room, pid, amount)
        return

    if data == CB_RAISE_CUSTOM:
        # DM으로 금액 입력 요청
        await prompt_custom_raise(context, room, pid)
        return

    # 교환
    if data.startswith("exch_"):
        try:
            cnt = int(data.split("_")[1])
        except Exception:
            cnt = 0
        await handle_exchange_choice(context, room, pid, max(0, min(4, cnt)))
        return

async def refresh_lobby(message, room: GameRoom):
    keyboard = [
        [InlineKeyboardButton("참가", callback_data=CB_JOIN)],
        [InlineKeyboardButton("시작", callback_data=CB_START)],
    ]
    current_players = ", ".join([p.username or str(pid) for pid, p in room.players.items()]) or "(없음)"
    try:
        await message.edit_text(
            f"🎲 바둑이 로비
스테이크: ante {room.ante}, 최소 보유칩 {room.min_chips}, 참가 보너스 +{room.join_bonus}
참가 인원: {len(room.players)}/{MAX_PLAYERS}
현재 참가자: {current_players}
호스트: {room.host_id}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except BadRequest:
        pass

# ======= 라운드 진행 =======
async def start_round(context: ContextTypes.DEFAULT_TYPE, room: GameRoom):
    room.state = "DEAL"
    room.pot = 0
    room.current_bet = 0
    room.make_deck()

    # 앤티 차감 + 패 DM
    to_kick = []
    for pid in list(room.players.keys()):
        p = room.players[pid]
        prof = await storage.get_profile(pid)
        if prof["chips"] < room.ante:
            to_kick.append(pid)
            continue
        await storage.add_chips(pid, -room.ante)
        room.pot += room.ante
        p.folded = False
        p.current_bet = 0
        p.total_put = 0
        p.hand = room.deal(4)
        try:
            await context.bot.send_message(pid, f"당신의 패: {format_hand(p.hand)}")
        except Forbidden:
            await context.bot.send_message(room.chat_id, f"DM 불가 → 공개: {p.username}의 패 {format_hand(p.hand)}")

    for pid in to_kick:
        await context.bot.send_message(room.chat_id, f"{room.players[pid].username} 님은 앤티 부족으로 제외")
        del room.players[pid]

    if len(room.players) < MIN_PLAYERS:
        await context.bot.send_message(room.chat_id, "인원 부족으로 라운드를 취소합니다.")
        room.state = "LOBBY"
        return

    room.turn_order = list(room.players.keys())
    random.shuffle(room.turn_order)

    await betting_round(context, room, phase="BET1", title="1차 배팅")
    if alive_count(room) < MIN_PLAYERS:
        await showdown(context, room)
        return

    await exchange_round(context, room, phase="EXC1", title="1차 교환")
    await betting_round(context, room, phase="BET2", title="2차 배팅")
    if alive_count(room) < MIN_PLAYERS:
        await showdown(context, room)
        return

    await exchange_round(context, room, phase="EXC2", title="2차 교환")
    await betting_round(context, room, phase="BET3", title="3차 배팅(최종)")
    await showdown(context, room)


def alive_count(room: GameRoom) -> int:
    return sum(1 for p in room.players.values() if not p.folded)

# ========== 배팅 라운드 (턴 + DM) ==========
async def betting_round(context: ContextTypes.DEFAULT_TYPE, room: GameRoom, phase: str, title: str):
    room.state = phase
    room.current_bet = 0
    for p in room.players.values():
        p.current_bet = 0
        p.total_put += 0  # 유지
    await context.bot.send_message(room.chat_id, f"🕒 {title} 시작! 각 플레이어의 DM을 확인하세요.")

    active = [pid for pid in room.turn_order if not room.players[pid].folded]
    if len(active) < 2:
        return

    while True:
        progressed = False
        for pid in list(active):
            player = room.players.get(pid)
            if not player or player.folded:
                continue
            need = max(0, room.current_bet - player.current_bet)

            # 버튼: 콜/폴드 + 프리셋 레이즈 + 사용자 입력 + 올인
            buttons = [[InlineKeyboardButton("콜", callback_data=CB_CALL), InlineKeyboardButton("폴드", callback_data=CB_FOLD)]]
            raise_row = []
            # 잔액 확인
            prof = await storage.get_profile(pid)
            mychips = prof["chips"]
            if mychips > need:
                for amt in RAISE_CHOICES:
                    if mychips >= need + amt:
                        raise_row.append(InlineKeyboardButton(f"+{amt}", callback_data=f"{CB_RAISE}{amt}"))
                raise_row.append(InlineKeyboardButton("올인", callback_data=f"{CB_RAISE}allin"))
                raise_row.append(InlineKeyboardButton("직접입력", callback_data=CB_RAISE_CUSTOM))
            buttons.append(raise_row)

            room.awaiting_user = pid
            # DM 발송
            try:
                await context.bot.send_message(pid, f"{title} — 현재콜 {room.current_bet} / 당신 필요 {need}
보유칩 {mychips}", reply_markup=InlineKeyboardMarkup(buttons))
            except Forbidden:
                # DM 불가 → 그룹으로 안내
                await context.bot.send_message(room.chat_id, f"{player.username} 님 DM 불가 → 여기서 선택", reply_markup=InlineKeyboardMarkup(buttons))

            try:
                await asyncio.wait_for(wait_until_turn_done(room, pid), timeout=BETTING_SECONDS)
            except asyncio.TimeoutError:
                # 자동 처리: 콜 가능하면 콜, 아니면 폴드
                if mychips >= need:
                    await handle_call(context, room, pid, silent=True)
                else:
                    await handle_fold(context, room, pid, silent=True)

            progressed = True

            # 종료 체크: 생존자 전원 current_bet 동일 or 1명만 생존
            if all_bets_equal(room) or alive_count(room) <= 1:
                room.awaiting_user = None
                return
        if not progressed:
            break


def all_bets_equal(room: GameRoom) -> bool:
    target = None
    for p in room.players.values():
        if p.folded:
            continue
        if target is None:
            target = p.current_bet
        elif p.current_bet != target:
            return False
    return True

async def wait_until_turn_done(room: GameRoom, pid: int):
    while room.awaiting_user == pid or room.awaiting_custom_raise == pid:
        await asyncio.sleep(0.2)

async def prompt_custom_raise(context: ContextTypes.DEFAULT_TYPE, room: GameRoom, pid: int):
    room.awaiting_custom_raise = pid
    pending_custom_raise.add((room.chat_id, pid))
    try:
        await context.bot.send_message(pid, "레이즈 금액을 숫자로 입력하세요(예: 125). 취소하려면 무시하세요.")
    except Forbidden:
        await context.bot.send_message(room.chat_id, f"{room.players[pid].username} 님, DM이 막혀있어 사용자 입력 레이즈를 사용할 수 없습니다.")
        room.awaiting_custom_raise = None
        pending_custom_raise.discard((room.chat_id, pid))

# DM에서 사용자 입력 금액 받기
async def on_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()
    if not text.isdigit():
        return
    # 어떤 방에서 대기 중인지 찾기
    for chat_id, room in rooms.items():
        if room.awaiting_custom_raise == user_id and (chat_id, user_id) in pending_custom_raise:
            amount = int(text)
            pending_custom_raise.discard((chat_id, user_id))
            room.awaiting_custom_raise = None
            await handle_raise(context, room, user_id, amount)
            return

# ========== 교환 라운드 (DM 우선) ==========
async def exchange_round(context: ContextTypes.DEFAULT_TYPE, room: GameRoom, phase: str, title: str):
    room.state = phase
    await context.bot.send_message(room.chat_id, f"🔁 {title} 시작! 각자 DM에서 0~4장 교환을 선택하세요.")

    active = [pid for pid in room.turn_order if not room.players[pid].folded]
    for pid in active:
        p = room.players[pid]
        room.awaiting_user = pid
        keyboard = [[InlineKeyboardButton(f"{i}장", callback_data=CB_EXC[i]) for i in range(0,5)]]
        try:
            await context.bot.send_message(pid, f"{title} — 현재 패: {format_hand(p.hand)}
교환할 장수를 선택하세요.", reply_markup=InlineKeyboardMarkup(keyboard))
        except Forbidden:
            await context.bot.send_message(room.chat_id, f"{p.username} DM 불가 → 여기서 교환 수 선택", reply_markup=InlineKeyboardMarkup(keyboard))
        try:
            await asyncio.wait_for(wait_until_turn_done(room, pid), timeout=EXCHANGE_SECONDS)
        except asyncio.TimeoutError:
            await handle_exchange_choice(context, room, pid, 0, silent=True)
    room.awaiting_user = None

async def handle_exchange_choice(context: ContextTypes.DEFAULT_TYPE, room: GameRoom, pid: int, count: int, silent: bool=False):
    p = room.players.get(pid)
    if not p or p.folded:
        room.awaiting_user = None
        return
    count = max(0, min(4, count))
    if count > 0:
        idxs = heuristic_discards(p.hand, count)
        idxs.sort(reverse=True)
        for i in idxs:
            if 0 <= i < len(p.hand):
                p.hand.pop(i)
        p.hand.extend(room.deal(count))
    if not silent:
        await context.bot.send_message(room.chat_id, f"{p.username} 교환 {count}장 완료")
    room.awaiting_user = None

# ========== 베팅 액션 ==========
async def handle_call(context: ContextTypes.DEFAULT_TYPE, room: GameRoom, pid: int, silent: bool=False):
    p = room.players.get(pid)
    if not p or p.folded:
        return
    need = max(0, room.current_bet - p.current_bet)
    prof = await storage.get_profile(pid)
    mychips = prof["chips"]
    # 사이드팟: 가진 만큼만 지불하고 올인 허용
    to_put = min(need, mychips)
    await storage.add_chips(pid, -to_put)
    p.current_bet += to_put
    p.total_put += to_put
    if to_put < need:
        # 콜 부족 → 올인 상태로 고정(추가 액션 불가), 그러나 폴드 아님
        pass
    if not silent:
        await context.bot.send_message(room.chat_id, f"{p.username} 콜({to_put})")
    room.awaiting_user = None
    # 현재콜 갱신 필요 없음(콜)

async def handle_fold(context: ContextTypes.DEFAULT_TYPE, room: GameRoom, pid: int, silent: bool=False):
    p = room.players.get(pid)
    if not p:
        return
    p.folded = True
    if not silent:
        await context.bot.send_message(room.chat_id, f"{p.username} 폴드")
    room.awaiting_user = None

async def handle_raise(context: ContextTypes.DEFAULT_TYPE, room: GameRoom, pid: int, amount: int):
    p = room.players.get(pid)
    if not p or p.folded:
        return
    need = max(0, room.current_bet - p.current_bet)
    prof = await storage.get_profile(pid)
    mychips = prof["chips"]

    if amount == 0:  # all-in
        to_put = mychips
    else:
        if amount <= 0:
            await context.bot.send_message(room.chat_id, "레이즈 금액은 양수여야 합니다.")
            return
        to_put = need + amount
        if to_put > mychips:
            await context.bot.send_message(room.chat_id, "잔액이 부족합니다. 더 작은 금액을 입력하세요.")
            return

    await storage.add_chips(pid, -to_put)
    p.current_bet += to_put
    p.total_put += to_put
    room.current_bet = max(room.current_bet, p.current_bet)
    await context.bot.send_message(room.chat_id, f"{p.username} 레이즈 → 현재콜 {room.current_bet}")
    room.awaiting_user = None

# ========== 쇼다운 + 사이드팟 분배 ==========
async def showdown(context: ContextTypes.DEFAULT_TYPE, room: GameRoom):
    room.state = "SHOWDOWN"
    alive = [p for p in room.players.values() if not p.folded]
    if not alive:
        await context.bot.send_message(room.chat_id, "모두 폴드하여 라운드 종료")
        room.state = "LOBBY"
        return

    # 사이드팟 계산
    pots = build_side_pots(room)

    # 결과 메시지(비공개 패였어도 쇼다운은 공개)
    lines = ["👑 쇼다운"]
    for p in alive:
        lines.append(f"- {p.username}: {format_hand(p.hand)} → 키 {badugi_rank_key(p.hand)}")

    # 각 팟에 대해 승자 판정 및 분배
    for i, pot in enumerate(pots, 1):
        elig = [room.players[pid] for pid in pot["eligible"] if not room.players[pid].folded]
        if not elig:
            continue
        ranked = sorted(elig, key=lambda x: badugi_rank_key(x.hand))
        best_key = badugi_rank_key(ranked[0].hand)
        winners = [p for p in ranked if badugi_rank_key(p.hand) == best_key]
        share = pot["amount"] // max(1, len(winners))
        for w in winners:
            await storage.add_chips(w.user_id, share)
            await storage.record_game(w.user_id, True)
        losers = [p for p in elig if p.user_id not in [w.user_id for w in winners]]
        for l in losers:
            await storage.record_game(l.user_id, False)
        lines.append(f"팟{i}: {pot['amount']}칩 → 승자 {', '.join(w.username for w in winners)} (각 {share})")

    await context.bot.send_message(room.chat_id, "
".join(lines))
    room.state = "LOBBY"
    await context.bot.send_message(room.chat_id, "새 라운드를 시작하려면 /바둑이 를 입력하세요.")

# 사이드팟 구성: 각 플레이어 total_put 기준으로 티어링
def build_side_pots(room: GameRoom) -> List[Dict[str, Any]]:
    contrib = {pid: p.total_put for pid, p in room.players.items() if not p.folded and p.total_put > 0}
    if not contrib:
        return [{"amount": room_pot_sum(room), "eligible": [pid for pid, p in room.players.items() if not p.folded]}]
    # unique levels
    levels = sorted(set(contrib.values()))
    pots = []
    prev = 0
    for lvl in levels:
        amount = 0
        eligible = []
        for pid, put in contrib.items():
            take = max(0, min(put, lvl) - prev)
            if take > 0:
                amount += take
                eligible.append(pid)
        if amount > 0:
            pots.append({"amount": amount, "eligible": eligible})
        prev = lvl
    # 남은 오버액(모두가 lvl 이상 낸 부분)
    # 실제로는 마지막 레벨 이상은 동일하게 들어간 금액이 없음 → 이미 분해됨
    # 앤티로 쌓인 초기 팟 반영: total_put에는 베팅만 포함. 앤티 합산 필요.
    ante_only = room_pot_sum(room) - sum(p.total_put for p in room.players.values())
    if ante_only > 0:
        # 앤티는 모든 생존자 자격
        elig_ante = [pid for pid, p in room.players.items() if not p.folded]
        if pots:
            pots[0]["amount"] += ante_only  # 가장 작은 팟에 합산
        else:
            pots.append({"amount": ante_only, "eligible": elig_ante})
    return pots

def room_pot_sum(room: GameRoom) -> int:
    # 총합 = 플레이어 베팅 총합 + (기존 room.pot에 매 라운드 더한 금액). 여기선 room.pot이 앤티 + 베팅 누적.
    return sum(p.total_put for p in room.players.values()) + room.pot

# ======= 에러 핸들러 & 앱 =======
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

# ======= 랜덤 칩 지급 핸들러 =======
async def on_any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not user or user.is_bot:
        return
    # 그룹/슈퍼그룹/채널에서만(개인 DM 제외)
    if chat.type == "private":
        return
    # 확률 + 쿨다운
    if random.random() < GIVEAWAY_PROB and await storage.can_giveaway(chat.id, user.id):
        amount = random.randint(GIVEAWAY_MIN, GIVEAWAY_MAX)
        await storage.ensure_user(user.id, user.username or user.full_name)
        await storage.add_chips(user.id, amount)
        await storage.mark_giveaway(chat.id, user.id)
        try:
            await context.bot.send_message(chat.id, f"🎉 @{user.username or user.full_name} 님 랜덤 보너스 +{amount}칩!")
        except Exception:
            await context.bot.send_message(chat.id, f"🎉 보너스 +{amount}칩 지급!")

# ======= 앱 빌드 =======

def build_app() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("환경변수 BOT_TOKEN 이 설정되어야 합니다.")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("내정보", cmd_info))
    app.add_handler(CommandHandler("랭킹", cmd_rank))
    app.add_handler(CommandHandler("송금", cmd_transfer))
    app.add_handler(CommandHandler("출석", cmd_checkin))
    app.add_handler(CommandHandler("강제초기화", cmd_force_reset))
    app.add_handler(CommandHandler("관리자임명", cmd_set_admin))
    app.add_handler(CommandHandler("바둑이", cmd_badugi))

    app.add_handler(CallbackQueryHandler(on_button))

    # DM 사용자 입력(커스텀 레이즈)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, on_private_text))

    # 랜덤 칩 지급: 모든 메시지 후크 (명령 제외)
    app.add_handler(MessageHandler(~filters.COMMAND & filters.ALL, on_any_message))

    app.add_error_handler(on_error)
    return app


def main():
    app = build_app()
    logger.info("🤖 바둑이 게임봇 v5.0 시작")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
