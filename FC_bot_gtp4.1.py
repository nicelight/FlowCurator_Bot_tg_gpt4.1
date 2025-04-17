# Отправьте команду /addsource боту. Бот попросит переслать сообщение из нового канала. Перешлите сообщение, и бот автоматически добавит этот канал в список source channels и сохранит его в базе.


import asyncio
import logging
import sys
import signal
from telethon import TelegramClient, events
import aiosqlite
from datetime import datetime
import re
from telethon.tl.functions.channels import JoinChannelRequest


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
approval_group = -1002284347666    #  ID группы одобрения
target_channel = -1002252559154      # ID целевого канала


# ------------------------------
# Глобальные переменные
# ------------------------------
source_channels = []        # Список id источников (каналов) в виде строк
awaiting_new_source = False # Флаг ожидания нового источника после команды /addsource
my_user_id = None

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
# Создаем таблицы для хранения пересланных сообщений и источников каналов
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS forwarded_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_message_id TEXT NOT NULL,
                approval_message_id TEXT,
                source_channel_id TEXT NOT NULL,
                forward_date TEXT NOT NULL,
                grouped_id TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS source_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL UNIQUE,
                added_date TEXT NOT NULL
            )
        """)
        await db.commit()
        logger.info("INFO: База данных успешно проинициализирована.")
        async with db.execute("SELECT channel_id FROM source_channels") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                source_channels.append(row[0])
        logger.debug(f"DEBUG: Загружены источники: {source_channels}")
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
                                (str(orig_msg.id), str(fwd_msg.id), channel_id, datetime.utcnow().isoformat(), str(event.grouped_id))
                            )
                        await db.commit()
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
                                await event.reply(f"Переслано в {channel_title}")
                            else:
                                # Обычное сообщение
                                logger.info(f"INFO: Сообщение {original_message_id} одобрено, пересылаем в целевой канал.")
                                await event.client.forward_messages(
                                    entity=target_channel,
                                    messages=int(original_message_id),
                                    from_peer=int(source_channel_id)
                                )
                                await event.reply(f"Переслано в {channel_title}")
                        else:
                            logger.error(f"ERROR: Не найдена запись для сообщения {approval_msg_id}.")
    except Exception as e:
        logger.error(f"ERROR: Ошибка в обработчике одобрения: {e}")

# ------------------------------
# Обработчик команды /addsource – добавляет новый источник (канал)
# ------------------------------
@events.register(events.NewMessage(pattern=r'^/addsource'))
async def handle_addsource(event):
    global awaiting_new_source
    awaiting_new_source = True
    await event.reply("Пожалуйста, перешлите сообщение из нового канала, который хотите добавить в источники.")

# Обработчик ожидания нового источника
@events.register(events.NewMessage)
async def wait_for_new_source(event):
    global awaiting_new_source, my_user_id
    if not awaiting_new_source:
        return
    if not (event.is_private or (event.chat_id == approval_group)):
        # logger.debug(f"DEBUG: Сообщение получено не в личке и не в группе модерации (chat_id={event.chat_id}), игнорируем.")
        return
    logger.debug(f"DEBUG: Получено сообщение в режиме ожидания нового источника. sender_id={event.sender_id}, my_user_id={my_user_id}")
    if event.sender_id == my_user_id:
        logger.debug("DEBUG: Сообщение отправлено ботом, игнорируем.")
        return

    channel_id = None
    if event.fwd_from:
        # Новый способ: через from_id
        if hasattr(event.fwd_from, "channel_id") and event.fwd_from.channel_id:
            channel_id = str(event.fwd_from.channel_id)
        elif hasattr(event.fwd_from, "from_id") and hasattr(event.fwd_from.from_id, "channel_id"):
            channel_id = str(event.fwd_from.from_id.channel_id)

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

        reply_text = "\n".join(reply_lines)
        await event.reply(f"Список источников:\n{reply_text}")
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
# Обработчик команды // – выводит список всех команд
# ------------------------------
@events.register(events.NewMessage(pattern=r'^//'))
async def handle_help(event):
    help_text = (
        "Доступные команды:\n"
        "/addsource — добавить новый канал-источник\n"
        "/listsource — список всех источников\n"
        "/remsource <id> — удалить источник по ID\n"
        "Для публикации сообщения в целевой канал — ответьте на сообщение 'ok'."
    )
    await event.reply(help_text)

# ------------------------------
# Основная функция запуска бота с обработкой KeyboardInterrupt
# ------------------------------
async def main():
    global my_user_id
    try:
        client = await open_client_session(YOUR_API_ID, YOUR_API_HASH)
        me = await client.get_me()
        my_user_id = me.id
        await init_db()  # Инициализируем базу данных и загружаем источники

        # Регистрируем обработчики (если декораторы уже используются, их можно не дублировать)
        client.add_event_handler(forward_to_approval, events.NewMessage)
        client.add_event_handler(check_approval_response, events.NewMessage(chats=approval_group))
        client.add_event_handler(handle_addsource, events.NewMessage(pattern=r'^/addsource'))
        client.add_event_handler(wait_for_new_source, events.NewMessage)
        client.add_event_handler(handle_listsource, events.NewMessage(pattern=r'^/listsource'))
        client.add_event_handler(handle_remsource, events.NewMessage(pattern=r'^/remsource\s+(\-?\d+)'))
        client.add_event_handler(handle_help, events.NewMessage(pattern=r'^/help'))

        logger.info("INFO: Телеграм клиент запущен и готов к работе.")
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        logger.info("INFO: Программа завершена пользователем (KeyboardInterrupt).")
    except Exception as e:
        logger.error(f"ERROR: Ошибка в основном цикле: {e}")
    finally:
        await client.disconnect()
        logger.info("INFO: Сессия клиента закрыта.")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("INFO: Программа завершена пользователем (KeyboardInterrupt).")
        sys.exit(0)


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


