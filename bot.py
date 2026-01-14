#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 Telegram Group Joiner Bot - إصدار مدمج كامل
جميع الملفات في ملف واحد جاهز للنشر على Render
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
        
        config['BOT'] = {
            'token': '8494843591:AAGQkd-XLIjFSNP7CPlMsjKsyxHj0xI6LBk',
            'admin_id': '8294336757',
            'join_delay': '60',
            'links_per_session': '1000',
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
        
        # محاولة القراءة من متغيرات البيئة أولاً
        env_token = os.environ.get('BOT_TOKEN')
        env_admin = os.environ.get('ADMIN_ID')
        
        if env_token and env_token != 'YOUR_BOT_TOKEN_HERE':
            config.set('BOT', 'token', env_token)
        
        if env_admin and env_admin != '8294336757':
            config.set('BOT', 'admin_id', env_admin)
        
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
            print("⚠️  يرجى تعديله وإضافة التوكن ومعرفك")
        
        # تحديث من متغيرات البيئة
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
        
        # تحديد مستوى التسجيل
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
        self.db_file = db_file
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
        
        # جدول الإحصائيات
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE UNIQUE,
                total_links INTEGER DEFAULT 0,
                processed_links INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                active_sessions INTEGER DEFAULT 0
            )
        ''')
        
        # جدول الأخطاء
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                link_id INTEGER,
                error_type TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions (id),
                FOREIGN KEY (link_id) REFERENCES links (id)
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
            
            # حذف النسخ القديمة (احتفظ بأخر 10 نسخ)
            backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.db')])
            if len(backups) > 10:
                for old_backup in backups[:-10]:
                    os.remove(os.path.join(backup_dir, old_backup))
            
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
        
        # إحصائيات القنوات
        cursor.execute('''
            SELECT 
                COUNT(*) as total_channels,
                SUM(total_links_extracted) as total_extracted_links
            FROM source_channels
        ''')
        channel_stats = cursor.fetchone()
        stats['channels'] = dict(channel_stats)
        
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
        # تحميل الإعدادات
        self.config = ConfigManager.load_config()
        
        # الحصول على التوكن ومعرف المسؤول
        self.bot_token = self.config['BOT'].get('token')
        self.admin_id = int(self.config['BOT'].get('admin_id', '8294336757'))
        
        # التحقق من التوكن
        if not self.bot_token or self.bot_token == 'YOUR_BOT_TOKEN_HERE':
            raise ValueError("❌ يرجى إضافة توكن البوت في config.ini أو متغير BOT_TOKEN البيئي")
        
        # إعدادات الأداء
        self.join_delay = int(self.config['BOT'].get('join_delay', '60'))
        self.links_per_session = int(self.config['BOT'].get('links_per_session', '1000'))
        self.messages_per_channel = int(self.config['BOT'].get('messages_per_channel', '500'))
        
        # إعدادات API
        self.api_id = int(self.config['BOT'].get('api_id', '6'))
        self.api_hash = self.config['BOT'].get('api_hash', 'eb06d4abfb49dc3eeb1aeb98ae0f581e')
        
        # إعداد قاعدة البيانات
        self.db = DatabaseManager()
        
        # الحالات المؤقتة للمستخدمين
        self.user_states = {}
        
        # لوحة المفاتيح الرئيسية
        self.main_keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("📱 إضافة جلسة"), KeyboardButton("📋 عرض الجلسات")],
                [KeyboardButton("🔗 طلب روابط القنوات"), KeyboardButton("🚀 بدء الانضمام")],
                [KeyboardButton("📊 الإحصائيات"), KeyboardButton("⚙️ الإعدادات")],
                [KeyboardButton("🔄 تحديث الروابط"), KeyboardButton("❓ المساعدة")]
            ],
            resize_keyboard=True,
            persistent=True
        )
        
        # لوحة المفاتيح الثانوية
        self.settings_keyboard = ReplyKeyboardMarkup(
            [
                [KeyboardButton("⚡ تغيير سرعة الانضمام"), KeyboardButton("🔢 تغيير عدد الروابط")],
                [KeyboardButton("📈 عرض تقرير مفصل"), KeyboardButton("💾 نسخ احتياطي")],
                [KeyboardButton("🏠 القائمة الرئيسية")]
            ],
            resize_keyboard=True
        )
        
        # إعداد البوت
        self.bot_client = None
        self.is_running = False
        
        # إنشاء مجلدات
        self.create_folders()
        
        logging.info("✅ تم تهيئة البوت بنجاح")
    
    def create_folders(self):
        """إنشاء المجلدات الضرورية"""
        folders = ['logs', 'data', 'backups', 'sessions_backup']
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
            
            # بدء فحص الصحة للـ Render
            if self.config['RENDER'].getboolean('health_check', True):
                asyncio.create_task(self.health_check_server())
            
            # تشغيل البوت
            self.is_running = True
            await self.bot_client.run_until_disconnected()
            
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
• 📂 القنوات المصدر: {stats['channels']['total_channels'] or 0}

⚙️ **الإعدادات:**
• ⏱️ تأخير الانضمام: {self.join_delay} ثانية
• 🔢 روابط لكل جلسة: {self.links_per_session}
• 🕒 وقت البدء: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

📌 **استخدم الأزرار للتحكم بالبوت**
            """
            
            await self.bot_client.send_message(self.admin_id, message, buttons=self.main_keyboard)
            
        except Exception as e:
            logging.error(f"خطأ في إرسال رسالة البدء: {e}")
    
    async def health_check_server(self):
        """تشغيل خادم فحص الصحة للـ Render"""
        try:
            import socket
            from http.server import HTTPServer, BaseHTTPRequestHandler
            
            class HealthHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path == '/health':
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        
                        stats = self.server.bot.db.get_statistics()
                        response = {
                            'status': 'running',
                            'timestamp': datetime.now().isoformat(),
                            'sessions': stats['sessions']['active_sessions'] or 0,
                            'pending_links': stats['links']['pending_links'] or 0
                        }
                        self.wfile.write(json.dumps(response).encode())
                    else:
                        self.send_response(404)
                        self.end_headers()
                
                def log_message(self, format, *args):
                    # تعطيل تسجيل طلبات HTTP
                    pass
            
            port = int(self.config['RENDER'].get('port', '8080'))
            server = HTTPServer(('0.0.0.0', port), HealthHandler)
            server.bot = self
            
            logging.info(f"🌐 خادم فحص الصحة يعمل على المنفذ {port}")
            
            # تشغيل الخادم في خيط منفصل
            def run_server():
                server.serve_forever()
            
            import threading
            thread = threading.Thread(target=run_server, daemon=True)
            thread.start()
            
        except Exception as e:
            logging.warning(f"لا يمكن تشغيل خادم فحص الصحة: {e}")
    
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
            
            elif text == "⚙️ الإعدادات":
                await self.show_settings(event)
            
            elif text == "🔄 تحديث الروابط":
                await self.refresh_links(event)
            
            elif text == "❓ المساعدة":
                await self.show_help(event)
            
            elif text == "🏠 القائمة الرئيسية":
                await self.show_main_menu(event)
            
            elif text == "⚡ تغيير سرعة الانضمام":
                await self.change_join_delay(event)
            
            elif text == "🔢 تغيير عدد الروابط":
                await self.change_links_per_session(event)
            
            elif text == "📈 عرض تقرير مفصل":
                await self.show_detailed_report(event)
            
            elif text == "💾 نسخ احتياطي":
                await self.create_backup(event)
            
            elif text.startswith('/'):
                # معالجة الأوامر النصية
                if text == '/start':
                    await self.send_welcome(event)
                elif text == '/status':
                    await self.show_status(event)
                elif text == '/restart':
                    await self.restart_bot(event)
                elif text == '/stop':
                    await self.stop_bot(event)
            
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
• إحصائيات وتقارير مفصلة

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

⚠️ **ملاحظات مهمة:**
• تأكد من أن الحساب ليس قناة
• الجلسة صالحة لمدة 3 أشهر
• يمكنك إضافة عدد غير محدود من الجلسات

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
                    (session_string, phone, first_name, last_name, username, user_id, last_used, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session_string,
                    me.phone or "غير معروف",
                    me.first_name or "",
                    me.last_name or "",
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
• 👤 **الاسم:** `{me.first_name or ''} {me.last_name or ''}`
• 🏷️ **اليوزر:** @{me.username or 'لا يوجد'}
• 🆔 **User ID:** `{me.id}`

🎯 **المهام المخصصة:**
• 🔗 **الروابط المستهدفة:** 1000 رابط
• ⏱️ **التأخير بين الروابط:** {self.join_delay} ثانية
• 📅 **تم الإضافة:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

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
                       total_success, total_failed, is_active, created_at
                FROM sessions 
                ORDER BY is_active DESC, created_at DESC
            ''')
            
            sessions = cursor.fetchall()
            
            if not sessions:
                await event.reply("📭 **لا توجد جلسات مضافة حالياً**", buttons=self.main_keyboard)
                return
            
            # تقسيم الجلسات إلى نشطة وغير نشطة
            active_sessions = []
            inactive_sessions = []
            
            for session in sessions:
                sess_dict = dict(session)
                if sess_dict['is_active']:
                    active_sessions.append(sess_dict)
                else:
                    inactive_sessions.append(sess_dict)
            
            response = "📋 **قائمة الجلسات**\n\n"
            
            # الجلسات النشطة
            if active_sessions:
                response += "🟢 **الجلسات النشطة:**\n"
                for idx, sess in enumerate(active_sessions, 1):
                    created = datetime.strptime(sess['created_at'], '%Y-%m-%d %H:%M:%S') if isinstance(sess['created_at'], str) else sess['created_at']
                    created_str = created.strftime('%Y-%m-%d') if isinstance(created, datetime) else sess['created_at'][:10]
                    
                    response += f"""
{idx}. **{sess['first_name'] or 'غير معروف'}** (@{sess['username'] or 'لا يوجد'})
   📞: `{sess['phone'] or 'غير معروف'}`
   🆔: `{sess['id']}`
   📅: {created_str}
   🔗: {sess['links_processed']}/1000 رابط
   ✅: {sess['total_success']} | ❌: {sess['total_failed']}
"""
            
            # الجلسات المعطلة
            if inactive_sessions:
                response += "\n\n🔴 **الجلسات المعطلة:**\n"
                for idx, sess in enumerate(inactive_sessions, 1):
                    created = datetime.strptime(sess['created_at'], '%Y-%m-%d %H:%M:%S') if isinstance(sess['created_at'], str) else sess['created_at']
                    created_str = created.strftime('%Y-%m-%d') if isinstance(created, datetime) else sess['created_at'][:10]
                    
                    response += f"""
{idx}. **{sess['first_name'] or 'غير معروف'}** (@{sess['username'] or 'لا يوجد'})
   📞: `{sess['phone'] or 'غير معروف'}`
   🆔: `{sess['id']}`
   📅: {created_str}
   🔗: {sess['links_processed']}/1000 رابط
"""
            
            # حساب الجلسات المطلوبة
            cursor.execute('SELECT COUNT(*) FROM links WHERE is_processed = 0')
            pending_links = cursor.fetchone()[0] or 0
            
            sessions_needed = (pending_links // self.links_per_session) + (1 if pending_links % self.links_per_session > 0 else 0)
            active_count = len(active_sessions)
            
            response += f"""
📊 **تحليل الاحتياجات:**

🔗 **الروابط المعلقة:** {pending_links} رابط
📱 **الجلسات النشطة:** {active_count} جلسة
🎯 **الجلسات المطلوبة:** {sessions_needed} جلسة
💡 **كل جلسة ستنضم إلى:** {self.links_per_session} مجموعة
⏱️ **التأخير:** {self.join_delay} ثانية/رابط
"""
            
            if pending_links > 0 and active_count < sessions_needed:
                response += f"\n⚠️ **تحذير:** تحتاج إلى إضافة {sessions_needed - active_count} جلسة على الأقل"
            
            # إرسال الرسالة في أجزاء إذا كانت طويلة
            if len(response) > 4000:
                parts = [response[i:i+4000] for i in range(0, len(response), 4000)]
                for part in parts:
                    await event.reply(part)
            else:
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
4. البوت سيتعرف على روابط تليجرام فقط

🔍 **أنواع الروابط المدعومة:**
• https://t.me/channel_name
• https://t.me/joinchat/xxxxxx
• @username
• t.me/channel_name

⚠️ **ملاحظات:**
• البوت يتجاهل أي نص ليس رابط تليجرام
• ينظف الروابط من المسافات والأخطاء
• يستخرج فقط روابط المجموعات والقنوات

📤 **أرسل لي روابط القنوات الآن:**
(يمكنك إرسال عدة روابط، كل رابط في سطر)
        """
        
        await event.reply(instructions)
    
    async def process_channel_links(self, event, links_text):
        """معالجة روابط القنوات"""
        try:
            lines = links_text.strip().split('\n')
            added_channels = []
            extracted_links_count = 0
            
            await event.reply("🔍 **جاري معالجة الروابط...**")
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # تحويل إلى رابط صحيح
                link = self.normalize_telegram_link(line)
                if not link:
                    continue
                
                # التحقق من أن الرابط هو قناة وليس مجموعة
                try:
                    entity = await self.bot_client.get_entity(link)
                    
                    # فقط القنوات والمجموعات الكبيرة
                    if hasattr(entity, 'megagroup') and entity.megagroup:
                        # مجموعة كبيرة - نعتبرها قناة مصدر
                        pass
                    elif not hasattr(entity, 'broadcast'):
                        continue  # ليس قناة أو مجموعة كبيرة
                    
                    # حفظ القناة
                    cursor = self.db.conn.cursor()
                    cursor.execute('''
                        INSERT OR IGNORE INTO source_channels (channel_link, channel_name, added_at)
                        VALUES (?, ?, ?)
                    ''', (link, entity.title or "غير معروف", datetime.now()))
                    
                    if cursor.rowcount > 0:
                        added_channels.append({
                            'link': link,
                            'title': entity.title or "غير معروف"
                        })
                    
                    # استخراج الروابط من القناة
                    extracted_count = await self.extract_links_from_channel(link)
                    extracted_links_count += extracted_count
                    
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
• 🔗 **الروابط المستخرجة:** {extracted_links_count}
• ⏳ **إجمالي الروابط المعلقة:** {stats['links']['pending_links'] or 0}
• 📱 **الجلسات المطلوبة:** {(stats['links']['pending_links'] or 0) // self.links_per_session + 1}

📋 **القنوات المضافة:**
"""
            
            for channel in added_channels[:10]:  # عرض أول 10 قنوات
                response += f"\n• **{channel['title']}**\n  `{channel['link']}`"
            
            if len(added_channels) > 10:
                response += f"\n• ... و {len(added_channels) - 10} قنوات أخرى"
            
            response += f"""
            
💡 **معلومات مهمة:**
• البوت يستخرج فقط روابط تليجرام الصالحة
• يتجاهل الروابط المكررة تلقائياً
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
        
        # حذف المسافات والأحرف الزائدة
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
            r'https?://telegram\.me/',
            r'https?://telegram\.dog/'
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
                    # تحديد نوع الرابط
                    link_type = 'unknown'
                    if 'joinchat' in link:
                        link_type = 'private'
                    elif 't.me/' in link:
                        try:
                            entity = await self.bot_client.get_entity(link)
                            if hasattr(entity, 'megagroup') and entity.megagroup:
                                link_type = 'group'
                            elif hasattr(entity, 'broadcast'):
                                link_type = 'channel'
                        except:
                            link_type = 'unknown'
                    
                    cursor.execute('''
                        INSERT OR IGNORE INTO links (link, link_type, added_at)
                        VALUES (?, ?, ?)
                    ''', (link, link_type, datetime.now()))
                    
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
• ⚡ **السرعة:** {self.join_delay} ثانية/رابط

⚠️ **تحذيرات مهمة:**
• العملية قد تستغرق وقتاً طويلاً
• لا يمكن إيقاف العملية بعد البدء
• قد تتوقف بعض الجلسات بسبب الحظر

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
            await event.reply("🚀 **بدأت عملية الانضمام...**\n\n⏳ جاري التجهيز...")
            
            # الحصول على الجلسات النشطة
            cursor = self.db.conn.cursor()
            cursor.execute('''
                SELECT id, session_string, phone, first_name, links_processed
                FROM sessions 
                WHERE is_active = 1 AND links_processed < ?
                ORDER BY links_processed ASC
            ''', (self.links_per_session,))
            
            sessions = cursor.fetchall()
            
            if not sessions:
                await event.reply("❌ **لا توجد جلسات قادرة على العمل**", buttons=self.main_keyboard)
                return
            
            # الحصول على الروابط المعلقة
            cursor.execute('SELECT id, link FROM links WHERE is_processed = 0 ORDER BY added_at')
            all_links = cursor.fetchall()
            
            if not all_links:
                await event.reply("❌ **لا توجد روابط معلقة**", buttons=self.main_keyboard)
                return
            
            # توزيع الروابط على الجلسات
            session_tasks = {}
            for session in sessions:
                session_id = session['id']
                session_string = session['session_string']
                
                # حساب الروابط المتبقية لهذه الجلسة
                remaining_links = self.links_per_session - session['links_processed']
                if remaining_links <= 0:
                    continue
                
                # أخذ الروابط لهذه الجلسة
                links_for_session = all_links[:remaining_links]
                all_links = all_links[remaining_links:]
                
                if links_for_session:
                    session_tasks[session_id] = {
                        'session': session,
                        'session_string': session_string,
                        'links': links_for_session
                    }
                
                if not all_links:
                    break
            
            # بدء المهام
            total_tasks = len(session_tasks)
            await event.reply(f"🔧 **جاري بدء {total_tasks} جلسة...**")
            
            tasks = []
            for session_id, task_data in session_tasks.items():
                task = asyncio.create_task(
                    self.process_session_links(
                        session_id,
                        task_data['session_string'],
                        task_data['links'],
                        task_data['session']['phone']
                    )
                )
                tasks.append(task)
            
            # انتظار انتهاء جميع المهام
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # جمع النتائج
                total_success = 0
                total_failed = 0
                
                for result in results:
                    if isinstance(result, tuple):
                        success, failed = result
                        total_success += success
                        total_failed += failed
            
            # إرسال التقرير النهائي
            await self.send_joining_report(event, total_success, total_failed, total_tasks)
            
        except Exception as e:
            logging.error(f"خطأ في عملية الانضمام: {e}")
            await event.reply(f"❌ حدث خطأ في العملية: {str(e)}", buttons=self.main_keyboard)
    
    async def process_session_links(self, session_id, session_string, links, phone):
        """معالجة روابط لجلسة محددة"""
        client = None
        success_count = 0
        fail_count = 0
        
        try:
            # إنشاء عميل للجلسة
            client = TelegramClient(
                StringSession(session_string),
                self.api_id,
                self.api_hash
            )
            
            await client.connect()
            
            if not await client.is_user_authorized():
                logging.error(f"الجلسة {session_id} غير مصرح بها")
                return success_count, fail_count
            
            # إرسال رسالة بدء الجلسة
            await self.bot_client.send_message(
                self.admin_id,
                f"🔧 **بدء الجلسة {session_id}**\n📞: `{phone}`\n🔗: {len(links)} رابط"
            )
            
            # معالجة كل رابط
            total_links = len(links)
            
            for idx, (link_id, link) in enumerate(links, 1):
                try:
                    # محاولة الانضمام
                    success = await self.join_group(client, link)
                    
                    # تحديث قاعدة البيانات
                    cursor = self.db.conn.cursor()
                    
                    if success:
                        cursor.execute('''
                            UPDATE links 
                            SET is_processed = 1, processed_by = ?, processed_at = ?, success = 1
                            WHERE id = ?
                        ''', (f"session_{session_id}", datetime.now(), link_id))
                        success_count += 1
                        
                        cursor.execute('''
                            UPDATE sessions 
                            SET links_processed = links_processed + 1, 
                                total_success = total_success + 1,
                                last_used = ?
                            WHERE id = ?
                        ''', (datetime.now(), session_id))
                    else:
                        cursor.execute('''
                            UPDATE links 
                            SET is_processed = 1, processed_by = ?, processed_at = ?, success = 0
                            WHERE id = ?
                        ''', (f"session_{session_id}", datetime.now(), link_id))
                        fail_count += 1
                        
                        cursor.execute('''
                            UPDATE sessions 
                            SET links_processed = links_processed + 1, 
                                total_failed = total_failed + 1,
                                last_used = ?
                            WHERE id = ?
                        ''', (datetime.now(), session_id))
                    
                    self.db.conn.commit()
                    
                    # تسجيل النتيجة
                    logging.info(f"الجلسة {session_id} ({phone}): {'✅' if success else '❌'} {link}")
                    
                    # إرسال تحديث كل 20 رابط
                    if idx % 20 == 0 or idx == total_links:
                        progress = int((idx / total_links) * 100)
                        await self.bot_client.send_message(
                            self.admin_id,
                            f"📊 **الجلسة {session_id}**\n"
                            f"📞: `{phone}`\n"
                            f"📈: {progress}% ({idx}/{total_links})\n"
                            f"✅: {success_count} | ❌: {fail_count}"
                        )
                    
                    # الانتظار قبل الرابط التالي
                    await asyncio.sleep(self.join_delay)
                    
                except Exception as e:
                    logging.error(f"خطأ في الرابط {link}: {e}")
                    fail_count += 1
                    
                    # حفظ الخطأ
                    cursor = self.db.conn.cursor()
                    cursor.execute('''
                        INSERT INTO errors (session_id, link_id, error_type, error_message)
                        VALUES (?, ?, ?, ?)
                    ''', (session_id, link_id, type(e).__name__, str(e)[:200]))
                    
                    cursor.execute('''
                        UPDATE sessions 
                        SET links_processed = links_processed + 1, 
                            total_failed = total_failed + 1,
                            last_used = ?
                        WHERE id = ?
                    ''', (datetime.now(), session_id))
                    
                    self.db.conn.commit()
                    
                    # انتظار قصير بعد الخطأ
                    await asyncio.sleep(5)
        
        except Exception as e:
            logging.error(f"خطأ في الجلسة {session_id}: {e}")
        finally:
            if client:
                await client.disconnect()
            
            # إرسال تقرير نهاية الجلسة
            await self.bot_client.send_message(
                self.admin_id,
                f"🏁 **انتهت الجلسة {session_id}**\n"
                f"📞: `{phone}`\n"
                f"✅: {success_count} | ❌: {fail_count}\n"
                f"📊: {success_count + fail_count}/{self.links_per_session}"
            )
            
            return success_count, fail_count
    
    async def join_group(self, client, link):
        """الانضمام إلى مجموعة"""
        try:
            clean_link = link.strip()
            
            if 'joinchat/' in clean_link:
                # رابط الدعوة
                invite_hash = clean_link.split('joinchat/')[-1]
                await client(ImportChatInviteRequest(invite_hash))
                return True
                
            elif clean_link.startswith('@'):
                # @username
                entity = await client.get_entity(clean_link)
                await client(JoinChannelRequest(entity))
                return True
                
            else:
                # رابط عادي
                entity = await client.get_entity(clean_link)
                await client(JoinChannelRequest(entity))
                return True
                
        except errors.FloodWaitError as e:
            wait_time = e.seconds + 10
            logging.warning(f"Flood wait: {wait_time} ثانية")
            await asyncio.sleep(wait_time)
            return False
            
        except errors.UserAlreadyParticipantError:
            logging.info(f"المستخدم بالفعل في المجموعة: {link}")
            return True
            
        except errors.InviteHashExpiredError:
            logging.warning(f"انتهت صلاحية الرابط: {link}")
            return False
            
        except errors.InviteHashInvalidError:
            logging.warning(f"رابط غير صالح: {link}")
            return False
            
        except errors.ChannelPrivateError:
            logging.warning(f"القناة خاصة: {link}")
            return False
            
        except errors.ChannelInvalidError:
            logging.warning(f"رابط غير صالح: {link}")
            return False
            
        except Exception as e:
            logging.error(f"خطأ في الانضمام إلى {link}: {e}")
            return False
    
    async def send_joining_report(self, event, total_success, total_failed, total_sessions):
        """إرسال تقرير عملية الانضمام"""
        try:
            stats = self.db.get_statistics()
            
            total_processed = total_success + total_failed
            success_rate = (total_success / total_processed * 100) if total_processed > 0 else 0
            
            report = f"""
🏁 **تقرير عملية الانضمام**

📊 **نتائج الجلسة:**
• 🎯 **الجلسات النشطة:** {total_sessions}
• ✅ **النجاح:** {total_success}
• ❌ **الفشل:** {total_failed}
• 📈 **معدل النجاح:** {success_rate:.1f}%

📊 **إحصائيات إجمالية:**
• 🔗 **إجمالي الروابط:** {stats['links']['total_links'] or 0}
• ⏳ **المعلقة:** {stats['links']['pending_links'] or 0}
• ✅ **الناجحة:** {stats['links']['success_links'] or 0}
• 📱 **الجلسات:** {stats['sessions']['active_sessions'] or 0}

⏱️ **الوقت:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

💡 **التوصيات:**
"""
            
            if stats['links']['pending_links'] > 0:
                needed_sessions = (stats['links']['pending_links'] // self.links_per_session) + 1
                report += f"• تحتاج إلى إضافة {needed_sessions - stats['sessions']['active_sessions']} جلسة\n"
            
            if success_rate < 50:
                report += "• معدل النجاح منخفض، قد تحتاج إلى تحسين الجلسات\n"
            
            report += "• يمكنك بدء عملية جديدة أو إضافة جلسات/روابط"
            
            await event.reply(report, buttons=self.main_keyboard)
            
        except Exception as e:
            logging.error(f"خطأ في إرسال التقرير: {e}")
    
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
            
            # حساب معدل النجاح
            total_processed = (stats['links']['success_links'] or 0) + (stats['links']['failed_links'] or 0)
            success_rate = (stats['links']['success_links'] / total_processed * 100) if total_processed > 0 else 0
            
            statistics = f"""
📊 **إحصائيات البوت المتقدم**

📱 **الجلسات:**
• الإجمالي: {stats['sessions']['total_sessions'] or 0}
• النشطة: {stats['sessions']['active_sessions'] or 0}
• المعالجة: {stats['sessions']['total_links_processed'] or 0}
• المتوسط: {(stats['sessions']['total_links_processed'] / stats['sessions']['total_sessions']) if stats['sessions']['total_sessions'] > 0 else 0:.1f}/جلسة

🔗 **الروابط:**
• الإجمالي: {stats['links']['total_links'] or 0}
• المعالجة: {stats['links']['processed_links'] or 0}
• المعلقة: {stats['links']['pending_links'] or 0}
• الناجحة: {stats['links']['success_links'] or 0}
• الفاشلة: {stats['links']['failed_links'] or 0}

🎯 **الأداء:**
• النجاح: {success_rate:.1f}%
• الوقت المتبقي: {time_remaining}
• الجلسات المطلوبة: {(pending_links // self.links_per_session) + 1}

📂 **المصادر:**
• القنوات: {stats['channels']['total_channels'] or 0}
• الروابط المستخرجة: {stats['channels']['total_extracted_links'] or 0}

⚙️ **الإعدادات الحالية:**
• التأخير: {self.join_delay} ثانية
• الروابط/جلسة: {self.links_per_session}
• الرسائل/قناة: {self.messages_per_channel}
"""
            
            await event.reply(statistics, buttons=self.main_keyboard)
            
        except Exception as e:
            logging.error(f"خطأ في عرض الإحصائيات: {e}")
            await event.reply(f"❌ حدث خطأ: {str(e)}", buttons=self.main_keyboard)
    
    async def show_settings(self, event):
        """عرض إعدادات البوت"""
        settings_text = f"""
⚙️ **إعدادات البوت**

📋 **الإعدادات الحالية:**
• ⏱️ **تأخير الانضمام:** {self.join_delay} ثانية
• 🔢 **روابط لكل جلسة:** {self.links_per_session}
• 📨 **رسائل لكل قناة:** {self.messages_per_channel}
• 🆔 **معرف المسؤول:** {self.admin_id}
• 🔑 **API ID:** {self.api_id}

🔧 **يمكنك تغيير الإعدادات باستخدام الأزرار أدناه:**
        """
        
        await event.reply(settings_text, buttons=self.settings_keyboard)
    
    async def change_join_delay(self, event):
        """تغيير سرعة الانضمام"""
        self.user_states[event.sender_id] = 'change_join_delay'
        await event.reply("⚡ **أدخل التأخير الجديد بين الروابط (بالثواني):**\n\n📌 **الاقتراح:** 60-120 ثانية لتجنب الحظر")
    
    async def change_links_per_session(self, event):
        """تغيير عدد الروابط لكل جلسة"""
        self.user_states[event.sender_id] = 'change_links_per_session'
        await event.reply("🔢 **أدخل عدد الروابط الجديد لكل جلسة:**\n\n📌 **الاقتراح:** 1000 رابط كحد أقصى")
    
    async def refresh_links(self, event):
        """تحديث الروابط من القنوات المصدر"""
        try:
            cursor = self.db.conn.cursor()
            cursor.execute('SELECT channel_link FROM source_channels')
            channels = cursor.fetchall()
            
            if not channels:
                await event.reply("❌ **لا توجد قنوات مصدر مضافة**", buttons=self.main_keyboard)
                return
            
            total_extracted = 0
            
            await event.reply(f"🔄 **جاري تحديث الروابط من {len(channels)} قناة...**")
            
            for channel in channels:
                extracted = await self.extract_links_from_channel(channel['channel_link'])
                total_extracted += extracted
                
                # تحديث وقت السحب الأخير
                cursor.execute('''
                    UPDATE source_channels 
                    SET last_scraped = ?
                    WHERE channel_link = ?
                ''', (datetime.now(), channel['channel_link']))
            
            self.db.conn.commit()
            
            stats = self.db.get_statistics()
            
            response = f"""
✅ **تم تحديث الروابط بنجاح!**

📊 **النتائج:**
• 🔄 **القنوات المحدثة:** {len(channels)}
• 🆕 **الروابط الجديدة:** {total_extracted}
• ⏳ **إجمالي المعلقة:** {stats['links']['pending_links'] or 0}
• 📱 **الجلسات المطلوبة:** {(stats['links']['pending_links'] or 0) // self.links_per_session + 1}
"""
            
            await event.reply(response, buttons=self.main_keyboard)
            
        except Exception as e:
            logging.error(f"خطأ في تحديث الروابط: {e}")
            await event.reply(f"❌ حدث خطأ: {str(e)}", buttons=self.main_keyboard)
    
    async def show_detailed_report(self, event):
        """عرض تقرير مفصل"""
        try:
            cursor = self.db.conn.cursor()
            
            # أفضل الجلسات أداءً
            cursor.execute('''
                SELECT phone, first_name, total_success, total_failed, links_processed,
                       (total_success * 100.0 / links_processed) as success_rate
                FROM sessions 
                WHERE links_processed > 0
                ORDER BY success_rate DESC
                LIMIT 5
            ''')
            top_sessions = cursor.fetchall()
            
            # أحدث الروابط المضافة
            cursor.execute('''
                SELECT link, added_at, link_type
                FROM links
                ORDER BY added_at DESC
                LIMIT 10
            ''')
            recent_links = cursor.fetchall()
            
            # الأخطاء الشائعة
            cursor.execute('''
                SELECT error_type, COUNT(*) as count
                FROM errors
                GROUP BY error_type
                ORDER BY count DESC
                LIMIT 5
            ''')
            common_errors = cursor.fetchall()
            
            report = f"""
📈 **تقرير مفصل**

🏆 **أفضل الجلسات أداءً:**
"""
            
            for idx, session in enumerate(top_sessions, 1):
                report += f"""
{idx}. **{session['first_name'] or 'غير معروف'}** ({session['phone']})
   ✅ {session['total_success']} | ❌ {session['total_failed']}
   📊 {session['success_rate']:.1f}% نجاح
"""
            
            report += f"""
📋 **أحدث الروابط المضافة:**
"""
            
            for link in recent_links:
                added = datetime.strptime(link['added_at'], '%Y-%m-%d %H:%M:%S') if isinstance(link['added_at'], str) else link['added_at']
                added_str = added.strftime('%m-%d %H:%M') if isinstance(added, datetime) else link['added_at'][5:16]
                
                report += f"\n• [{link['link_type']}] `{link['link'][:30]}...` ({added_str})"
            
            if common_errors:
                report += f"""
🔴 **الأخطاء الشائعة:**
"""
                for error in common_errors:
                    report += f"\n• {error['error_type']}: {error['count']} مرة"
            
            report += f"""
🕒 **آخر تحديث:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            
            await event.reply(report, buttons=self.main_keyboard)
            
        except Exception as e:
            logging.error(f"خطأ في عرض التقرير: {e}")
            await event.reply(f"❌ حدث خطأ: {str(e)}", buttons=self.main_keyboard)
    
    async def create_backup(self, event):
        """إنشاء نسخة احتياطية"""
        try:
            await event.reply("💾 **جاري إنشاء نسخة احتياطية...**")
            
            backup_file = self.db.backup_database()
            
            if backup_file:
                response = f"""
✅ **تم إنشاء نسخة احتياطية بنجاح!**

📁 **الملف:** `{backup_file}`
📊 **الحجم:** {os.path.getsize(backup_file) / 1024:.1f} كيلوبايت
🕒 **الوقت:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

💡 **النسخ الاحتياطية تحفظ تلقائياً في مجلد backups/**
"""
                await event.reply(response, buttons=self.main_keyboard)
            else:
                await event.reply("❌ **فشل في إنشاء النسخة الاحتياطية**", buttons=self.main_keyboard)
                
        except Exception as e:
            logging.error(f"خطأ في إنشاء النسخة الاحتياطية: {e}")
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
• كل جلسة تنضم إلى 1000 رابط كحد أقصى
• التأخير بين الروابط 60 ثانية لتجنب الحظر
• البوت يتعرف على روابط تليجرام فقط
• الروابط المكررة تتجاهل تلقائياً

⚡ **نصائح للحصول على أفضل نتائج:**
1. أضف جلسات حديثة وغير محظورة
2. أضف قنوات تحتوي على روابط مجموعات نشطة
3. راقب سجلات البوت في ملف bot.log
4. لا تبدأ العملية إلا بعد إضافة جلسات كافية

⚠️ **تحذيرات:**
• كثرة الانضمام قد تؤدي لحظر مؤقت
• تأكد من صلاحية الجلسات قبل البدء
• البوت للاستخدام القانوني فقط

🆘 **الدعم:**
• تحقق من السجلات في logs/bot.log
• أعد تشغيل البوت إذا توقف
• تأكد من صحة التوكن والإعدادات
"""
        
        await event.reply(help_text, buttons=self.main_keyboard)
    
    async def show_main_menu(self, event):
        """العودة إلى القائمة الرئيسية"""
        await event.reply("🏠 **العودة إلى القائمة الرئيسية**", buttons=self.main_keyboard)
    
    async def show_status(self, event):
        """عرض حالة البوت"""
        uptime = datetime.now()  # يمكنك إضافة حساب وقت التشغيل الفعلي
        
        status_text = f"""
🟢 **البوت يعمل بشكل طبيعي**

📊 **معلومات النظام:**
• 🕒 **وقت التشغيل:** {uptime.strftime('%Y-%m-%d %H:%M:%S')}
• 🐍 **إصدار Python:** {sys.version.split()[0]}
• 💾 **ذاكرة مستخدمة:** {self.get_memory_usage():.1f} ميجابايت
• 📁 **حجم قاعدة البيانات:** {self.get_db_size():.1f} ميجابايت

🔍 **للتحقق من الصحة:** http://localhost:{self.config['RENDER'].get('port', '8080')}/health
"""
        
        await event.reply(status_text, buttons=self.main_keyboard)
    
    async def restart_bot(self, event):
        """إعادة تشغيل البوت"""
        await event.reply("🔄 **جاري إعادة التشغيل...**")
        os.execv(sys.executable, [sys.executable] + sys.argv)
    
    async def stop_bot(self, event):
        """إيقاف البوت"""
        await event.reply("🛑 **جاري إيقاف البوت...**")
        self.is_running = False
        await self.bot_client.disconnect()
        sys.exit(0)
    
    def get_memory_usage(self):
        """الحصول على استهلاك الذاكرة"""
        import psutil
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / 1024 / 1024
    
    def get_db_size(self):
        """الحصول على حجم قاعدة البيانات"""
        if os.path.exists(self.db.db_file):
            return os.path.getsize(self.db.db_file) / 1024 / 1024
        return 0
    
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
        
        elif state == 'change_join_delay':
            try:
                new_delay = int(text)
                if new_delay < 10:
                    await event.reply("❌ **التأخير يجب أن يكون 10 ثواني على الأقل**", buttons=self.settings_keyboard)
                else:
                    self.join_delay = new_delay
                    self.config.set('BOT', 'join_delay', str(new_delay))
                    ConfigManager.save_config(self.config)
                    
                    await event.reply(f"✅ **تم تغيير التأخير إلى {new_delay} ثانية**", buttons=self.settings_keyboard)
            except ValueError:
                await event.reply("❌ **يرجى إدخال رقم صحيح**", buttons=self.settings_keyboard)
            
            if user_id in self.user_states:
                del self.user_states[user_id]
        
        elif state == 'change_links_per_session':
            try:
                new_limit = int(text)
                if new_limit < 100 or new_limit > 5000:
                    await event.reply("❌ **الحد يجب أن يكون بين 100 و 5000**", buttons=self.settings_keyboard)
                else:
                    self.links_per_session = new_limit
                    self.config.set('BOT', 'links_per_session', str(new_limit))
                    ConfigManager.save_config(self.config)
                    
                    await event.reply(f"✅ **تم تغيير عدد الروابط إلى {new_limit} لكل جلسة**", buttons=self.settings_keyboard)
            except ValueError:
                await event.reply("❌ **يرجى إدخال رقم صحيح**", buttons=self.settings_keyboard)
            
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
        
        # إنشاء مجلدات ضرورية
        for folder in ['logs', 'data', 'backups', 'sessions_backup']:
            os.makedirs(folder, exist_ok=True)
        
        # التحقق من متغيرات البيئة
        bot_token = os.environ.get('BOT_TOKEN')
        admin_id = os.environ.get('ADMIN_ID')
        
        if not bot_token:
            logger.warning("⚠️  لم يتم تعيين BOT_TOKEN في متغيرات البيئة")
            logger.info("ℹ️  سيتم استخدام القيم من config.ini")
        
        # إنشاء وتشغيل البوت
        bot = TelegramGroupJoinerBot()
        
        # التحقق من التوكن
        if not bot.bot_token or bot.bot_token == 'YOUR_BOT_TOKEN_HERE':
            logger.error("❌ يرجى إضافة توكن البوت في config.ini أو متغير BOT_TOKEN البيئي")
            print("=" * 50)
            print("❌ خطأ: يرجى إضافة توكن البوت")
            print("1. عدل ملف config.ini وأضف التوكن")
            print("2. أو عين متغير BOT_TOKEN البيئي")
            print("3. احصل على التوكن من @BotFather")
            print("=" * 50)
            return
        
        logger.info(f"✅ البوت جاهز للتشغيل")
        logger.info(f"👤 معرف المسؤول: {bot.admin_id}")
        logger.info(f"⚙️  التأخير: {bot.join_delay} ثانية")
        logger.info(f"🔢 الروابط/جلسة: {bot.links_per_session}")
        
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
