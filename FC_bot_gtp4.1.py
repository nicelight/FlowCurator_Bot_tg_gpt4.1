# Отправьте команду /addsource боту. Бот попросит переслать сообщение из нового канала. Перешлите сообщение, и бот автоматически добавит этот канал в список source channels и сохранит его в базе.
# 4. Стандартный запуск  проекта uv run main.py
# 5. добавление зависимостей uv add django requests

#imported libs
import asyncio
import logging
from telethon import TelegramClient, events
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession
from telethon.tl.functions.auth import ExportLoginTokenRequest, ImportLoginTokenRequest
import aiosqlite
from datetime import datetime, timedelta
import qrcode
# system libs? 
import re
from getpass import getpass
import io
import sys
import signal


# ------------------------------
# Настройки чатов: approval_group и target_channel задаются через id (числовые)
# ------------------------------
# свалка 1
# https://t.me/Hydrotrash1
# -1002284347666
# канал свалка гидропоника с горошком ()
# https://t.me/+Rfo3SwVYIW1kYTRi
# -1002340184870
#  канал Галерея гидропоники
# ID: -1002252559154

#API ключи от telegram user bot: my.telegram.org
YOUR_API_ID = 25979825
YOUR_API_HASH = 'e2a55f23f44e1aeda0fc6223b0505d7e'
SETGROUP_PASSWORD = "5555"  # Пароль для смены группы одобрения
approval_group = -1002284347666    #  ID группы одобрения
target_channel = -1002252559154      # ID целевого канала


# ------------------------------
# Глобальные переменные
# ------------------------------
source_channels = []        # Список id источников (каналов) в виде строк
awaiting_new_source = False # Флаг ожидания нового источника после команды /addsource
my_user_id = None
start_time = datetime.utcnow()  # Время старта для аптайма
set_target_mode = False  # Флаг ожидания установки целевого канала
set_group_mode = False  # Флаг ожидания установки группы одобрения
set_group_wait_link = False  # Флаг ожидания ссылки на группу
processing_albums = set()  # Временное хранилище обрабатываемых альбомов (channel_id:grouped_id)

# ------------------------------
# Настройка логирования: запись в файлы и вывод в консоль
# ------------------------------
class LevelFilter(logging.Filter):
    def __init__(self, level):
        super().__init__()
        self.level = level

    def filter(self, record):
        return record.levelno == self.level

logger = logging.getLogger("FCLogger")
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Общий лог (все сообщения) в файл fc_logs.txt
all_handler = logging.FileHandler("fc_logs.txt", encoding="utf-8")
all_handler.setLevel(logging.DEBUG)
all_handler.setFormatter(formatter)
logger.addHandler(all_handler)

# Лог для INFO в файл fc_INFO.txt
info_handler = logging.FileHandler("fc_INFO.txt", encoding="utf-8")
info_handler.setLevel(logging.DEBUG)
info_handler.addFilter(LevelFilter(logging.INFO))
info_handler.setFormatter(formatter)
logger.addHandler(info_handler)

# Лог для ERROR в файл fc_ERROR.txt
error_handler = logging.FileHandler("fc_ERROR.txt", encoding="utf-8")
error_handler.setLevel(logging.DEBUG)
error_handler.addFilter(LevelFilter(logging.ERROR))
error_handler.setFormatter(formatter)
logger.addHandler(error_handler)

# Лог для DEBUG в файл fc_DEBUG.txt
debug_handler = logging.FileHandler("fc_DEBUG.txt", encoding="utf-8")
debug_handler.setLevel(logging.DEBUG)
debug_handler.addFilter(LevelFilter(logging.DEBUG))
debug_handler.setFormatter(formatter)
logger.addHandler(debug_handler)

# Консольный обработчик - вывод всех логов в консоль
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# ------------------------------
# Функция для открытия сессии Telethon с повторными попытками (3 попытки, интервал 5 сек)
# ------------------------------
async def open_client_session(api_id, api_hash, max_attempts=3, delay=5):
    for attempt in range(1, max_attempts + 1):
        try:
            logger.debug(f"DEBUG: Попытка открытия сессии {attempt} из {max_attempts}.")
            client = TelegramClient('fc_session', api_id, api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                logger.info("INFO: Клиент не авторизован. Добавьте процедуру авторизации при необходимости.")
            logger.info("INFO: Сессия успешно открыта.")
            return client
        except Exception as e:
            logger.error(f"ERROR: Попытка {attempt} не удалась: {e}")
            if attempt < max_attempts:
                logger.debug("DEBUG: Ожидание 5 секунд перед следующей попыткой...")
                await asyncio.sleep(delay)
    logger.error("ERROR: Не удалось открыть сессию за 3 попытки. Завершаем программу.")
    sys.exit(1)

# ------------------------------
# Инициализация базы данных SQLite
# Создаем таблицы для хранения пересланных сообщений, источников каналов и настроек
# ------------------------------
async def init_db():
    try:
        db = await aiosqlite.connect("fc_database.sqlite")
        # Проверка и миграция: добавление grouped_id, если его нет
        async with db.execute("PRAGMA table_info(forwarded_messages)") as cursor:
            columns = [row[1] async for row in cursor]
        if "grouped_id" not in columns:
            logger.info("INFO: Миграция БД: добавляем столбец grouped_id в forwarded_messages...")
            await db.execute("ALTER TABLE forwarded_messages ADD COLUMN grouped_id TEXT")
            await db.commit()
            logger.info("INFO: Миграция БД завершена: grouped_id добавлен.")
        # Миграция: добавляем поле forwarded_to_target, если его нет
        async with db.execute("PRAGMA table_info(forwarded_messages)") as cursor:
            columns = [row[1] async for row in cursor]
        if "forwarded_to_target" not in columns:
            logger.info("INFO: Миграция БД: добавляем столбец forwarded_to_target в forwarded_messages...")
            await db.execute("ALTER TABLE forwarded_messages ADD COLUMN forwarded_to_target INTEGER DEFAULT 0")
            await db.commit()
            logger.info("INFO: Миграция БД завершена: forwarded_to_target добавлен.")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS forwarded_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_message_id TEXT NOT NULL,
                approval_message_id TEXT,
                source_channel_id TEXT NOT NULL,
                forward_date TEXT NOT NULL,
                grouped_id TEXT,
                forwarded_to_target INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS source_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL UNIQUE,
                added_date TEXT NOT NULL
            )
        """)
        # Новая таблица для хранения настроек
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.commit()
        logger.info("INFO: База данных успешно проинициализирована.")
        async with db.execute("SELECT channel_id FROM source_channels") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                source_channels.append(row[0])
        logger.debug(f"DEBUG: Загружены источники: {source_channels}")
        # Загружаем целевой канал из базы, если есть
        global target_channel, approval_group
        async with db.execute("SELECT value FROM settings WHERE key = 'target_channel'") as cursor:
            row = await cursor.fetchone()
            if row:
                try:
                    target_channel = int(row[0])
                    logger.info(f"INFO: Загружен целевой канал из базы: {target_channel}")
                except Exception as e:
                    logger.error(f"ERROR: Не удалось преобразовать target_channel из базы: {e}")
        # Загружаем группу одобрения из базы, если есть
        async with db.execute("SELECT value FROM settings WHERE key = 'approval_group'") as cursor:
            row = await cursor.fetchone()
            if row:
                try:
                    val = str(row[0])
                    if not val.startswith('-100'):
                        val = f'-100{val}'
                    approval_group = int(val)
                    logger.info(f"INFO: Загружена группа одобрения из базы: {approval_group}")
                except Exception as e:
                    logger.error(f"ERROR: Не удалось преобразовать approval_group из базы: {e}")
        return db
    except Exception as e:
        logger.error(f"ERROR: Ошибка при инициализации базы данных: {e}")
        sys.exit(1)

# ------------------------------
# Функция для добавления нового источника (канала)
# ------------------------------
async def add_source_channel(channel_id):
    try:
        if not str(channel_id).startswith("-100"):
            channel_id = f"-100{channel_id}"
        async with aiosqlite.connect("fc_database.sqlite") as db:
            await db.execute(
                "INSERT OR IGNORE INTO source_channels (channel_id, added_date) VALUES (?, ?)",
                (channel_id, datetime.utcnow().isoformat())
            )
            await db.commit()
        if channel_id not in source_channels:
            source_channels.append(channel_id)
        logger.info(f"INFO: Новый источник добавлен: {channel_id}")
    except Exception as e:
        logger.error(f"ERROR: Ошибка при добавлении источника {channel_id}: {e}")


# ------------------------------
# Обработчик для пересылки сообщений из source_channels (только из каналов)
# слушает все новости в каналах
# ------------------------------
@events.register(events.NewMessage)
async def forward_to_approval(event):
    try:
        if event.chat and getattr(event.chat, 'broadcast', False):
            channel_id = str(event.chat_id)
            if channel_id in source_channels:
                logger.debug(f"DEBUG: Получено сообщение из источника {channel_id}.")
                # Проверяем, часть ли это альбома
                if event.grouped_id:
                    grouped_id_str = str(event.grouped_id)
                    album_key = f"{channel_id}:{grouped_id_str}"
                    if album_key in processing_albums:
                        logger.debug(
                            f"DEBUG: Альбом grouped_id={grouped_id_str} из канала {channel_id} уже обрабатывается, пропускаем повторное событие."
                        )
                        return
                    async with aiosqlite.connect("fc_database.sqlite") as db:
                        async with db.execute(
                            "SELECT 1 FROM forwarded_messages WHERE grouped_id = ? AND source_channel_id = ? LIMIT 1",
                            (grouped_id_str, channel_id),
                        ) as cursor:
                            already_in_db = await cursor.fetchone() is not None
                    if already_in_db:
                        logger.debug(
                            f"DEBUG: Альбом grouped_id={grouped_id_str} из канала {channel_id} уже пересылался ранее, пропускаем."
                        )
                        return
                    if album_key in processing_albums:
                        logger.debug(
                            f"DEBUG: Альбом grouped_id={grouped_id_str} из канала {channel_id} уже обрабатывается после проверки БД, пропускаем повторное событие."
                        )
                        return
                    processing_albums.add(album_key)
                    try:
                        # Получаем все сообщения альбома
                        messages = []
                        async for msg in event.client.iter_messages(event.chat_id, min_id=event.id-20, max_id=event.id+20):
                            if msg.grouped_id == event.grouped_id:
                                messages.append(msg)
                        messages = sorted(messages, key=lambda m: m.id)
                        forwarded = await event.client.forward_messages(approval_group, [m.id for m in messages], event.chat_id)
                        logger.info(f"INFO: Альбом из {len(messages)} сообщений переслан в группу одобрения.")
                        # Сохраняем все id сообщений альбома и их связь с grouped_id
                        async with aiosqlite.connect("fc_database.sqlite") as db:
                            for orig_msg, fwd_msg in zip(messages, forwarded):
                                await db.execute(
                                    "INSERT INTO forwarded_messages (original_message_id, approval_message_id, source_channel_id, forward_date, grouped_id) VALUES (?, ?, ?, ?, ?)",
                                    (str(orig_msg.id), str(fwd_msg.id), channel_id, datetime.utcnow().isoformat(), grouped_id_str)
                                )
                            await db.commit()
                    finally:
                        processing_albums.discard(album_key)
                else:
                    forwarded = await event.forward_to(approval_group)
                    logger.info(f"INFO: Сообщение {event.id} переслано в группу одобрения как {forwarded.id}.")
                    # Сохраняем как раньше
                    async with aiosqlite.connect("fc_database.sqlite") as db:
                        await db.execute(
                            "INSERT INTO forwarded_messages (original_message_id, approval_message_id, source_channel_id, forward_date, grouped_id) VALUES (?, ?, ?, ?, ?)",
                            (str(event.id), str(forwarded.id), channel_id, datetime.utcnow().isoformat(), None)
                        )
                        await db.commit()
    except Exception as e:
        logger.error(f"ERROR: Ошибка при пересылке сообщения {event.id}: {e}")

# ------------------------------
# Обработчик для мониторинга approval_group: при ответе "ok" пересылаем исходное сообщение (или альбом) в target_channel
# ------------------------------
@events.register(events.NewMessage(chats=approval_group))
async def check_approval_response(event):
    try:
        text = event.raw_text.strip().lower()
        if text.lower() in ["ok", "ок"] and event.is_reply:
            replied_msg = await event.get_reply_message()
            if replied_msg:
                approval_msg_id = str(replied_msg.id)
                async with aiosqlite.connect("fc_database.sqlite") as db:
                    # Получаем запись по этому сообщению
                    async with db.execute(
                        "SELECT original_message_id, source_channel_id, grouped_id FROM forwarded_messages WHERE approval_message_id = ?",
                        (approval_msg_id,)
                    ) as cursor:
                        row = await cursor.fetchone()
                        if row:
                            original_message_id, source_channel_id, grouped_id = row
                            # Получаем имя целевого канала
                            try:
                                channel_entity = await event.client.get_entity(target_channel)
                                channel_title = getattr(channel_entity, "title", str(target_channel))
                            except Exception as e:
                                logger.error(f"ERROR: Не удалось получить имя целевого канала: {e}")
                                channel_title = str(target_channel)
                            if grouped_id:
                                # Проверяем, был ли альбом уже переслан
                                async with db.execute(
                                    "SELECT COUNT(*) FROM forwarded_messages WHERE grouped_id = ? AND source_channel_id = ? AND forwarded_to_target = 1",
                                    (grouped_id, source_channel_id)
                                ) as check_cur:
                                    already_forwarded = (await check_cur.fetchone())[0] > 0
                                if already_forwarded:
                                    await event.reply(f"Альбом уже был опубликован в {channel_title}")
                                    logger.info(f"INFO: Попытка повторной публикации альбома grouped_id={grouped_id}, отклонено.")
                                    return
                                # Это альбом, пересылаем все сообщения альбома
                                async with db.execute(
                                    "SELECT original_message_id FROM forwarded_messages WHERE grouped_id = ? AND source_channel_id = ? ORDER BY original_message_id ASC",
                                    (grouped_id, source_channel_id)
                                ) as cur2:
                                    msg_ids = [int(r[0]) for r in await cur2.fetchall()]
                                logger.info(f"INFO: Одобрен альбом, пересылаем {len(msg_ids)} сообщений в целевой канал.")
                                await event.client.forward_messages(
                                    entity=target_channel,
                                    messages=msg_ids,
                                    from_peer=int(source_channel_id)
                                )
                                # Отмечаем как пересланные в целевой канал
                                await db.execute(
                                    "UPDATE forwarded_messages SET forwarded_to_target = 1 WHERE grouped_id = ? AND source_channel_id = ?",
                                    (grouped_id, source_channel_id)
                                )
                                await db.commit()
                                await event.reply(f"Переслано в {channel_title}")
                            else:
                                # Проверяем, было ли сообщение уже переслано
                                async with db.execute(
                                    "SELECT forwarded_to_target FROM forwarded_messages WHERE original_message_id = ? AND source_channel_id = ?",
                                    (original_message_id, source_channel_id)
                                ) as check_cur:
                                    already_forwarded = (await check_cur.fetchone())[0] == 1
                                if already_forwarded:
                                    await event.reply(f"Сообщение уже было опубликовано в {channel_title}")
                                    logger.info(f"INFO: Попытка повторной публикации сообщения id={original_message_id}, отклонено.")
                                    return
                                # Обычное сообщение
                                logger.info(f"INFO: Сообщение {original_message_id} одобрено, пересылаем в целевой канал.")
                                await event.client.forward_messages(
                                    entity=target_channel,
                                    messages=int(original_message_id),
                                    from_peer=int(source_channel_id)
                                )
                                # Отмечаем как пересланное в целевой канал
                                await db.execute(
                                    "UPDATE forwarded_messages SET forwarded_to_target = 1 WHERE original_message_id = ? AND source_channel_id = ?",
                                    (original_message_id, source_channel_id)
                                )
                                await db.commit()
                                await event.reply(f"Переслано в {channel_title}")
                        else:
                            logger.error(f"ERROR: Не найдена запись для сообщения {approval_msg_id}.")
    except Exception as e:
        logger.error(f"ERROR: Ошибка в обработчике одобрения: {e}")

# ------------------------------
# Функция сброса всех режимов ожидания
# ------------------------------
def reset_all_modes():
    global awaiting_new_source, set_target_mode, set_group_mode, set_group_wait_link
    awaiting_new_source = False
    set_target_mode = False
    set_group_mode = False
    set_group_wait_link = False

# ------------------------------
# Обработчик команды /addsource – добавляет новый источник (канал)
# ------------------------------
@events.register(events.NewMessage(pattern=r'^/addsource'))
async def handle_addsource(event):
    global awaiting_new_source
    logger.debug("DEBUG: Вызван обработчик handle_addsource")
    reset_all_modes()
    awaiting_new_source = True
    logger.debug(f"DEBUG: awaiting_new_source установлен в True, остальные режимы сброшены")
    await event.reply("Пожалуйста, перешлите сообщение из нового канала, который хотите добавить в источники.")

@events.register(events.NewMessage)
async def wait_for_new_source(event):
    global awaiting_new_source, set_target_mode, set_group_mode, set_group_wait_link, my_user_id
    # logger.debug("DEBUG: обработка нового сообщения в канале, группе или ЛС")
    # logger.debug(f"DEBUG: wait_for_new_source вызван. awaiting_new_source={awaiting_new_source}, set_target_mode={set_target_mode}, set_group_mode={set_group_mode}, set_group_wait_link={set_group_wait_link}")
    if not awaiting_new_source or set_target_mode or set_group_mode or set_group_wait_link:
        # logger.debug("DEBUG: wait_for_new_source: неактивен режим ожидания нового источника, выходим")
        return
    logger.debug(f"DEBUG: Типы: event.chat_id={event.chat_id} ({type(event.chat_id)}), approval_group={approval_group} ({type(approval_group)})")
    if not (event.is_private or (int(event.chat_id) == int(approval_group))):
        logger.debug(f"DEBUG: wait_for_new_source: сообщение не в личке и не в группе модерации (chat_id={event.chat_id}), выходим")
        return
    logger.debug(f"DEBUG: Получено сообщение в режиме ожидания нового источника. sender_id={event.sender_id}, my_user_id={my_user_id}")
    if event.sender_id == my_user_id:
        logger.debug("DEBUG: Сообщение отправлено ботом, игнорируем.")
        return
    channel_id = None
    if event.fwd_from:
        logger.debug(f"DEBUG: event.fwd_from найден: {event.fwd_from!r}")
        # Новый способ: через from_id
        if hasattr(event.fwd_from, "channel_id") and event.fwd_from.channel_id:
            channel_id = str(event.fwd_from.channel_id)
            logger.debug(f"DEBUG: channel_id найден через event.fwd_from.channel_id: {channel_id}")
        elif hasattr(event.fwd_from, "from_id") and hasattr(event.fwd_from.from_id, "channel_id"):
            channel_id = str(event.fwd_from.from_id.channel_id)
            logger.debug(f"DEBUG: channel_id найден через event.fwd_from.from_id.channel_id: {channel_id}")
    else:
        logger.debug("DEBUG: event.fwd_from отсутствует")
    if channel_id:
        logger.info(f"INFO: Добавляем новый источник: {channel_id}")
        try:
            # Получаем объект канала для получения имени
            try:
                entity_id = int(channel_id)
                if not str(channel_id).startswith("-100"):
                    entity_id = int(f"-100{channel_id}")
                channel_entity = await event.client.get_entity(entity_id)
                channel_title = getattr(channel_entity, "title", str(channel_id))
                logger.debug(f"DEBUG: Получен объект канала: {channel_entity}")
            except Exception as e:
                logger.error(f"ERROR: Не удалось получить имя канала по id {channel_id}: {e}")
                channel_title = str(channel_id)
            # Пытаемся подписаться на канал
            try:
                await event.client(JoinChannelRequest(channel_entity))
                logger.info(f"INFO: Бот подписался на канал {channel_title} ({channel_id})")
            except Exception as e:
                logger.error(f"ERROR: Не удалось подписаться на канал {channel_id}: {e}")
            await add_source_channel(channel_id)
            awaiting_new_source = False
            await event.reply(f"Источник успешно добавлен: {channel_title}\n Все источники: /listsource ")
            logger.info(f"INFO: Источник {channel_id} ({channel_title}) успешно добавлен и подтверждён пользователю.")
        except Exception as e:
            logger.error(f"ERROR: Исключение при добавлении источника {channel_id}: {e}")
            await event.reply("Произошла ошибка при добавлении источника. Попробуйте ещё раз.")
    else:
        logger.warning("WARNING: Получено сообщение не из канала или без channel_id, игнорируем.")
        logger.debug(f"DEBUG: event.fwd_from = {event.fwd_from!r}")
        # Можно раскомментировать, если хочешь уведомлять пользователя:
        # await event.reply("Ошибка: сообщение должно быть переслано из канала.")

# ------------------------------
# Обработчик команды /listsource – выводит список всех источников
# ------------------------------
@events.register(events.NewMessage(pattern=r'^/listsource'))
async def handle_listsource(event):
    try:
        if not source_channels:
            await event.reply("Список источников пуст.")
            logger.info("INFO: Запрошен список источников, но он пуст.")
            return

        reply_lines = []
        for idx, channel_id in enumerate(source_channels, 1):
            try:
                entity_id = int(channel_id)
                if not str(channel_id).startswith("-100"):
                    entity_id = int(f"-100{channel_id}")
                channel_entity = await event.client.get_entity(entity_id)
                channel_title = getattr(channel_entity, "title", str(channel_id))
            except Exception as e:
                logger.error(f"ERROR: Не удалось получить имя канала по id {channel_id}: {e}")
                channel_title = "Неизвестно"
            reply_lines.append(f"{idx} : {channel_title} : {channel_id}")

        # Разбиваем на группы по 20
        chunk_size = 20
        for i in range(0, len(reply_lines), chunk_size):
            chunk = reply_lines[i:i+chunk_size]
            reply_text = "\n".join(chunk)
            await event.reply(f"Список источников (стр. {i//chunk_size+1}):\n{reply_text}")
        logger.info("INFO: Список источников отправлен пользователю.")
    except Exception as e:
        logger.error(f"ERROR: Ошибка при обработке /listsource: {e}")
        await event.reply("Произошла ошибка при получении списка источников.")

# ------------------------------
# Обработчик команды /remsource – удаляет источник (канал) по его ID
# ------------------------------
@events.register(events.NewMessage(pattern=r'^/remsource\s+(\-?\d+)'))
async def handle_remsource(event):
    try:
        match = re.match(r'^/remsource\s+(\-?\d+)', event.raw_text.strip())
        if not match:
            await event.reply("Пожалуйста, укажите ID канала для удаления, например: /remsource 2340184870")
            return

        channel_id = match.group(1)
        # Удаляем из базы данных
        async with aiosqlite.connect("fc_database.sqlite") as db:
            await db.execute("DELETE FROM source_channels WHERE channel_id = ?", (channel_id,))
            await db.commit()
        # Удаляем из оперативного списка
        if channel_id in source_channels:
            source_channels.remove(channel_id)
            logger.info(f"INFO: Источник {channel_id} удалён из списка.")
            await event.reply(f"Источник с ID {channel_id} успешно удалён.")
        else:
            logger.info(f"INFO: Попытка удалить несуществующий источник {channel_id}.")
            await event.reply(f"Источник с ID {channel_id} не найден в списке.")
    except Exception as e:
        logger.error(f"ERROR: Ошибка при удалении источника {channel_id}: {e}")
        await event.reply("Произошла ошибка при удалении источника.")

# ------------------------------
# Обработчик команды /settarget – устанавливает целевой канал
# ------------------------------
@events.register(events.NewMessage(pattern=r'^/settarget'))
async def handle_settarget(event):
    global set_target_mode
    reset_all_modes()
    set_target_mode = True
    await event.reply("Пожалуйста, перешлите сообщение из канала, который должен стать целевым.")

@events.register(events.NewMessage)
async def wait_for_settarget(event):
    global set_target_mode, awaiting_new_source, set_group_mode, set_group_wait_link, target_channel, my_user_id
    if not set_target_mode or awaiting_new_source or set_group_mode or set_group_wait_link:
        return
    if not (event.is_private or (event.chat_id == approval_group)):
        return
    if event.sender_id == my_user_id:
        return
    channel_id = None
    if event.fwd_from:
        if hasattr(event.fwd_from, "channel_id") and event.fwd_from.channel_id:
            channel_id = str(event.fwd_from.channel_id)
        elif hasattr(event.fwd_from, "from_id") and hasattr(event.fwd_from.from_id, "channel_id"):
            channel_id = str(event.fwd_from.from_id.channel_id)
    if channel_id:
        try:
            entity_id = int(channel_id)
            if not str(channel_id).startswith("-100"):
                entity_id = int(f"-100{channel_id}")
            channel_entity = await event.client.get_entity(entity_id)
            channel_title = getattr(channel_entity, "title", str(channel_id))
        except Exception as e:
            logger.error(f"ERROR: Не удалось получить имя канала по id {channel_id}: {e}")
            channel_title = str(channel_id)
        target_channel = int(entity_id)
        set_target_mode = False
        # Сохраняем целевой канал в базу
        async with aiosqlite.connect("fc_database.sqlite") as db:
            await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("target_channel", str(target_channel)))
            await db.commit()
        await event.reply(f"Канал {channel_title} установлен как целевой.")
        logger.info(f"INFO: Канал {channel_title} ({channel_id}) установлен как целевой.")
    else:
        logger.warning("WARNING: Получено сообщение не из канала или без channel_id, игнорируем.")

# ------------------------------
# Обработчик команды /setgroup – смена группы для одобрения (только в ЛС, с паролем)
# ------------------------------
@events.register(events.NewMessage(pattern=r'^/setgroup.*'))
async def handle_setgroup(event):
    global set_group_mode, set_group_wait_link
    if not event.is_private:
        return
    text = event.raw_text.strip().replace(" ", "")
    if f"/setgroup{SETGROUP_PASSWORD}" in text:
        reset_all_modes()
        set_group_mode = True
        set_group_wait_link = True
        await event.reply("Пожалуйста, добавьте меня в группу для курирования и пришлите ссылку на группу (например, t.me/xxxxx).")
    else:
        username = event.sender.username if event.sender and hasattr(event.sender, 'username') and event.sender.username else str(event.sender_id)
        await event.reply("давай не будем играться")
        logger.warning(f"WARNING: {username} пытается сменить нашу групу.")
        # Отправляем предупреждение в текущую approval_group
        try:
            await event.client.send_message(approval_group, f"warning!  {username} пытается сменить нашу групу")
        except Exception as e:
            logger.error(f"ERROR: Не удалось отправить предупреждение в approval_group: {e}")

@events.register(events.NewMessage)
async def wait_for_setgroup(event):
    global set_group_mode, set_group_wait_link, awaiting_new_source, set_target_mode, my_user_id, approval_group
    if not set_group_mode or not set_group_wait_link or awaiting_new_source or set_target_mode:
        return
    if not event.is_private:
        return
    if event.sender_id == my_user_id:
        return
    text = event.raw_text.strip()
    # Проверяем, что это ссылка t.me/xxxxx
    if not (text.startswith("t.me/") or text.startswith("https://t.me/")):
        await event.reply("Ссылка должна быть вида t.me/xxxxx")
        return
    # Приводим к username
    link = text.replace("https://", "").replace("http://", "").replace("t.me/", "").strip()
    if not link:
        await event.reply("Ссылка должна быть вида t.me/xxxxx")
        return
    try:
        entity = await event.client.get_entity(link)
        group_title = getattr(entity, "title", str(link))
        # Проверяем, что это именно группа, а не канал
        is_group = False
        if hasattr(entity, 'megagroup') and entity.megagroup:
            is_group = True
        if hasattr(entity, 'gigagroup') and entity.gigagroup:
            is_group = True
        if hasattr(entity, 'broadcast') and entity.broadcast:
            is_group = False
        if not is_group:
            await event.reply("Это канал, а не группа. Пожалуйста, пришлите ссылку на группу.")
            logger.warning(f"WARNING: Попытка установить канал {group_title} ({link}) как группу для одобрения — отклонено.")
            set_group_mode = False
            set_group_wait_link = False
            return
        val = str(entity.id)
        if not val.startswith('-100'):
            val = f'-100{val}'
        approval_group = int(val)
        set_group_mode = False
        set_group_wait_link = False
        # Сохраняем группу одобрения в базу
        async with aiosqlite.connect("fc_database.sqlite") as db:
            await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("approval_group", val))
            await db.commit()
        await event.reply(f"Теперь я буду отправлять весь контент в группу {group_title}")
        logger.info(f"INFO: Группа {group_title} ({link}) установлена как группа одобрения.")
    except Exception as e:
        await event.reply(f"Ошибка при определении группы по ссылке: {e}")
        logger.error(f"ERROR: Не удалось получить entity по ссылке {link}: {e}")
        set_group_mode = False
        set_group_wait_link = False

# ------------------------------
# Обработчик команды // – выводит список всех команд
# ------------------------------
@events.register(events.NewMessage(pattern=r'^//'))
async def handle_help(event):
    help_text = (
        "Доступные команды:\n"
        "/addsource — добавить новый канал-источник\n"
        "/listsource — список всех источников\n"
        "/remsource <id> — удалить источник по ID\n"
        "/settarget — установить целевой канал\n"
        "/setgroup — сменить группу для одобрения (только в ЛС, переслать сообщение из нужной группы)\n"
        "Для публикации сообщения в целевой канал — ответьте на сообщение 'ok'."
    )
    await event.reply(help_text)

# ------------------------------
# Фоновая задача: аптайм и статистика
# ------------------------------
async def periodic_uptime_report():
    print("[Uptime] печать аптайма стартовала", flush=True)
    try:
        while True:
            try:
                now = datetime.utcnow()
                uptime = now - start_time
                days = uptime.days
                hours, remainder = divmod(uptime.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                async with aiosqlite.connect("fc_database.sqlite") as db:
                    async with db.execute("SELECT COUNT(*) FROM forwarded_messages") as cur:
                        total_to_group = (await cur.fetchone())[0]
                    async with db.execute("SELECT COUNT(*) FROM forwarded_messages WHERE forwarded_to_target = 1") as cur:
                        total_to_target = (await cur.fetchone())[0]
                # print(f"[Uptime] now: {now.strftime('%Y-%m-%d %H:%M:%S')}")
                # print(f"[Uptime] {days}d:{hours:02}:{minutes:02} | Переслано в гру ппу: {total_to_group} | Переслано в целевой канал: {total_to_target}")
                print(f"{now.strftime('%Y-%m-%d %H:%M:%S')} | [Uptime] {days}d:{hours:02}:{minutes:02} | Переслано в группу: {total_to_group} | Переслано в целевой канал: {total_to_target}", flush=True)
            except Exception as e:
                print(f"[Uptime] Ошибка при подсчёте статистики: {e}", flush=True)
            await asyncio.sleep(600)  # 10 минут
    except Exception as e:
        print(f"[Uptime] задача по печати  аптайма  аварийно завершилась: {e}", flush=True)

# ------------------------------
# Основная функция запуска бота с обработкой KeyboardInterrupt
# ------------------------------
async def perform_qr_login(client):
    """Авторизация через QR-код (без SMS)."""
    try:
        print("Попытка авторизации через QR-код...")
        qr_login = await client.qr_login()
        qr = qrcode.QRCode()
        qr.add_data(qr_login.url)
        qr.make(fit=True)
        img = qr.make_image(fill='black', back_color='white')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        try:
            import PIL.Image
            PIL.Image.open(buf).show()
            print("QR-код также открыт в отдельном окне. Если не открылся — отсканируйте из консоли.")
        except Exception:
            pass
        print("Сканируйте этот QR-код в Telegram (Настройки → Устройства → Сканировать QR-код):")
        qr.print_ascii(invert=True)
        await qr_login.wait()
        logger.info("INFO: Авторизация через QR-код прошла успешно.")
        return await client.get_me()
    except Exception as e:
        logger.error(f"ERROR: Не удалось пройти авторизацию через QR-код: {e}")
        return None

async def perform_interactive_login(client):
    """Запускает интерактивную процедуру входа, если сессия не авторизована."""
    try:
        phone = input("Введите номер телефона (например, +71234567890): ").strip()
        await client.send_code_request(phone)
        code = input("Введите код из Telegram: ").strip()
        try:
            me = await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            pwd = getpass("Введите пароль 2FA: ")
            me = await client.sign_in(password=pwd)
        logger.info("INFO: Успешная авторизация пользователя.")
        return me
    except Exception as auth_e:
        logger.error(f"ERROR: Не удалось пройти интерактивную авторизацию: {auth_e}")
        # Попробуем QR-код
        logger.info("INFO: Пробуем авторизацию через QR-код...")
        return await perform_qr_login(client)

async def run_bot_forever():
    global my_user_id
    while True:
        try:
            logger.info("INFO: Запуск Telegram клиента...")
            client = await open_client_session(YOUR_API_ID, YOUR_API_HASH)

            me = await client.get_me()
            if me is None:
                logger.warning("WARNING: Клиент не авторизован. Запускаем интерактивную авторизацию.")
                me = await perform_interactive_login(client)
                if me is None:
                    logger.error("ERROR: Авторизация не удалась. Повтор через 30 секунд.")
                    await client.disconnect()
                    await asyncio.sleep(30)
                    continue

            my_user_id = me.id

            await init_db()  # Инициализируем базу данных и загружаем источники

            # Запускаем фоновую задачу аптайма
            asyncio.create_task(periodic_uptime_report())

            # Регистрируем обработчики
            client.add_event_handler(forward_to_approval, events.NewMessage)
            client.add_event_handler(check_approval_response, events.NewMessage(chats=approval_group))
            client.add_event_handler(handle_addsource, events.NewMessage(pattern=r'^/addsource'))
            client.add_event_handler(wait_for_new_source, events.NewMessage)
            client.add_event_handler(handle_listsource, events.NewMessage(pattern=r'^/listsource'))
            client.add_event_handler(handle_remsource, events.NewMessage(pattern=r'^/remsource\s+(\-?\d+)'))
            client.add_event_handler(handle_settarget, events.NewMessage(pattern=r'^/settarget'))
            client.add_event_handler(wait_for_settarget, events.NewMessage)
            client.add_event_handler(handle_setgroup, events.NewMessage(pattern=r'^/setgroup.*'))
            client.add_event_handler(wait_for_setgroup, events.NewMessage)
            client.add_event_handler(handle_help, events.NewMessage(pattern=r'^/help'))

            logger.info("INFO: Телеграм клиент запущен и готов к работе.")
            await client.run_until_disconnected()
            logger.warning("WARNING: Клиент отключился. Перезапуск через 5 секунд...")
        except KeyboardInterrupt:
            logger.info("INFO: Программа завершена пользователем (KeyboardInterrupt).")
            print("Программа завершена пользователем (KeyboardInterrupt).")
            sys.exit(0)
        except Exception as e:
            logger.error(f"ERROR: Критическая ошибка в основном цикле: {e}")
            import traceback
            traceback.print_exc()
            logger.info("INFO: Перезапуск через 5 секунд...")
            await asyncio.sleep(5)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
            logger.info("INFO: Сессия клиента закрыта.")

if __name__ == '__main__':
    try:
        asyncio.run(run_bot_forever())
    except KeyboardInterrupt:
        logger.info("INFO: Программа завершена пользователем (KeyboardInterrupt).")
        print("Программа завершена пользователем (KeyboardInterrupt).")
        sys.exit(0)
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")



# Как настроить автозапуск Python-скрипта через Task Scheduler
# 1. Откройте Планировщик заданий
# Нажмите Win+R, введите 
# taskschd.msc
# и нажмите Enter.
# 2. Создайте новую задачу
# В меню справа выберите Создать задачу... (не простую задачу!).
# 3. Вкладка "Общие"
# Дайте задаче имя, например: FlowCuratorBot
# Выберите "Выполнять для всех пользователей" (если нужно).
# Поставьте галочку "Выполнять с наивысшими правами" (если требуется доступ к сети/файлам).
# 4. Вкладка "Триггеры"
# Нажмите "Создать..."
# Выберите "При входе в систему" или "При запуске" (если бот должен стартовать при загрузке Windows).
# 5. Вкладка "Действия"
# Нажмите "Создать..."
# Действие: Запуск программы
# Программа или сценарий:
# Укажите путь к вашему интерпретатору Python, например:

#   C:\Users\Acer\AppData\Local\Programs\Python\Python311\python.exe

# (или где у вас установлен Python)
# Добавить аргументы:

# FC_bot_gtp4.1.py

# Рабочая папка:
# Укажите папку, где лежит ваш скрипт, например:

#   C:\Users\Acer\Documents\python_lessons\Sergios_projects\FlowCurator_Bot_tg_gpt4.1

# 6. Вкладка "Условия"
# Отключите "Запускать только при питании от сети" (если не нужно).
# В "Параметрах" можно включить "Перезапускать при сбое" и задать интервал.
# 7. Сохраните задачу
# Нажмите OK, введите пароль (если потребуется).
# Как увидеть вывод скрипта?
# Task Scheduler по умолчанию не показывает окно консоли.
# Если хотите видеть окно:
# В "Действии" укажите запуск не python.exe, а cmd.exe с аргументами:

#     /k python FC_bot_gtp4.1.py

# Это откроет консоль и не закроет её после завершения скрипта.
# Пример для поля "Действие":
# Программа или сценарий:
  
# cmd.exe
  
# Добавить аргументы:

# /k python FC_bot_gtp4.1.py

# Рабочая папка:

# C:\Users\Acer\Documents\python_lessons\Sergios_projects\FlowCurator_Bot_tg_gpt4.1
  


##################################
# Telethon API connecting issues :

# Test config 
# 149.154.167.40:443
#  Public keys 
#-----BEGIN RSA PUBLIC KEY-----
# MIIBCgKCAQEAyMEdY1aR+sCR3ZSJrtztKTKqigvO/vBfqACJLZtS7QMgCGXJ6XIR
# yy7mx66W0/sOFa7/1mAZtEoIokDP3ShoqF4fVNb6XeqgQfaUHd8wJpDWHcR2OFwv
# plUUI1PLTktZ9uW2WE23b+ixNwJjJGwBDJPQEQFBE+vfmH0JP503wr5INS1poWg/
# j25sIWeYPHYeOrFp/eXaqhISP6G+q2IeTaWTXpwZj4LzXq5YOpk4bYEQ6mvRq7D1
# aHWfYmlEGepfaYR8Q0YqvvhYtMte3ITnuSJs171+GDqpdKcSwHnd6FudwGO4pcCO
# j4WcDuXc2CTHgH8gFTNhp/Y8/SpDOhvn9QIDAQAB
# -----END RSA PUBLIC KEY-----

# production config 
# 149.154.167.50:443
# DC2
# -----BEGIN RSA PUBLIC KEY-----
# MIIBCgKCAQEA6LszBcC1LGzyr992NzE0ieY+BSaOW622Aa9Bd4ZHLl+TuFQ4lo4g
# 5nKaMBwK/BIb9xUfg0Q29/2mgIR6Zr9krM7HjuIcCzFvDtr+L0GQjae9H0pRB2OO
# 62cECs5HKhT5DZ98K33vmWiLowc621dQuwKWSQKjWf50XYFw42h21P2KXUGyp2y/
# +aEyZ+uVgLLQbRA1dEjSDZ2iGRy12Mk5gpYc397aYp438fsJoHIgJ2lgMv5h7WY9
# t6N/byY9Nw9p21Og3AoXSL2q/2IJ1WRUhebgAdGVMlV1fkuOQoEzR7EdpqtQD9Cs
# 5+bfo3Nhmcyvk5ftB0WkJ9z6bNZ7yxrP8wIDAQAB
# -----END RSA PUBLIC KEY-----


