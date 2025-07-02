from hikkatl.types import Message
from .. import loader, utils
import time
from typing import Dict, List, Set, Tuple
from datetime import datetime, timedelta

@loader.tds
class MommyAfk(loader.Module):
    """Улучшенный AFK-модуль с интеллектуальной защитой от флуда"""
    
    strings = {
        "name": "MommyAfk",
    }

    def __init__(self):
        self.afk = False
        self.start_time = 0
        self.config = loader.ModuleConfig(
            # Настройки кулдаунов
            "user_cooldown", 600, "Задержка между ответами пользователю (сек)",
            "chat_cooldown", 300, "Задержка между ответами в чате (сек)",
            "global_cooldown", 5, "Минимальная задержка между любыми ответами (сек)",
            "max_replies_per_hour", 20, "Максимум ответов в час",
            
            # Текстовые сообщения
            "afk_on", "✅ <b>AFK включён</b>\nПричина: {}", "Сообщение при включении AFK",
            "afk_off", "❌ <b>AFK выключен</b>", "Сообщение при выключении AFK",
            "default_reason", "Недоступен", "Причина по умолчанию",
            "afk_response", "💤 <b>Сейчас я в АФК режиме</b>\n❇️ <b>Был онлайн:</b> {}\n📝 <b>Ушёл по причине:</b> {}\n\n", "Ответ в AFK режиме",
            "afk_status", "🔄 <b>Статус:</b> {}\n<b>Причина:</b> {}\n<b>Время AFK:</b> {}", "Статус AFK",
            "help", "📚 <b>Команды:</b>\n.afk [причина] - Вкл/выкл AFK\n.afkstatus - Проверить статус", "Справка по модулю",
            "flood_warning", "⏳ Получил ваше сообщение, но сейчас не могу ответить из-за ограничений Telegram.", "Предупреждение о флуде",
            "notified_list", "📋 <b>Список пользователей, получивших AFK-ответ:</b>\n\n{}", "Заголовок списка уведомлений",
            "notified_item", "👤 {}. <a href='tg://user?id={}'>{}</a> (сообщений: {})", "Элемент списка уведомлений",
            "no_notifications", "ℹ️ <b>Никто не получил AFK-ответ во время вашего отсутствия</b>", "Сообщение при отсутствии уведомлений"
        )
        self.user_cooldowns: Dict[int, datetime] = {}
        self.chat_cooldowns: Dict[int, datetime] = {}
        self.global_last_reply: datetime = datetime.min
        self.reply_history: List[datetime] = []
        self.notified_users: Dict[int, Tuple[str, str, int]] = {}  # ID: (имя, юзернейм, счётчик)

    async def client_ready(self, client, db):
        self._client = client
        self._me = await client.get_me()

    def _check_flood_limits(self) -> bool:
        """Проверяет все уровни ограничений"""
        now = datetime.now()
        
        # Очистка старых записей (старше 1 часа)
        self.reply_history = [t for t in self.reply_history if now - t < timedelta(hours=1)]
        
        # Проверка глобального кулдауна
        if (now - self.global_last_reply).total_seconds() < self.config["global_cooldown"]:
            return True
            
        # Проверка лимита ответов в час
        if len(self.reply_history) >= self.config["max_replies_per_hour"]:
            return True
            
        return False

    async def _send_afk_response(self, message: Message, is_mention: bool = False) -> bool:
        """Отправляет ответ AFK с учетом контекста"""
        if self._check_flood_limits():
            return False

        try:
            duration = self._format_duration_detailed((datetime.now() - datetime.fromtimestamp(self.start_time)).total_seconds())
            response = self.config["afk_response"].format(duration, self.reason)
            
            await message.reply(response)
            
            # Сохраняем информацию о пользователе
            try:
                user = await message.get_sender()
                user_name = getattr(user, "first_name", "Unknown") or getattr(user, "title", "Unknown")
                username = getattr(user, "username", None) or "нет"
                
                # Обновляем счётчик сообщений
                if user.id in self.notified_users:
                    name, uname, count = self.notified_users[user.id]
                    self.notified_users[user.id] = (name, uname, count + 1)
                else:
                    self.notified_users[user.id] = (user_name, username, 1)
            except Exception as e:
                print(f"Error saving user info: {e}")
            
            # Обновление истории ответов
            now = datetime.now()
            self.reply_history.append(now)
            self.global_last_reply = now
            return True
        except Exception as e:
            print(f"AFK reply error: {e}")
            return False

    async def watcher(self, message: Message):
        if not self.afk or message.out:
            return
            
        try:
            user_id = message.sender_id
            chat_id = message.chat_id
            
            if hasattr(user_id, 'user_id'):
                user_id = user_id.user_id
                
            user_id = int(user_id)
            chat_id = int(chat_id)
        except:
            return

        now = datetime.now()
        
        # Всегда помечаем сообщение как прочитанное
        try:
            await message.client.send_read_acknowledge(message.chat_id, clear_mentions=True)
        except Exception as e:
            print(f"Error marking as read: {e}")

        # Проверяем, является ли отправитель ботом
        try:
            sender = await message.get_sender()
            if getattr(sender, "bot", False):
                return  # Не отвечаем ботам, только пометили прочитанным
        except:
            pass

        # Проверяем, нужно ли отвечать
        is_private = message.is_private
        is_mention = getattr(message, "mentioned", False) or (
            self._me.username and f"@{self._me.username}" in message.raw_text.lower()
        )
        is_reply = False
        
        if message.reply_to_msg_id:
            try:
                replied_msg = await message.get_reply_message()
                if replied_msg.sender_id == self._me.user_id:
                    is_reply = True
            except:
                pass

        # Определяем контекст ответа
        respond_in_private = is_private and user_id not in self.user_cooldowns
        respond_in_chat = (is_mention or is_reply) and chat_id not in self.chat_cooldowns

        if not (respond_in_private or respond_in_chat):
            return

        # Проверка кулдаунов
        if user_id in self.user_cooldowns:
            if (now - self.user_cooldowns[user_id]).total_seconds() < self.config["user_cooldown"]:
                return
                
        if chat_id in self.chat_cooldowns:
            if (now - self.chat_cooldowns[chat_id]).total_seconds() < self.config["chat_cooldown"]:
                return

        # Отправляем ответ в нужном контексте
        if respond_in_private:
            if await self._send_afk_response(message):
                self.user_cooldowns[user_id] = now
                
        if respond_in_chat and (is_mention or is_reply):
            if await self._send_afk_response(message, is_mention=True):
                self.chat_cooldowns[chat_id] = now

    @loader.command(aliases=["afk", "афк"])
    async def afkcmd(self, message: Message):
        """Включение/выключение AFK режима"""
        args = utils.get_args_raw(message)
        
        if self.afk:
            # Формируем список уведомленных пользователей
            notified_list = []
            for idx, (user_id, (name, username, count)) in enumerate(self.notified_users.items(), 1):
                notified_list.append(self.config["notified_item"].format(
                    idx, user_id, name, count
                ))
            
            if notified_list:
                response = self.config["notified_list"].format("\n".join(notified_list))
            else:
                response = self.config["no_notifications"]
            
            self.afk = False
            self.user_cooldowns.clear()
            self.chat_cooldowns.clear()
            await utils.answer(message, self.config["afk_off"] + "\n\n" + response)
            self.notified_users.clear()
        else:
            self.afk = True
            self.reason = args if args else self.config["default_reason"]
            self.start_time = time.time()
            self.notified_users.clear()
            await utils.answer(message, self.config["afk_on"].format(self.reason))

    @loader.command(aliases=["afkstatus", "афкстатус"])
    async def afkstat(self, message: Message):
        """Проверка текущего статуса AFK"""
        status = "🟢 Включен" if self.afk else "🔴 Выключен"
        reason = self.reason if self.afk else "Нет"
        duration = self._format_duration(time.time() - self.start_time) if self.afk else "—"
        
        await utils.answer(message, self.config["afk_status"].format(status, reason, duration))

    def _format_duration(self, seconds: float) -> str:
        """Форматирование времени (кратко)"""
        minutes, _ = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours}ч {minutes}м" if hours else f"{minutes}м"

    def _format_duration_detailed(self, seconds: float) -> str:
        """Подробное форматирование времени"""
        seconds = int(seconds)
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        parts = []
        if days > 0:
            parts.append(f"{days} д.")
        if hours > 0:
            parts.append(f"{hours} ч.")
        if minutes > 0:
            parts.append(f"{minutes} мин.")
        if seconds > 0 and days == 0 and hours == 0:
            parts.append(f"{seconds} сек.")
            
        return " ".join(parts) if parts else "0 сек."

    @loader.command()
    async def afkhelp(self, message: Message):
        """Помощь по модулю"""
        await utils.answer(message, self.config["help"])

    async def on_unload(self):
        self.user_cooldowns.clear()
        self.chat_cooldowns.clear()
        self.notified_users.clear()
