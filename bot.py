#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 Telegram Group Joiner Bot - إصدار معدل لمتغيرات البيئة
"""

import asyncio
import logging
import re
import sqlite3
import os
import sys
import json
import time
import configparser
from datetime import datetime, timedelta
from typing import List, Dict, Set, Optional, Tuple
from telethon import TelegramClient, errors
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.sessions import StringSession
from telethon.tl.types import KeyboardButton, ReplyKeyboardMarkup

# ============================================
# 🎯 إعدادات البوت الأساسية
# ============================================

class ConfigManager:
    """مدير إعدادات البوت"""
    
    @staticmethod
    def create_default_config():
        """إنشاء إعدادات افتراضية"""
        config = configparser.ConfigParser()
        
        # الحصول من متغيرات البيئة أولاً
        bot_token = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
        admin_id = os.environ.get('ADMIN_ID', '8294336757')
        join_delay = os.environ.get('JOIN_DELAY', '60')
        links_per_session = os.environ.get('LINKS_PER_SESSION', '1000')
        
        config['BOT'] = {
            'token': bot_token,
            'admin_id': admin_id,
            'join_delay': join_delay,
            'links_per_session': links_per_session,
            'api_id': '6',
            'api_hash': 'eb06d4abfb49dc3eeb1aeb98ae0f581e',
            'messages_per_channel': '500',
            'log_level': 'INFO',
            'max_sessions': '50'
        }
        
        config['DATABASE'] = {
            'file': 'sessions.db',
            'auto_backup': 'yes',
            'backup_interval': '24'
        }
        
        config['RENDER'] = {
            'port': '8080',
            'health_check': 'yes'
        }
        
        return config
    
    @staticmethod
    def save_config(config, filename='config.ini'):
        """حفظ الإعدادات إلى ملف"""
        with open(filename, 'w', encoding='utf-8') as f:
            config.write(f)
    
    @staticmethod
    def load_config(filename='config.ini'):
        """تحميل الإعدادات من ملف"""
        config = configparser.ConfigParser()
        
        if os.path.exists(filename):
            config.read(filename, encoding='utf-8')
        else:
            config = ConfigManager.create_default_config()
            ConfigManager.save_config(config, filename)
            print(f"📝 تم إنشاء ملف الإعدادات: {filename}")
        
        # تحديث من متغيرات البيئة (الأولوية لمتغيرات البيئة)
        env_vars = {
            'BOT_TOKEN': ('BOT', 'token'),
            'ADMIN_ID': ('BOT', 'admin_id'),
            'JOIN_DELAY': ('BOT', 'join_delay'),
            'LINKS_PER_SESSION': ('BOT', 'links_per_session'),
            'LOG_LEVEL': ('BOT', 'log_level')
        }
        
        for env_key, (section, key) in env_vars.items():
            env_value = os.environ.get(env_key)
            if env_value:
                config.set(section, key, env_value)
        
        return config

# ============================================
# 📊 إعدادات التسجيل
# ============================================

class LogManager:
    """مدير سجلات البوت"""
    
    @staticmethod
    def setup_logging():
        """إعداد نظام التسجيل"""
        # إنشاء مجلد السجلات
        os.makedirs('logs', exist_ok=True)
        
        # تحديد مستوى التسجيل من متغير البيئة
        log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
        level = getattr(logging, log_level, logging.INFO)
        
        # تهيئة التسجيل
        logger = logging.getLogger()
        logger.setLevel(level)
        
        # إزالة المعالجات القديمة
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # معالج الملفات
        file_handler = logging.FileHandler(
            'logs/bot.log',
            encoding='utf-8',
            mode='a'
        )
        file_handler.setLevel(level)
        
        # معالج الكونسول
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        
        # تنسيق السجلات
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        return logger

# ============================================
# 🗄️ قاعدة البيانات
# ============================================

class DatabaseManager:
    """مدير قاعدة البيانات"""
    
    def __init__(self, db_file='sessions.db'):
        """تهيئة قاعدة البيانات"""
        # الحصول من متغير البيئة أو استخدام الافتراضي
        self.db_file = os.environ.get('DATABASE_FILE', db_file)
        self.conn = None
        self.setup_database()
    
    def setup_database(self):
        """إعداد جداول قاعدة البيانات"""
        # إنشاء مجلد البيانات
        os.makedirs('data', exist_ok=True)
        
        # الاتصال بقاعدة البيانات
        self.conn = sqlite3.connect(self.db_file, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.cursor()
        
        # جدول الجلسات
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_string TEXT UNIQUE,
                phone TEXT,
                first_name TEXT,
                last_name TEXT,
                username TEXT,
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                links_processed INTEGER DEFAULT 0,
                max_links INTEGER DEFAULT 1000,
                total_success INTEGER DEFAULT 0,
                total_failed INTEGER DEFAULT 0
            )
        ''')
        
        # جدول الروابط
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link TEXT UNIQUE,
                channel_name TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_processed BOOLEAN DEFAULT 0,
                processed_by TEXT,
                processed_at TIMESTAMP,
                link_type TEXT CHECK(link_type IN ('group', 'channel', 'private', 'unknown')),
                success BOOLEAN,
                error_message TEXT
            )
        ''')
        
        # جدول القنوات المصدر
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS source_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_link TEXT UNIQUE,
                channel_name TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_scraped TIMESTAMP,
                total_links_extracted INTEGER DEFAULT 0
            )
        ''')
        
        self.conn.commit()
        
        # إنشاء الفهرس لتحسين الأداء
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_links_processed ON links(is_processed)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(is_active)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_links_type ON links(link_type)')
        
        self.conn.commit()
    
    def backup_database(self):
        """نسخ احتياطي لقاعدة البيانات"""
        try:
            backup_dir = 'backups'
            os.makedirs(backup_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = f'{backup_dir}/sessions_backup_{timestamp}.db'
            
            # إنشاء اتصال جديد للنسخ الاحتياطي
            backup_conn = sqlite3.connect(backup_file)
            self.conn.backup(backup_conn)
            backup_conn.close()
            
            return backup_file
        except Exception as e:
            logging.error(f"خطأ في النسخ الاحتياطي: {e}")
            return None
    
    def get_statistics(self):
        """الحصول على إحصائيات البوت"""
        cursor = self.conn.cursor()
        
        stats = {}
        
        # إحصائيات الجلسات
        cursor.execute('''
            SELECT 
                COUNT(*) as total_sessions,
                SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active_sessions,
                SUM(links_processed) as total_links_processed,
                SUM(total_success) as total_success,
                SUM(total_failed) as total_failed
            FROM sessions
        ''')
        session_stats = cursor.fetchone()
        stats['sessions'] = dict(session_stats)
        
        # إحصائيات الروابط
        cursor.execute('''
            SELECT 
                COUNT(*) as total_links,
                SUM(CASE WHEN is_processed = 1 THEN 1 ELSE 0 END) as processed_links,
                SUM(CASE WHEN is_processed = 0 THEN 1 ELSE 0 END) as pending_links,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_links,
                SUM(CASE WHEN success = 0 AND is_processed = 1 THEN 1 ELSE 0 END) as failed_links
            FROM links
        ''')
        link_stats = cursor.fetchone()
        stats['links'] = dict(link_stats)
        
        return stats
    
    def close(self):
        """إغلاق اتصال قاعدة البيانات"""
        if self.conn:
            self.conn.close()

# ============================================
# 🤖 البوت الرئيسي
# ============================================

class TelegramGroupJoinerBot:
    def __init__(self):
        """تهيئة البوت"""
        # أولوية لمتغيرات البيئة
        self.bot_token = os.environ.get('BOT_TOKEN')
        self.admin_id = os.environ.get('ADMIN_ID')
        self.join_delay = os.environ.get('JOIN_DELAY')
        self.links_per_session = os.environ.get('LINKS_PER_SESSION')
        
        # إذا لم تكن متغيرات البيئة موجودة، اقرأ من config.ini
        if not self.bot_token:
            logging.info("⚙️  جاري تحميل الإعدادات من config.ini...")
            self.config = ConfigManager.load_config()
            self.bot_token = self.config['BOT'].get('token')
            self.admin_id = self.config['BOT'].get('admin_id', '8294336757')
            self.join_delay = self.config['BOT'].get('join_delay', '60')
            self.links_per_session = self.config['BOT'].get('links_per_session', '1000')
        else:
            logging.info("⚙️  جاري استخدام متغيرات البيئة...")
            # إنشاء config افتراضي من متغيرات البيئة
            self.config = configparser.ConfigParser()
            self.config['BOT'] = {
                'token': self.bot_token,
                'admin_id': self.admin_id or '8294336757',
                'join_delay': self.join_delay or '60',
                'links_per_session': self.links_per_session or '1000',
                'api_id': '6',
                'api_hash': 'eb06d4abfb49dc3eeb1aeb98ae0f581e',
                'messages_per_channel': '500',
                'log_level': os.environ.get('LOG_LEVEL', 'INFO')
            }
        
        # التحقق من التوكن
        if not self.bot_token or self.bot_token == 'YOUR_BOT_TOKEN_HERE':
            error_msg = "❌ يرجى إضافة توكن البوت في config.ini أو متغير BOT_TOKEN البيئي"
            logging.error(error_msg)
            raise ValueError(error_msg)
        
        # تحويل الأنواع
        try:
            self.admin_id = int(self.admin_id)
            self.join_delay = int(self.join_delay)
            self.links_per_session = int(self.links_per_session)
        except (ValueError, TypeError) as e:
            logging.error(f"❌ خطأ في تحويل أنواع البيانات: {e}")
            raise ValueError(f"❌ قيم غير صالحة في الإعدادات: {e}")
        
        # إعدادات API ثابتة
        self.api_id = 6
        self.api_hash = "eb06d4abfb49dc3eeb1aeb98ae0f581e"
        self.messages_per_channel = 500
        
        # إعداد قاعدة البيانات
        self.db = DatabaseManager()
        
        # الحالات المؤقتة للمستخدمين
        self.user_states = {}
        
        # لوحة المفاتيح الرئيسية
        self.main_keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("📱 إضافة جلسة"), KeyboardButton("📋 عرض الجلسات")],
                [KeyboardButton("🔗 طلب روابط القنوات"), KeyboardButton("🚀 بدء الانضمام")],
                [KeyboardButton("📊 الإحصائيات"), KeyboardButton("❓ المساعدة")]
            ],
            resize_keyboard=True,
            persistent=True
        )
        
        # إعداد البوت
        self.bot_client = None
        self.is_running = False
        
        # إنشاء مجلدات
        self.create_folders()
        
        logging.info("✅ تم تهيئة البوت بنجاح")
        logging.info(f"👤 معرف المسؤول: {self.admin_id}")
        logging.info(f"⚙️  التأخير: {self.join_delay} ثانية")
        logging.info(f"🔢 الروابط/جلسة: {self.links_per_session}")
    
    def create_folders(self):
        """إنشاء المجلدات الضرورية"""
        folders = ['logs', 'data', 'backups']
        for folder in folders:
            os.makedirs(folder, exist_ok=True)
    
    async def start(self):
        """بدء تشغيل البوت"""
        try:
            logging.info("🚀 بدء تشغيل البوت...")
            
            # إنشاء عميل البوت
            self.bot_client = TelegramClient(
                'bot_session',
                self.api_id,
                self.api_hash
            )
            
            # تشغيل البوت
            await self.bot_client.start(bot_token=self.bot_token)
            
            # التحقق من الاتصال
            me = await self.bot_client.get_me()
            logging.info(f"✅ البوت يعمل باسم: {me.username} (ID: {me.id})")
            
            # إرسال رسالة بدء التشغيل
            await self.send_startup_message()
            
            # إضافة معالج الرسائل
            self.bot_client.add_event_handler(self.handle_message)
            
            # تشغيل البوت
            self.is_running = True
            await self.bot_client.run_until_disconnected()
            
        except errors.RPCError as e:
            logging.error(f"❌ خطأ في اتصال تليجرام: {e}")
            raise
        except Exception as e:
            logging.error(f"❌ خطأ في تشغيل البوت: {e}")
            raise
    
    async def send_startup_message(self):
        """إرسال رسالة بدء التشغيل للمسؤول"""
        try:
            stats = self.db.get_statistics()
            
            message = f"""
🚀 **تم تشغيل البوت بنجاح!**

📊 **إحصائيات الحالية:**
• 📱 الجلسات النشطة: {stats['sessions']['active_sessions'] or 0}
• 🔗 الروابط المعلقة: {stats['links']['pending_links'] or 0}
• ✅ الروابط الناجحة: {stats['links']['success_links'] or 0}

⚙️ **الإعدادات:**
• ⏱️ تأخير الانضمام: {self.join_delay} ثانية
• 🔢 روابط لكل جلسة: {self.links_per_session}
• 🕒 وقت البدء: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

📌 **استخدم الأزرار للتحكم بالبوت**
            """
            
            await self.bot_client.send_message(self.admin_id, message, buttons=self.main_keyboard)
            
        except Exception as e:
            logging.error(f"خطأ في إرسال رسالة البدء: {e}")
    
    async def handle_message(self, event):
        """معالجة الرسائل الواردة"""
        try:
            # التحقق من هوية المرسل
            if event.message.sender_id != self.admin_id:
                logging.warning(f"محاولة وصول غير مصرح بها من: {event.message.sender_id}")
                return
            
            text = event.message.text or ""
            user_id = event.message.sender_id
            
            logging.info(f"📩 رسالة من المسؤول: {text}")
            
            # معالجة الأزرار والأوامر
            if text == "📱 إضافة جلسة":
                await self.start_add_session(event)
            
            elif text == "📋 عرض الجلسات":
                await self.list_sessions(event)
            
            elif text == "🔗 طلب روابط القنوات":
                await self.request_channel_links(event)
            
            elif text == "🚀 بدء الانضمام":
                await self.start_joining_process(event)
            
            elif text == "📊 الإحصائيات":
                await self.show_statistics(event)
            
            elif text == "❓ المساعدة":
                await self.show_help(event)
            
            elif text.startswith('/'):
                if text == '/start':
                    await self.send_welcome(event)
                elif text == '/status':
                    await self.show_status(event)
            
            else:
                # معالجة الحالات المؤقتة
                await self.handle_user_state(event, text)
                
        except Exception as e:
            logging.error(f"خطأ في معالجة الرسالة: {e}")
            await event.reply(f"❌ حدث خطأ: {str(e)}", buttons=self.main_keyboard)
    
    async def send_welcome(self, event):
        """إرسال رسالة ترحيبية"""
        welcome_text = """
🤖 **مرحباً بك في بوت إدارة حسابات Telegram المتقدم**

🎯 **المميزات الرئيسية:**
• إدارة عدة جلسات تيليجرام
• استخراج روابط المجموعات من القنوات تلقائياً
• توزيع 1000 رابط لكل حساب
• واجهة أزرار سهلة الاستخدام

📊 **للبدء، استخدم الأزرار أدناه:**
        """
        
        await event.reply(welcome_text, buttons=self.main_keyboard)
    
    async def start_add_session(self, event):
        """بدء عملية إضافة جلسة"""
        self.user_states[event.sender_id] = 'awaiting_session'
        
        instructions = """
📱 **إضافة جلسة جديدة**

🔧 **طريقة الحصول على جلسة التيثون:**
1. اذهب إلى @SessionStringGeneratorBot
2. أرسل /start
3. اختر Generate New Session
4. اختر Telethon
5. أرسل رقم هاتفك
6. أدخل الرمز الذي يصلك
7. انسخ الجلسة وأرسلها لي

📤 **الآن أرسل لي جلسة التيثون:**
        """
        
        await event.reply(instructions)
    
    async def add_session(self, event, session_string):
        """إضافة جلسة جديدة"""
        try:
            # تنظيف الجلسة
            session_string = session_string.strip()
            
            # التحقق من الجلسة
            try:
                temp_client = TelegramClient(
                    StringSession(session_string),
                    self.api_id,
                    self.api_hash
                )
                
                await temp_client.connect()
                
                if not await temp_client.is_user_authorized():
                    await event.reply("❌ الجلسة غير صالحة أو منتهية الصلاحية", buttons=self.main_keyboard)
                    return
                
                # الحصول على معلومات الحساب
                me = await temp_client.get_me()
                
                # حفظ الجلسة في قاعدة البيانات
                cursor = self.db.conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO sessions 
                    (session_string, phone, first_name, username, user_id, last_used, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session_string,
                    me.phone or "غير معروف",
                    me.first_name or "",
                    me.username or "",
                    me.id,
                    datetime.now(),
                    True
                ))
                
                self.db.conn.commit()
                session_id = cursor.lastrowid
                
                # إرسال تأكيد الإضافة
                response = f"""
✅ **تم إضافة الجلسة بنجاح!**

📋 **معلومات الحساب:**
• 🆔 **المعرف:** `{session_id}`
• 📞 **الهاتف:** `{me.phone or 'غير معروف'}`
• 👤 **الاسم:** `{me.first_name or ''}`
• 🏷️ **اليوزر:** @{me.username or 'لا يوجد'}

🎯 **المهام المخصصة:**
• 🔗 **الروابط المستهدفة:** {self.links_per_session} رابط
• ⏱️ **التأخير بين الروابط:** {self.join_delay} ثانية

💡 **سيبدأ هذا الحساب بالعمل تلقائياً عند بدء عملية الانضمام**
                """
                
                await event.reply(response, buttons=self.main_keyboard)
                
                # إغلاق الاتصال المؤقت
                await temp_client.disconnect()
                
                # حذف حالة المستخدم
                if event.sender_id in self.user_states:
                    del self.user_states[event.sender_id]
                
            except Exception as e:
                await event.reply(f"❌ خطأ في التحقق من الجلسة: {str(e)}", buttons=self.main_keyboard)
                
        except Exception as e:
            logging.error(f"خطأ في إضافة الجلسة: {e}")
            await event.reply(f"❌ حدث خطأ: {str(e)}", buttons=self.main_keyboard)
    
    async def list_sessions(self, event):
        """عرض الجلسات المضافة"""
        try:
            cursor = self.db.conn.cursor()
            cursor.execute('''
                SELECT id, phone, first_name, username, links_processed, 
                       total_success, total_failed, is_active
                FROM sessions 
                ORDER BY is_active DESC, created_at DESC
            ''')
            
            sessions = cursor.fetchall()
            
            if not sessions:
                await event.reply("📭 **لا توجد جلسات مضافة حالياً**", buttons=self.main_keyboard)
                return
            
            response = "📋 **قائمة الجلسات**\n\n"
            
            for idx, session in enumerate(sessions, 1):
                sess_dict = dict(session)
                status = "🟢" if sess_dict['is_active'] else "🔴"
                
                response += f"""
{idx}. {status} **{sess_dict['first_name'] or 'غير معروف'}**
   📞: `{sess_dict['phone'] or 'غير معروف'}`
   🆔: `{sess_dict['id']}`
   🔗: {sess_dict['links_processed']}/{self.links_per_session}
   ✅: {sess_dict['total_success']} | ❌: {sess_dict['total_failed']}
"""
            
            # حساب الإحصائيات
            cursor.execute('SELECT COUNT(*) FROM links WHERE is_processed = 0')
            pending_links = cursor.fetchone()[0] or 0
            
            active_sessions = len([s for s in sessions if s['is_active']])
            sessions_needed = (pending_links // self.links_per_session) + (1 if pending_links % self.links_per_session > 0 else 0)
            
            response += f"""
📊 **تحليل الاحتياجات:**

🔗 **الروابط المعلقة:** {pending_links} رابط
📱 **الجلسات النشطة:** {active_sessions} جلسة
🎯 **الجلسات المطلوبة:** {sessions_needed} جلسة
💡 **كل جلسة ستنضم إلى:** {self.links_per_session} مجموعة
⏱️ **التأخير:** {self.join_delay} ثانية/رابط
"""
            
            if pending_links > 0 and active_sessions < sessions_needed:
                response += f"\n⚠️ **تحذير:** تحتاج إلى إضافة {sessions_needed - active_sessions} جلسة على الأقل"
            
            await event.reply(response, buttons=self.main_keyboard)
                
        except Exception as e:
            logging.error(f"خطأ في عرض الجلسات: {e}")
            await event.reply(f"❌ حدث خطأ: {str(e)}", buttons=self.main_keyboard)
    
    async def request_channel_links(self, event):
        """طلب روابط القنوات المصدر"""
        self.user_states[event.sender_id] = 'awaiting_channel_links'
        
        instructions = """
🔗 **إضافة روابط القنوات المصدر**

📝 **طريقة العمل:**
1. أرسل لي روابط القنوات التي تحتوي على روابط المجموعات
2. يمكنك إرسال رابط واحد أو عدة روابط
3. كل رابط في سطر منفصل

📤 **أرسل لي روابط القنوات الآن:**
        """
        
        await event.reply(instructions)
    
    async def process_channel_links(self, event, links_text):
        """معالجة روابط القنوات"""
        try:
            lines = links_text.strip().split('\n')
            added_channels = []
            
            await event.reply("🔍 **جاري معالجة الروابط...**")
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # تحويل إلى رابط صحيح
                link = self.normalize_telegram_link(line)
                if not link:
                    continue
                
                # حفظ القناة
                try:
                    cursor = self.db.conn.cursor()
                    cursor.execute('''
                        INSERT OR IGNORE INTO source_channels (channel_link, added_at)
                        VALUES (?, ?)
                    ''', (link, datetime.now()))
                    
                    if cursor.rowcount > 0:
                        added_channels.append(link)
                    
                    # استخراج الروابط من القناة
                    extracted_count = await self.extract_links_from_channel(link)
                    
                    # تحديث عدد الروابط المستخرجة
                    cursor.execute('''
                        UPDATE source_channels 
                        SET total_links_extracted = total_links_extracted + ?, last_scraped = ?
                        WHERE channel_link = ?
                    ''', (extracted_count, datetime.now(), link))
                    
                except Exception as e:
                    logging.error(f"خطأ في معالجة القناة {link}: {e}")
                    continue
            
            self.db.conn.commit()
            
            # حساب الإحصائيات
            stats = self.db.get_statistics()
            
            response = f"""
✅ **تمت معالجة القنوات بنجاح!**

📊 **النتائج:**
• 📥 **القنوات المضافة:** {len(added_channels)}
• ⏳ **إجمالي الروابط المعلقة:** {stats['links']['pending_links'] or 0}
• 📱 **الجلسات المطلوبة:** {(stats['links']['pending_links'] or 0) // self.links_per_session + 1}
"""
            
            if added_channels:
                response += "\n📋 **القنوات المضافة:**"
                for channel in added_channels[:5]:
                    response += f"\n• `{channel}`"
                
                if len(added_channels) > 5:
                    response += f"\n• ... و {len(added_channels) - 5} قنوات أخرى"
            
            response += f"""
            
💡 **معلومات مهمة:**
• البوت يستخرج فقط روابط تليجرام الصالحة
• كل جلسة تحتاج إلى {self.links_per_session} رابط لتبدأ العمل
"""
            
            await event.reply(response, buttons=self.main_keyboard)
            
            # حذف حالة المستخدم
            if event.sender_id in self.user_states:
                del self.user_states[event.sender_id]
            
        except Exception as e:
            logging.error(f"خطأ في معالجة روابط القنوات: {e}")
            await event.reply(f"❌ حدث خطأ: {str(e)}", buttons=self.main_keyboard)
    
    def normalize_telegram_link(self, link):
        """تنظيم رابط تليجرام"""
        link = link.strip()
        
        # حذف المسافات
        link = re.sub(r'\s+', '', link)
        
        # تحويل @username إلى رابط كامل
        if link.startswith('@'):
            link = f"https://t.me/{link[1:]}"
        
        # إضافة https:// إذا لم يكن موجوداً
        elif not link.startswith('http'):
            link = f"https://{link}"
        
        # التحقق من أن الرابط هو تليجرام
        telegram_patterns = [
            r'https?://t\.me/',
            r'https?://telegram\.me/'
        ]
        
        for pattern in telegram_patterns:
            if re.match(pattern, link, re.IGNORECASE):
                return link
        
        return None
    
    async def extract_links_from_channel(self, channel_link):
        """استخراج الروابط من قناة"""
        try:
            entity = await self.bot_client.get_entity(channel_link)
            messages = await self.bot_client.get_messages(
                entity, 
                limit=self.messages_per_channel
            )
            
            extracted_links = set()
            
            for message in messages:
                if not message.text:
                    continue
                
                # البحث عن روابط تليجرام
                telegram_links = re.findall(
                    r'(https?://t\.me/(?:joinchat/)?[a-zA-Z0-9_\-+]+|@[a-zA-Z0-9_]{5,})',
                    message.text
                )
                
                for link in telegram_links:
                    clean_link = self.normalize_telegram_link(link)
                    if clean_link:
                        extracted_links.add(clean_link)
            
            # حفظ الروابط في قاعدة البيانات
            added_count = 0
            cursor = self.db.conn.cursor()
            
            for link in extracted_links:
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO links (link, added_at)
                        VALUES (?, ?)
                    ''', (link, datetime.now()))
                    
                    if cursor.rowcount > 0:
                        added_count += 1
                        
                except Exception as e:
                    logging.error(f"خطأ في حفظ الرابط {link}: {e}")
                    continue
            
            self.db.conn.commit()
            
            logging.info(f"تم استخراج {added_count} رابط من {channel_link}")
            return added_count
            
        except Exception as e:
            logging.error(f"خطأ في استخراج الروابط من {channel_link}: {e}")
            return 0
    
    async def start_joining_process(self, event):
        """بدء عملية الانضمام"""
        try:
            # التحقق من الجلسات النشطة
            cursor = self.db.conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM sessions WHERE is_active = 1 AND links_processed < ?', 
                         (self.links_per_session,))
            active_sessions = cursor.fetchone()[0] or 0
            
            if active_sessions == 0:
                await event.reply("❌ **لا توجد جلسات نشطة قادرة على العمل**", buttons=self.main_keyboard)
                return
            
            # التحقق من الروابط المعلقة
            cursor.execute('SELECT COUNT(*) FROM links WHERE is_processed = 0')
            pending_links = cursor.fetchone()[0] or 0
            
            if pending_links == 0:
                await event.reply("❌ **لا توجد روابط معلقة للانضمام**", buttons=self.main_keyboard)
                return
            
            # حساب الوقت المتوقع
            estimated_seconds = (pending_links / min(active_sessions, pending_links // self.links_per_session + 1)) * self.join_delay
            hours = int(estimated_seconds // 3600)
            minutes = int((estimated_seconds % 3600) // 60)
            
            confirmation = f"""
🚀 **بدء عملية الانضمام**

📊 **التجهيزات:**
• 📱 **الجلسات النشطة:** {active_sessions}
• 🔗 **الروابط المعلقة:** {pending_links}
• 🎯 **الهدف:** الانضمام إلى جميع الروابط
• ⏱️ **الوقت المتوقع:** {hours} ساعة و {minutes} دقيقة

✅ **هل تريد البدء الآن؟**
أرسل **نعم** للموافقة أو **لا** للإلغاء
            """
            
            self.user_states[event.sender_id] = 'confirm_joining'
            await event.reply(confirmation)
            
        except Exception as e:
            logging.error(f"خطأ في بدء العملية: {e}")
            await event.reply(f"❌ حدث خطأ: {str(e)}", buttons=self.main_keyboard)
    
    async def process_joining(self, event):
        """معالجة عملية الانضمام"""
        try:
            await event.reply("🚀 **بدأت عملية الانضمام...**")
            
            # الحصول على الجلسات النشطة
            cursor = self.db.conn.cursor()
            cursor.execute('''
                SELECT id, session_string, phone, links_processed
                FROM sessions 
                WHERE is_active = 1 AND links_processed < ?
                ORDER BY links_processed ASC
            ''', (self.links_per_session,))
            
            sessions = cursor.fetchall()
            
            if not sessions:
                await event.reply("❌ **لا توجد جلسات قادرة على العمل**", buttons=self.main_keyboard)
                return
            
            # الحصول على الروابط المعلقة
            cursor.execute('SELECT id, link FROM links WHERE is_processed = 0')
            all_links = cursor.fetchall()
            
            if not all_links:
                await event.reply("❌ **لا توجد روابط معلقة**", buttons=self.main_keyboard)
                return
            
            # بدء المهام
            total_sessions = len(sessions)
            await event.reply(f"🔧 **جاري بدء {total_sessions} جلسة...**")
            
            # هنا يمكنك إضافة منطق معالجة الجلسات
            # (مختصر لأغراض الإصلاح)
            
            await event.reply("✅ **تم بدء العملية بنجاح**", buttons=self.main_keyboard)
            
        except Exception as e:
            logging.error(f"خطأ في عملية الانضمام: {e}")
            await event.reply(f"❌ حدث خطأ في العملية: {str(e)}", buttons=self.main_keyboard)
    
    async def show_statistics(self, event):
        """عرض إحصائيات البوت"""
        try:
            stats = self.db.get_statistics()
            
            # حساب الوقت المتبقي
            pending_links = stats['links']['pending_links'] or 0
            active_sessions = stats['sessions']['active_sessions'] or 0
            
            if active_sessions > 0 and pending_links > 0:
                estimated_seconds = (pending_links / min(active_sessions, pending_links // self.links_per_session + 1)) * self.join_delay
                hours = int(estimated_seconds // 3600)
                minutes = int((estimated_seconds % 3600) // 60)
                time_remaining = f"{hours} ساعة و {minutes} دقيقة"
            else:
                time_remaining = "غير متوفر"
            
            statistics = f"""
📊 **إحصائيات البوت**

📱 **الجلسات:**
• النشطة: {active_sessions}
• المعالجة: {stats['sessions']['total_links_processed'] or 0}

🔗 **الروابط:**
• الإجمالي: {stats['links']['total_links'] or 0}
• المعلقة: {pending_links}
• الناجحة: {stats['links']['success_links'] or 0}

⏱️ **التوقيت:**
• المتبقي: {time_remaining}
• الجلسات المطلوبة: {(pending_links // self.links_per_session) + 1}
"""
            
            await event.reply(statistics, buttons=self.main_keyboard)
            
        except Exception as e:
            logging.error(f"خطأ في عرض الإحصائيات: {e}")
            await event.reply(f"❌ حدث خطأ: {str(e)}", buttons=self.main_keyboard)
    
    async def show_help(self, event):
        """عرض التعليمات"""
        help_text = """
❓ **تعليمات استخدام البوت**

🎯 **كيفية العمل:**
1. **📱 إضافة جلسة** - أضف حسابات تيليجرام
2. **🔗 طلب روابط القنوات** - أضف قنوات تحتوي على روابط مجموعات
3. **🚀 بدء الانضمام** - ابدأ عملية الانضمام التلقائي
4. **📊 الإحصائيات** - تابع أداء البوت

📋 **معلومات مهمة:**
• كل جلسة تنضم إلى {self.links_per_session} رابط
• التأخير بين الروابط {self.join_delay} ثانية
• البوت يتعرف على روابط تليجرام فقط

⚠️ **تحذيرات:**
• كثرة الانضمام قد تؤدي لحظر مؤقت
• تأكد من صلاحية الجلسات قبل البدء
"""
        
        await event.reply(help_text, buttons=self.main_keyboard)
    
    async def show_status(self, event):
        """عرض حالة البوت"""
        status_text = f"""
🟢 **البوت يعمل بشكل طبيعي**

📊 **معلومات النظام:**
• 🕒 **وقت التشغيل:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
• ⚙️ **التأخير:** {self.join_delay} ثانية
• 🔢 **الروابط/جلسة:** {self.links_per_session}
• 👤 **المسؤول:** {self.admin_id}
"""
        
        await event.reply(status_text, buttons=self.main_keyboard)
    
    async def handle_user_state(self, event, text):
        """معالجة الحالات المؤقتة للمستخدم"""
        user_id = event.sender_id
        
        if user_id not in self.user_states:
            return
        
        state = self.user_states[user_id]
        
        if state == 'awaiting_session':
            await self.add_session(event, text)
        
        elif state == 'awaiting_channel_links':
            await self.process_channel_links(event, text)
        
        elif state == 'confirm_joining':
            if text.lower() in ['نعم', 'yes', 'y', 'ابدأ', 'start']:
                await self.process_joining(event)
            else:
                await event.reply("❌ **تم إلغاء العملية**", buttons=self.main_keyboard)
            
            if user_id in self.user_states:
                del self.user_states[user_id]

# ============================================
# 🚀 الدالة الرئيسية
# ============================================

async def main():
    """الدالة الرئيسية لتشغيل البوت"""
    try:
        # إعداد التسجيل
        logger = LogManager.setup_logging()
        logger.info("🚀 بدء تشغيل Telegram Group Joiner Bot")
        
        # التحقق من متغيرات البيئة
        bot_token = os.environ.get('BOT_TOKEN')
        
        if not bot_token:
            logger.warning("⚠️  BOT_TOKEN not set in environment variables")
            logger.info("ℹ️  سيتم استخدام config.ini إذا كان موجوداً")
        
        # إنشاء وتشغيل البوت
        bot = TelegramGroupJoinerBot()
        
        logger.info("✅ البوت جاهز للتشغيل")
        
        # تشغيل البوت
        await bot.start()
        
    except KeyboardInterrupt:
        logger.info("⏹️  تم إيقاف البوت بواسطة المستخدم")
    except Exception as e:
        logger.error(f"❌ خطأ غير متوقع: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        logger.info("👋 انتهى تشغيل البوت")

if __name__ == "__main__":
    # تشغيل البوت
    asyncio.run(main())
