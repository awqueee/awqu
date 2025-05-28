import asyncio
import logging
import random
import bleach
from datetime import datetime, timedelta, date
from typing import List, Optional
from sqlalchemy import (
    Column, Date, Integer, String, Boolean, DateTime, ForeignKey,
    select, func, Text as SQLText
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, aliased

from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram import BaseMiddleware
from aiogram.types import Update
from typing import Callable, Dict, Any, Awaitable

API_TOKEN = '7799452151:AAGCCzzHg7vght2oOFTMyFcnVdkH2Phipnw'
ADMIN_IDS = [747885035]

logging.basicConfig(level=logging.INFO)

Base = declarative_base()
engine = create_async_engine('sqlite+aiosqlite:///giveaway.db', echo=False)
Session = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

allowed_tags = ['b', 'i', 'u', 's', 'code', 'a']

# --- Модели базы данных ---

class Giveaway(Base):
    __tablename__ = 'giveaways'
    id = Column(Integer, primary_key=True)
    text = Column(SQLText, nullable=False)
    winners_count = Column(Integer, nullable=False)
    end_time = Column(DateTime, nullable=False)
    completed = Column(Boolean, default=False, nullable=False)
    subscribe_channels = Column(String, default="")
    post_channel = Column(String, nullable=True)
    message_id = Column(Integer, nullable=True)
    chat_id = Column(String, nullable=True)

    participants = relationship("Participant", back_populates="giveaway", cascade="all, delete-orphan")
    winners = relationship("Winner", back_populates="giveaway", cascade="all, delete-orphan")

class Participant(Base):
    __tablename__ = 'participants'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    username = Column(String)
    giveaway_id = Column(Integer, ForeignKey('giveaways.id'), nullable=False)
    giveaway = relationship("Giveaway", back_populates="participants")

class Winner(Base):
    __tablename__ = 'winners'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    username = Column(String)
    giveaway_id = Column(Integer, ForeignKey('giveaways.id'), nullable=False)
    giveaway = relationship("Giveaway", back_populates="winners")

class User(Base):
    __tablename__ = 'users'
    user_id = Column(Integer, primary_key=True)
    username = Column(String, nullable=True)
    referred_by = Column(Integer, nullable=True)
    notify = Column(Boolean, default=True)
    registered_at = Column(Date, default=date.today)
    coins = Column(Integer, default=3)
    banned = Column(Boolean, default=False)
    ban_reason = Column(String, nullable=True)

# --- Middleware для банов ---

class BanFilterMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        user_id = None
        if hasattr(event, "from_user") and event.from_user:
            user_id = event.from_user.id
        elif hasattr(event, "message") and event.message and event.message.from_user:
            user_id = event.message.from_user.id
        elif hasattr(event, "callback_query") and event.callback_query and event.callback_query.from_user:
            user_id = event.callback_query.from_user.id

        if user_id is not None:
            async with Session() as session:
                user = await session.get(User, user_id)
                if user and user.banned:
                    reason = user.ban_reason or "Причина не указана."
                    text = f"⛔️ Вы забанены администрацией.\nПричина: {reason}"
                    if hasattr(event, "answer"):
                        try:
                            await event.answer(text, show_alert=True)
                        except Exception:
                            pass
                    elif hasattr(event, "message") and event.message:
                        try:
                            await event.message.answer(text)
                        except Exception:
                            pass
                    return
        return await handler(event, data)

# --- FSM States ---

class GiveawayStates(StatesGroup):
    awaiting_text = State()
    awaiting_winners_count = State()
    awaiting_duration = State()
    awaiting_subscribe_channels = State()
    awaiting_post_channel = State()
    awaiting_broadcast_text = State()

# --- Главное меню ---

@router.message(F.text == "⬅️ В меню")
async def back_to_menu(message: Message):
    kb = ReplyKeyboardBuilder()
    kb.button(text="👤 Профиль")
    kb.button(text="🎁 Активные розыгрыши")
    kb.button(text="📊 Моя статистика")
    kb.button(text="🏆 Топ победителей")
    kb.button(text="🕓 История розыгрышей")
    kb.button(text="🤝 Пригласить друга")
    kb.button(text="🛒 Магазин")
    kb.button(text="❓ FAQ")
    kb.button(text="🆘 Связь с администрацией")
    kb.adjust(2)
    await message.answer(
        "🏠 <b>Главное меню</b>\n"
        "Выбирай, что будем делать дальше! 😎👇",
        reply_markup=kb.as_markup(resize_keyboard=True),
        parse_mode=ParseMode.HTML
    )

# --- FAQ ---

@router.message(F.text == "❓ FAQ")
async def faq_menu(message: Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="Как участвовать?", callback_data="faq_how_to_participate")
    kb.button(text="Как получить выигрыш?", callback_data="faq_how_to_get_prize")
    kb.button(text="Как пригласить друга?", callback_data="faq_invite")
    kb.button(text="Остальные вопросы", callback_data="faq_other")
    kb.button(text="⬅️ В меню", callback_data="faq_back")
    kb.adjust(1)
    await message.answer(
        "❓ <b>FAQ — Часто задаваемые вопросы</b>\n"
        "👇 Жми на любой вопрос и получи ответ!",
        reply_markup=kb.as_markup(),
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data.startswith("faq_"))
async def faq_answer(callback: CallbackQuery):
    data = callback.data
    if data == "faq_how_to_participate":
        text = "Чтобы участвовать в розыгрыше, выберите активный розыгрыш и нажмите кнопку «Участвовать»."
    elif data == "faq_how_to_get_prize":
        text = "Победителям приходит личное уведомление. Для получения приза — свяжитесь с администрацией в основном меню бота."
    elif data == "faq_invite":
        text = "В разделе «Пригласить друга» найдите вашу уникальную ссылку и отправьте её друзьям."
    elif data == "faq_other":
        text = "Если не нашли ответа — напишите администрации через специальную кнопку в основном меню бота."
    elif data == "faq_back":
        await back_to_menu(callback.message)
        await callback.answer()
        return
    else:
        text = "Выберите вопрос из меню."
    await callback.answer(text, show_alert=True)

# --- Магазин ---

@router.message(F.text == "🛒 Магазин")
async def shop_menu(message: Message):
    async with Session() as session:
        user = await session.get(User, message.from_user.id)
        coins = user.coins if user else 0
    kb = ReplyKeyboardBuilder()
    kb.button(text="🔄 Обменять монеты на $VOXL")
    kb.button(text="⬅️ В меню")
    kb.adjust(2)
    await message.answer(
        f"🛍 <b>Магазин призов</b>\n"
        f"💰 <b>Твой баланс:</b> {coins} монет\n\n"
        "Что хочешь обменять сегодня?\n"
        "🔄 Монеты на $VOXL — просто выбери нужное!\n\n"
        "🔄 1 монета = 50 $VOXL\n\n"
        "🔄 Минимальная сумма для обменя: 100 монет\n\n"
        "⬇️ Жми кнопку:",
        reply_markup=kb.as_markup(resize_keyboard=True),
        parse_mode=ParseMode.HTML
    )

@router.message(F.text == "🔄 Обменять монеты на $VOXL")
async def exchange_coin_voxel(message: Message):
    async with Session() as session:
        user = await session.get(User, message.from_user.id)
        max_voxel = user.coins if user else 0
        if max_voxel < 100:
            await message.answer("Для обмена требуется минимум 100 монет.")
            return
    kb = InlineKeyboardBuilder()
    # Ограничиваем максимум 10 кнопок
    max_buttons = min(max_voxel // 100, 10)
    for i in range(1, max_buttons + 1):
        n = i * 100
        kb.button(text=f"{n}", callback_data=f"exchange_voxel_{n}")
    kb.adjust(3)
    await message.answer(
        "Сколько монет обменять на $VOXL? (5000 $VOXL = 100 монет)\n"
        "(Показано не более 10 вариантов, если у вас много монет — используйте крупный обмен!)",
        reply_markup=kb.as_markup()
    )

@router.callback_query(F.data.startswith("exchange_voxel_"))
async def process_exchange_voxel(callback: CallbackQuery):
    amount = int(callback.data.split("_")[-1])
    voxels = amount * 50  # Исправлено!
    async with Session() as session:
        user = await session.get(User, callback.from_user.id)
        if user.coins < amount:
            await callback.answer("Недостаточно монет для обмена!", show_alert=True)
            return
        user.coins -= amount
        final_coins = user.coins
        await session.commit()

    await callback.answer(
        f"💸 Готово! {amount} монет превращены в {voxels} $VOXL!\n"
        "💬 Напиши админу в меню для получения награды.",
        show_alert=True
    )
    await callback.message.edit_text(
        f"Вы успешно обменяли {amount} монет на {voxels} $VOXL!\n"
        "Свяжитесь с администратором для получения $VOXL."
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💱 Пользователь @{callback.from_user.username or callback.from_user.id} "
                f"(ID: <code>{callback.from_user.id}</code>) обменял {amount} монет на {voxels} $VOXL.\n"
                f"Осталось монет: <b>{final_coins}</b>",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logging.warning(f"Не удалось отправить уведомление админу: {e}")

# --- Баланс монет ---

@router.message(F.text == "🎫 Мои монеты")
async def show_coins(message: Message):
    async with Session() as session:
        user = await session.get(User, message.from_user.id)
        coins = user.coins if user else 0
    await message.answer(f"🪙 Ваши монеты: {coins}")

# --- Регистрация пользователя (с учетом реферала) ---

async def add_coins(user_id: int, amount: int):
    async with Session() as session:
        user = await session.get(User, user_id)
        if user:
            user.coins += amount
            await session.commit()

async def remove_coins(user_id: int, amount: int):
    async with Session() as session:
        user = await session.get(User, user_id)
        if user and user.coins >= amount:
            user.coins -= amount
            await session.commit()
            return True
        return False

async def register_user(user_id: int, username: Optional[str] = None, ref_id: Optional[int] = None):
    async with Session() as session:
        user = await session.get(User, user_id)
        if not user:
            referred_by = ref_id if ref_id and ref_id != user_id else None
            user = User(user_id=user_id, username=username, referred_by=referred_by, registered_at=date.today(), coins=3)
            session.add(user)
            await session.commit()
            if referred_by:
                await add_coins(referred_by, 2)
        else:
            if username and user.username != username:
                user.username = username
                await session.commit()

# --- Проверка подписки ---

async def check_user_subscriptions(user_id: int, channel_ids: List[int]) -> bool:
    for ch_id in channel_ids:
        try:
            member = await bot.get_chat_member(ch_id, user_id)
            if member.status in ('left', 'kicked'):
                return False
        except Exception as e:
            logging.warning(f"Ошибка проверки подписки {user_id} на {ch_id}: {e}")
            return False
    return True

# --- Кнопка подписки/отписки от уведомлений ---

def get_notify_keyboard(user_notify: bool) -> InlineKeyboardMarkup:
    if user_notify:
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔕 Отключить уведомления", callback_data="notify_off")]]
        )
    else:
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔔 Включить уведомления", callback_data="notify_on")]]
        )

# --- Команда старт и главное меню ---

@router.message(Command("start"))
async def user_start(message: Message):
    args = ""
    if message.text and len(message.text.split()) > 1:
        args = message.text.split(maxsplit=1)[1]
    ref_id = None
    if args.startswith("ref_"):
        try:
            ref_id = int(args.split("_")[1])
        except Exception:
            ref_id = None
    await register_user(message.from_user.id, message.from_user.username, ref_id)
    kb = ReplyKeyboardBuilder()
    kb.button(text="👤 Профиль")
    kb.button(text="🎁 Активные розыгрыши")
    kb.button(text="📊 Моя статистика")
    kb.button(text="🏆 Топ победителей")
    kb.button(text="🕓 История розыгрышей")
    kb.button(text="🤝 Пригласить друга")
    kb.button(text="🛒 Магазин")
    kb.button(text="❓ FAQ")
    kb.button(text="🆘 Связь с администрацией")
    kb.adjust(2)
    await message.answer("Добро пожаловать!\nВыберите действие:", reply_markup=kb.as_markup(resize_keyboard=True))

# --- Профиль пользователя ---

@router.message(F.text == "👤 Профиль")
async def show_profile(message: Message):
    await register_user(message.from_user.id, message.from_user.username)
    user_id = message.from_user.id
    async with Session() as session:
        user = await session.get(User, user_id)
        wins = (await session.execute(
            select(func.count(Winner.id)).where(Winner.user_id == user_id)
        )).scalar_one()
        parts = (await session.execute(
            select(func.count(Participant.id)).where(Participant.user_id == user_id)
        )).scalar_one()
        refs = (await session.execute(
            select(func.count(User.user_id)).where(User.referred_by == user_id)
        )).scalar_one()
        coins = user.coins if user else 0
    text = (
        f"👤 <b>Твой профиль</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👾 Ник: @{message.from_user.username or '—'}\n"
        f"🎲 Участий в розыгрышах: <b>{parts}</b>\n"
        f"🏆 Побед: <b>{wins}</b>\n"
        f"🤝 Друзей приглашено: <b>{refs}</b>\n"
        f"🪙 Монеток: <b>{coins}</b>\n"
        f"🔔 Уведомления: {'<b>ВКЛ</b> ✅' if (user and user.notify) else '<b>ВЫКЛ</b> ❌'}"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=get_notify_keyboard(user.notify if user else True))

# --- Меню: Пригласить друга ---

async def get_ref_link(user_id: int) -> str:
    bot_info = await bot.me()
    return f"https://t.me/{bot_info.username}?start=ref_{user_id}"

@router.message(F.text == "🤝 Пригласить друга")
async def invite_friend(message: Message):
    user_id = message.from_user.id
    ref_link = await get_ref_link(user_id)
    async with Session() as session:
        refs = (await session.execute(
            select(func.count(User.user_id)).where(User.referred_by == user_id)
        )).scalar_one()
    text = (
        f"🔗 Ваша реферальная ссылка:\n"
        f"<code>{ref_link}</code>\n\n"
        f"Вы уже пригласили: <b>{refs}</b> друзей!\n\n"
        f"Отправьте эту ссылку друзьям — за каждого нового пользователя, который запустит бота по ней, вы получите +1 к приглашённым!"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)

# --- Активные розыгрыши и публикация ---

GIVEAWAY_POST_TEMPLATE = (
    "{text}\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "👥 <b>Уже участвуют:</b> <b>{participants_count}</b>\n"
    "🏆 <b>Победителей:</b> <b>{winners_count}</b>\n"
    "⏰ <b>До окончания:</b> {remain_str}\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "<b>Что нужно сделать?</b>\n"
    "1️⃣ Подпишись на все обязательные каналы\n"
    "2️⃣ Жми <b>Участвовать</b> и жди розыгрыша!\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🍀 <b>Удачи!</b>"
)

@router.message(F.text == "🎁 Активные розыгрыши")
async def show_active_giveaways(message: Message):
    await register_user(message.from_user.id, message.from_user.username)
    async with Session() as session:
        now = datetime.utcnow()
        query = await session.execute(
            select(Giveaway)
            .where(Giveaway.completed == False)
            .where(Giveaway.end_time > now)
            .order_by(Giveaway.end_time)
        )
        giveaways = query.scalars().all()
        if not giveaways:
            await message.answer("Сейчас нет активных розыгрышей.")
            return
        for giveaway in giveaways:
            remain = giveaway.end_time - datetime.utcnow()
            mins, secs = divmod(int(remain.total_seconds()), 60)
            remain_str = f"Осталось {mins} мин {secs} сек"
            count_q = await session.execute(
                select(func.count(Participant.id)).where(Participant.giveaway_id == giveaway.id)
            )
            count = count_q.scalar_one()
            kb = InlineKeyboardBuilder()
            kb.button(text="Участвовать", callback_data=f"join_{giveaway.id}")
            markup = kb.as_markup()
            safe_text = bleach.clean(giveaway.text, tags=allowed_tags, strip=True)
            await message.answer(
                GIVEAWAY_POST_TEMPLATE.format(
                    text=safe_text,
                    winners_count=giveaway.winners_count,
                    participants_count=count,
                    remain_str=remain_str
                ),
                reply_markup=markup,
                parse_mode=ParseMode.HTML
            )

# --- История розыгрышей ---
@router.message(F.text == "🕓 История розыгрышей")
async def show_history(message: Message):
    async with Session() as session:
        query = await session.execute(
            select(Giveaway).where(Giveaway.completed == True).order_by(Giveaway.end_time.desc()).limit(10)
        )
        giveaways = query.scalars().all()
        if not giveaways:
            await message.answer("Пока что история пуста... Но всё впереди! 🚀")
            return
        text = "🕓 <b>Последние розыгрыши:</b>\n\n"
        for g in giveaways:
            wq = await session.execute(
                select(Winner.username).where(Winner.giveaway_id == g.id)
            )
            ws = [u[0] for u in wq.all()]
            winners = ", ".join([f"@{u}" if u else "—" for u in ws]) if ws else "—"
            safe_title = bleach.clean(g.text.replace('\n', ' ')[:30], tags=allowed_tags, strip=True)
            link = None
            if g.chat_id and g.message_id:
                try:
                    chat = await bot.get_chat(int(g.chat_id))
                    if getattr(chat, "username", None):
                        link = f"https://t.me/{chat.username}/{g.message_id}"
                except Exception:
                    pass
            link_str = f' <a href="{link}">Подробнее</a>' if link else ""
            text += f"• <b>{safe_title}...</b>{link_str}\nПобедители: {winners}\n\n"
        if len(text) > 4000:
            text = text[:3990] + "\n..."
        await message.answer(
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True  # <--- вот это важно!
        )
# --- Участие в розыгрыше (БЕСПЛАТНО!) ---

@router.callback_query(F.data.startswith("join_"))
async def join_giveaway(callback: CallbackQuery):
    await register_user(callback.from_user.id, callback.from_user.username)
    giveaway_id = int(callback.data.split("_")[1])
    user = callback.from_user

    async with Session() as session:
        giveaway = await session.get(Giveaway, giveaway_id)
        if not giveaway:
            return await callback.answer("Розыгрыш не найден.", show_alert=True)
        if giveaway.completed:
            return await callback.answer("Розыгрыш уже завершен.", show_alert=True)

        channel_ids = [int(ch) for ch in giveaway.subscribe_channels.split(",") if ch]
        if channel_ids:
            if not await check_user_subscriptions(user.id, channel_ids):
                return await callback.answer("Вы должны быть подписаны на все указанные каналы.", show_alert=True)

        participant_q = await session.execute(
            select(Participant).where(
                Participant.user_id == user.id,
                Participant.giveaway_id == giveaway_id
            )
        )
        participant = participant_q.scalar_one_or_none()
        if participant:
            return await callback.answer("Вы уже участвуете в этом розыгрыше.", show_alert=True)

        participant = Participant(
            user_id=user.id,
            username=user.username or user.full_name,
            giveaway_id=giveaway_id
        )
        session.add(participant)
        await session.commit()
        await update_giveaway_message(giveaway_id)
        await add_coins(user.id, 1)

    await callback.answer("🎉 Ты в игре! Желаем удачи 🍀")

# --- Обновление розыгрыша (одинаковый текст) ---

async def update_giveaway_message(giveaway_id: int):
    async with Session() as session:
        giveaway = await session.get(Giveaway, giveaway_id)
        if not giveaway:
            return

        kb = InlineKeyboardBuilder()
        if not giveaway.completed:
            kb.button(text="Участвовать", callback_data=f"join_{giveaway.id}")

        count_q = await session.execute(
            select(func.count(Participant.id)).where(Participant.giveaway_id == giveaway.id)
        )
        count = count_q.scalar_one()

        remain = giveaway.end_time - datetime.utcnow()
        if remain.total_seconds() < 0 or giveaway.completed:
            remain_str = "Завершено"
        else:
            mins, secs = divmod(int(remain.total_seconds()), 60)
            remain_str = f"Осталось {mins} мин {secs} сек"

        # Очищаем текст розыгрыша, разрешая только базовые HTML-теги
        safe_text = bleach.clean(giveaway.text, tags=allowed_tags, strip=True)
        text = GIVEAWAY_POST_TEMPLATE.format(
            text=safe_text,
            winners_count=giveaway.winners_count,
            participants_count=count,
            remain_str=remain_str
        )

        reply_markup = kb.as_markup() if not giveaway.completed else None

        if giveaway.completed:
            winners_q = await session.execute(
                select(Winner.username, Winner.user_id)
                .where(Winner.giveaway_id == giveaway.id)
            )
            winners = winners_q.all()
            if winners:
                text += "\n\n<b>Победители:</b>\n"
                for username, user_id in winners:
                    if username:
                        text += f" - @{username}\n"
                    else:
                        text += f" - <code>{user_id}</code>\n"

        try:
            if giveaway.chat_id and giveaway.message_id:
                await bot.edit_message_text(
                    chat_id=int(giveaway.chat_id),
                    message_id=giveaway.message_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logging.warning(f"Не удалось обновить сообщение розыгрыша {giveaway.id}: {e}")

# --- Создание розыгрыша (тот же шаблон публикации) ---

@router.callback_query(F.data == "new_giveaway")
async def new_giveaway(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("Введите текст розыгрыша:")
    await state.set_state(GiveawayStates.awaiting_text)

@router.message(GiveawayStates.awaiting_text)
async def set_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer("Введите количество победителей:")
    await state.set_state(GiveawayStates.awaiting_winners_count)

@router.message(GiveawayStates.awaiting_winners_count)
async def set_winners_count(message: Message, state: FSMContext):
    try:
        count = int(message.text)
        if count < 1:
            raise ValueError()
    except ValueError:
        return await message.answer("Введите корректное число победителей (больше 0).")
    await state.update_data(winners_count=count)
    await message.answer("Через сколько минут закончить розыгрыш?")
    await state.set_state(GiveawayStates.awaiting_duration)

@router.message(GiveawayStates.awaiting_duration)
async def set_duration(message: Message, state: FSMContext):
    try:
        minutes = int(message.text)
        if minutes < 1:
            raise ValueError()
    except ValueError:
        return await message.answer("Введите корректное количество минут (больше 0).")
    await state.update_data(duration=minutes)
    await message.answer(
        "Введите ID каналов для проверки подписки через пробел (например: -100123456 -100654321).\n"
        "Если не нужно проверять подписку, отправьте пустое сообщение."
    )
    await state.set_state(GiveawayStates.awaiting_subscribe_channels)

@router.message(GiveawayStates.awaiting_subscribe_channels)
async def set_subscribe_channels(message: Message, state: FSMContext):
    text = message.text.strip()
    if text:
        try:
            channel_ids = [int(ch.strip()) for ch in text.split()]
        except Exception:
            return await message.answer("Некорректный формат ID каналов. Введите ID через пробел.")
    else:
        channel_ids = []

    await state.update_data(subscribe_channels=channel_ids)
    await message.answer(
        "Введите ID канала для публикации розыгрыша (например: -100123456).\n"
        "Если хотите публиковать в тот же чат, где создаёте, отправьте пустое сообщение."
    )
    await state.set_state(GiveawayStates.awaiting_post_channel)

@router.message(GiveawayStates.awaiting_post_channel)
async def set_post_channel(message: Message, state: FSMContext):
    text = message.text.strip()
    if text:
        try:
            post_channel = str(int(text))
        except Exception:
            return await message.answer("Некорректный ID канала. Введите числовой ID.")
    else:
        post_channel = None

    data = await state.get_data()
    end_time = datetime.utcnow() + timedelta(minutes=data['duration'])

    async with Session() as session:
        giveaway = Giveaway(
            text=data['text'],
            winners_count=data['winners_count'],
            end_time=end_time,
            subscribe_channels=",".join(str(ch) for ch in data['subscribe_channels']),
            post_channel=post_channel
        )
        session.add(giveaway)
        await session.commit()
        await session.refresh(giveaway)

    kb = InlineKeyboardBuilder()
    kb.button(text="Участвовать", callback_data=f"join_{giveaway.id}")
    chat_for_post = post_channel if post_channel else message.chat.id

    try:
        safe_text = bleach.clean(giveaway.text, tags=allowed_tags, strip=True)
        sent_msg = await bot.send_message(
        chat_id=chat_for_post,
        text=GIVEAWAY_POST_TEMPLATE.format(
        text=safe_text,
        winners_count=giveaway.winners_count,
        participants_count=0,
        remain_str=f"Осталось {data['duration']} мин 0 сек"
    ),
    reply_markup=kb.as_markup(),
    parse_mode=ParseMode.HTML
)
        async with Session() as session:
            db_giveaway = await session.get(Giveaway, giveaway.id)
            db_giveaway.message_id = sent_msg.message_id
            db_giveaway.chat_id = str(sent_msg.chat.id)
            await session.commit()
    except Exception as e:
        logging.error(f"Ошибка отправки поста розыгрыша: {e}")
        await message.answer("Не удалось опубликовать розыгрыш в указанный канал.")

    await message.answer("Розыгрыш создан!")
    asyncio.create_task(notify_all_users_about_giveaway(giveaway))
    await state.clear()
    asyncio.create_task(giveaway_watcher(giveaway.id))

# --- Админ-панель и топы ---

# --- Кнопка "Добавить монеты" в админ-панели ---

@router.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("Доступ запрещен.")
    kb = InlineKeyboardBuilder()
    kb.button(text="🎉 Новый розыгрыш", callback_data="new_giveaway")
    kb.button(text="📈 Аналитика", callback_data="admin_analytics")
    kb.button(text="🏆 Топ победителей", callback_data="admin_top")
    kb.button(text="👑 Топ рефоводов", callback_data="admin_top_ref")
    kb.button(text="➕ Добавить монеты", callback_data="admin_add_coins")
    kb.button(text="⛔️ Забанить пользователя", callback_data="admin_ban_user")
    kb.button(text="✅ Разбанить пользователя", callback_data="admin_unban_user")
    kb.adjust(2)
    await message.answer("Панель администратора:", reply_markup=kb.as_markup())
    await state.clear()

# ban/unban
class BanUserStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_reason = State()

class UnbanUserStates(StatesGroup):
    waiting_for_user_id = State()

@router.callback_query(F.data == "admin_ban_user")
async def admin_ban_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID пользователя для бана:")
    await state.set_state(BanUserStates.waiting_for_user_id)
    await callback.answer()

@router.message(BanUserStates.waiting_for_user_id)
async def admin_ban_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except Exception:
        await message.answer("Некорректный ID пользователя. Введите числовой ID:")
        return
    await state.update_data(target_user_id=user_id)
    await message.answer("Введите причину бана:")
    await state.set_state(BanUserStates.waiting_for_reason)

@router.message(BanUserStates.waiting_for_reason)
async def admin_ban_reason(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = data["target_user_id"]
    reason = message.text.strip()
    async with Session() as session:
        user = await session.get(User, user_id)
        if not user:
            await message.answer(f"Пользователь с ID {user_id} не найден.")
        elif user.banned:
            await message.answer("Пользователь уже забанен.")
        else:
            user.banned = True
            user.ban_reason = reason
            await session.commit()
            await message.answer(f"Пользователь {user_id} забанен.\nПричина: {reason}")
            try:
                await bot.send_message(user_id, f"⛔️ Вы были заблокированы администрацией!\nПричина: {reason}")
            except Exception:
                pass
    await state.clear()

    class UnbanUserStates(StatesGroup):
        waiting_for_user_id = State()

@router.callback_query(F.data == "admin_unban_user")
async def admin_unban_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID пользователя для разбана:")
    await state.set_state(UnbanUserStates.waiting_for_user_id)
    await callback.answer()

@router.message(UnbanUserStates.waiting_for_user_id)
async def admin_unban_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except Exception:
        await message.answer("Некорректный ID пользователя. Введите числовой ID:")
        return
    async with Session() as session:
        user = await session.get(User, user_id)
        if not user:
            await message.answer(f"Пользователь с ID {user_id} не найден.")
        elif not user.banned:
            await message.answer("Пользователь не забанен.")
        else:
            user.banned = False
            user.ban_reason = None
            await session.commit()
            await message.answer(f"Пользователь {user_id} разбанен.")
            try:
                await bot.send_message(user_id, "✅ Ваш бан снят администрацией.")
            except Exception:
                pass
    await state.clear()



# --- FSM для добавления монет ---

class AddCoinsStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount = State()

@router.callback_query(F.data == "admin_add_coins")
async def admin_add_coins_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID пользователя, которому нужно начислить монеты:")
    await state.set_state(AddCoinsStates.waiting_for_user_id)
    await callback.answer()

@router.message(AddCoinsStates.waiting_for_user_id)
async def admin_add_coins_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except Exception:
        await message.answer("Некорректный ID пользователя. Введите числовой ID:")
        return
    await state.update_data(target_user_id=user_id)
    await message.answer("Введите количество монет для начисления:")
    await state.set_state(AddCoinsStates.waiting_for_amount)

@router.message(AddCoinsStates.waiting_for_amount)
async def admin_add_coins_amount(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError()
    except Exception:
        await message.answer("Некорректное количество. Введите положительное число:")
        return

    target_user_id = data.get("target_user_id")
    async with Session() as session:
        user = await session.get(User, target_user_id)
        if not user:
            await message.answer(f"Пользователь с ID {target_user_id} не найден.")
            await state.clear()
            return
        user.coins += amount
        await session.commit()
        await message.answer(f"Пользователю <code>{target_user_id}</code> начислено {amount} монет.\nТекущий баланс: <b>{user.coins}</b>", parse_mode=ParseMode.HTML)
        try:
            await bot.send_message(
                target_user_id,
                f"🪙 Вам было начислено {amount} монет администратором!\nВаш текущий баланс: <b>{user.coins}</b>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass  # Не удалось отправить сообщение пользователю
    await state.clear()


@router.callback_query(F.data == "admin_analytics")
async def admin_analytics_callback(callback: CallbackQuery):
    await admin_analytics(callback.message)
    await callback.answer()

@router.callback_query(F.data == "admin_top")
async def admin_top_callback(callback: CallbackQuery):
    await top_winners(callback.message)
    await callback.answer()

@router.callback_query(F.data == "admin_top_ref")
async def admin_top_ref_callback(callback: CallbackQuery):
    User2 = aliased(User)
    async with Session() as session:
        result = await session.execute(
            select(User.user_id, User.username, func.count(User2.user_id).label("refs"))
            .outerjoin(User2, User2.referred_by == User.user_id)
            .group_by(User.user_id, User.username)
            .order_by(func.count(User2.user_id).desc())
            .limit(10)
        )
        top = result.all()
    text = "👑 <b>Топ рефоводов:</b>\n\n"
    for i, (uid, username, refs) in enumerate(top, 1):
        username_str = f"@{username}" if username else f"<code>{uid}</code>"
        text += f"{i}. {username_str} — {refs} приглашённых\n"
    await callback.message.answer(text, parse_mode=ParseMode.HTML)
    await callback.answer()

# --- Статистика пользователя ---

async def user_stats(message: Message):
    user_id = message.from_user.id
    async with Session() as session:
        win_count = (await session.execute(
            select(func.count(Winner.id)).where(Winner.user_id == user_id)
        )).scalar_one()
        participated_count = (await session.execute(
            select(func.count(Participant.id)).where(Participant.user_id == user_id)
        )).scalar_one()
        user = await session.get(User, user_id)
        coins = user.coins if user else 0
    await message.answer(
        f"🏅 Ваша статистика:\n\n"
        f"Участвовали в розыгрышах: {participated_count}\n"
        f"Выигрывали: {win_count}\n"
        f"Монет: {coins}"
    )

# --- Топ победителей ---

async def top_winners(message: Message):
    async with Session() as session:
        result = await session.execute(
            select(Winner.username, func.count(Winner.id).label("wins"))
            .group_by(Winner.user_id, Winner.username)
            .order_by(func.count(Winner.id).desc())
            .limit(10)
        )
        top = result.all()

    if not top:
        await message.answer("Победителей пока нет.")
        return

    text = "🏆 Топ победителей:\n\n"
    for i, (username, wins) in enumerate(top, 1):
        text += f"{i}. @{username} - {wins} выигрышей\n"

    await message.answer(text)

# --- Аналитика (статистика) для админа ---

@router.message(F.text == "📈 Аналитика")
async def admin_analytics(message: Message):
    async with Session() as session:
        total_users = (await session.execute(select(func.count(User.user_id)))).scalar_one()
        week_ago = date.today() - timedelta(days=7)
        try:
            new_users = (await session.execute(
                select(func.count(User.user_id)).where(User.registered_at >= week_ago)
            )).scalar_one()
        except Exception:
            new_users = "нет данных"

        total_giveaways = (await session.execute(
            select(func.count(Giveaway.id))
        )).scalar_one()
        completed_giveaways = (await session.execute(
            select(func.count(Giveaway.id)).where(Giveaway.completed == True)
        )).scalar_one()
        active_giveaways = (await session.execute(
            select(func.count(Giveaway.id)).where(Giveaway.completed == False)
        )).scalar_one()

        total_winners = (await session.execute(
            select(func.count(Winner.id))
        )).scalar_one()
        top_winner = (await session.execute(
            select(Winner.username, func.count(Winner.id).label("cnt"))
            .group_by(Winner.user_id)
            .order_by(func.count(Winner.id).desc())
            .limit(1)
        )).first()
        top_winner_str = f"@{top_winner[0]} ({top_winner[1]} побед)" if top_winner else "нет данных"

        User2 = aliased(User)
        top_ref = (await session.execute(
            select(User.username, func.count(User2.user_id).label("refs"))
            .outerjoin(User2, User2.referred_by == User.user_id)
            .group_by(User.user_id, User.username)
            .order_by(func.count(User2.user_id).desc())
            .limit(1)
        )).first()
        top_ref_str = f"@{top_ref[0]} ({top_ref[1]} приглашённых)" if top_ref else "нет данных"

    text = (
        f"📈 <b>Аналитика:</b>\n"
        f"Всего пользователей: {total_users}\n"
        f"Новых за 7 дней: {new_users}\n"
        f"Всего розыгрышей: {total_giveaways}\n"
        f"Активных розыгрышей: {active_giveaways}\n"
        f"Завершённых розыгрышей: {completed_giveaways}\n"
        f"Всего победителей: {total_winners}\n"
        f"Топ победитель: {top_winner_str}\n"
        f"Топ рефовод: {top_ref_str}\n"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)

# --- Хендлеры статистики и топа ---

@router.message(F.text == "📊 Моя статистика")
async def button_user_stats(message: Message):
    await register_user(message.from_user.id, message.from_user.username)
    await user_stats(message)

@router.message(F.text == "🏆 Топ победителей")
async def button_top_winners(message: Message):
    await register_user(message.from_user.id, message.from_user.username)
    await top_winners(message)


# Связь с админом
class FeedbackStates(StatesGroup):
    waiting_for_feedback = State()
    waiting_for_admin_reply = State()

import re

# Словарь для хранения соответствия id сообщения пользователя и id сообщения админа
# При реальном проекте лучше сохранять это в БД, но для простоты используем dict
USER_MSG_MAP = {}

@router.message(F.text == "🆘 Связь с администрацией")
async def contact_admin_start(message: Message, state: FSMContext):
    await message.answer("Пожалуйста, опишите свой вопрос или проблему. Сообщение будет передано администрации.")
    await state.set_state(FeedbackStates.waiting_for_feedback)

@router.message(F.text == "🆘 Связь с администрацией")
async def contact_admin_start(message: Message, state: FSMContext):
    await message.answer("Пожалуйста, опишите свой вопрос или проблему. Сообщение будет передано администрации.")
    await state.set_state(FeedbackStates.waiting_for_feedback)

@router.message(FeedbackStates.waiting_for_feedback)
async def contact_admin_process(message: Message, state: FSMContext):
    text = message.text
    user = message.from_user
    # Безопасный текст для HTML, переносы строк -> <br>
    admin_text = bleach.clean(text, tags=allowed_tags, strip=True).replace('\n', '<br>')
    for admin_id in ADMIN_IDS:
        try:
            sent = await bot.send_message(
                admin_id,
                f"🆘 <b>Связь с администрацией</b>\n"
                f"От: @{user.username or user.id} (ID: <code>{user.id}</code>)\n"
                f"Для ответа: <code>/reply_{user.id}</code> Ваш текст\n\n"
                f"{admin_text}",
                parse_mode=ParseMode.HTML
            )
            USER_MSG_MAP[sent.message_id] = user.id
        except Exception as e:
            logging.warning(f"Не удалось отправить сообщение админу: {e}")
    await message.answer("Ваше сообщение отправлено администрации. Спасибо!")
    await state.clear()

# --- Ответ администратора пользователю ---
@router.message(F.text.regexp(r"^/reply_(\d+)\s+(.+)"))
async def admin_reply_command(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    match = re.match(r"^/reply_(\d+)\s+(.+)", message.text, re.DOTALL)
    if not match:
        await message.answer("Используйте формат: /reply_ID текст ответа")
        return
    user_id, reply_text = match.groups()
    try:
        user_id = int(user_id)
        await bot.send_message(
            user_id,
            f"💬 Ответ администрации:\n\n{reply_text}"
        )
        await message.answer("Ответ отправлен.")
    except Exception as e:
        await message.answer(f"Ошибка при отправке ответа: {e}")
# --- Таймер розыгрыша ---

async def giveaway_watcher(giveaway_id: int):
    reminder_sent = False
    while True:
        await asyncio.sleep(5)
        async with Session() as session:
            giveaway = await session.get(Giveaway, giveaway_id)
            if not giveaway or giveaway.completed:
                break
            await update_giveaway_message(giveaway_id)
            remain = (giveaway.end_time - datetime.utcnow()).total_seconds()
            if not reminder_sent and remain <= 300 and remain > 0:
                participants_q = await session.execute(
                    select(Participant.user_id).where(Participant.giveaway_id == giveaway_id)
                )
                pids = {u for (u,) in participants_q.all()}
                for uid in pids:
                    try:
                        await bot.send_message(uid, f"⏰ До завершения розыгрыша осталось 5 минут!\n\n{bleach.clean(giveaway.text, tags=allowed_tags, strip=True)}")
                    except Exception as e:
                        logging.warning(f"Не удалось отправить напоминание участнику {uid}: {e}")
                reminder_sent = True
            if giveaway.end_time <= datetime.utcnow():
                participants_q = await session.execute(
                    select(Participant).where(Participant.giveaway_id == giveaway_id)
                )
                participants = participants_q.scalars().all()
                if len(participants) == 0:
                    giveaway.completed = True
                    await session.commit()
                    await update_giveaway_message(giveaway_id)
                    break
                winners_count = min(giveaway.winners_count, len(participants))
                winners = random.sample(participants, winners_count)
                for w in winners:
                    winner_entry = Winner(
                        user_id=w.user_id,
                        username=w.username,
                        giveaway_id=giveaway_id
                    )
                    session.add(winner_entry)
                    await add_coins(w.user_id, 4)
                giveaway.completed = True
                await session.commit()
                await update_giveaway_message(giveaway_id)
                for w in winners:
                    try:
                        safe_text = bleach.clean(giveaway.text, tags=allowed_tags, strip=True)
                        await bot.send_message(
                        w.user_id,
                        f"🏅 <b>Поздравляем!</b> Ты стал победителем в розыгрыше:\n\n"
                        f"{safe_text}\n\n"
                        "📝 Пиши админу для получения приза. Ты — настоящий везунчик! 🍀",
                        parse_mode=ParseMode.HTML
                    )
                    except Exception as e:
                        logging.warning(f"Не удалось отправить уведомление победителю {w.user_id}: {e}")
                break

# --- Рассылка уведомлений о новом розыгрыше ---

async def notify_all_users_about_giveaway(giveaway: Giveaway):
    async with Session() as session:
        users = (await session.execute(select(User.user_id).where(User.notify == True))).scalars().all()
    safe_text = bleach.clean(giveaway.text, tags=allowed_tags, strip=True)
    message_text = (
    "🆕 <b>Запущен новый розыгрыш!</b>\n\n"
    f"{safe_text}\n\n"
    f"⏳ Успей поучаствовать! Время до конца: {(giveaway.end_time - datetime.utcnow()).seconds // 60} мин"
)
    for uid in users:
        try:
            await bot.send_message(uid, message_text)
        except Exception as e:
            logging.warning(f"Не удалось отправить уведомление пользователю {uid}: {e}")

# --- Кнопка подписки/отписки от уведомлений ---

@router.callback_query(F.data.in_(["notify_on", "notify_off"]))
async def switch_notify(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with Session() as session:
        user = await session.get(User, user_id)
        if user:
            user.notify = callback.data == "notify_on"
            await session.commit()
            await callback.answer("Настройки обновлены!")
            await callback.message.edit_reply_markup(reply_markup=get_notify_keyboard(user.notify))
        else:
            await callback.answer("Ошибка!")

# --- Инициализация базы и запуск ---

async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logging.info("База данных создана/подключена.")

async def main():
    await on_startup()
    dp.message.middleware(BanFilterMiddleware())
    dp.callback_query.middleware(BanFilterMiddleware())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
