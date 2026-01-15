#!/usr/bin/env python3
"""
IT House English Test - Telegram Bot
To'liq funksionallik: Test natijalarini qabul qilish, foydalanuvchilarga javob berish, ma'lumotlar bazasi bilan ishlash
"""

import os
import logging
import json
import asyncio
import sqlite3
import hashlib
import secrets
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from enum import Enum
import aiohttp
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters
)

# Logging sozlamalari
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Bot tokeni (o'zgartiring)
BOT_TOKEN = "8489045280:AAHgPKMNfeZUNXa4w4Wqo7n1l4A-2kVaStQ"

# Adminlar ro'yxati (telegram_id lar)
ADMINS = [8352638044]  # O'z telegram ID laringizni qo'ying

# Admin parollari (hashlangan)
ADMIN_PASSWORDS = {
    "admin": hashlib.sha256("admin123".encode()).hexdigest(),  # default parol
}

# Ma'lumotlar bazasi
DB_PATH = "english_test.db"

# Conversation holatlari
class AdminStates(Enum):
    WAITING_FOR_PASSWORD = 1
    MAIN_MENU = 2
    ADDING_QUESTION = 3
    EDITING_QUESTION = 4
    VIEWING_STATS = 5
    SENDING_BROADCAST = 6
    MANAGING_USERS = 7

class TestStates(Enum):
    SELECTING_LEVEL = 1
    TAKING_TEST = 2
    VIEWING_RESULT = 3

class EnglishTestBot:
    def __init__(self):
        self.application = None
        self.db = self.init_database()
        self.test_sessions = {}
        self.admin_sessions = {}
        self.user_test_sessions = {}
        
        # Darajalar
        self.levels = {
            'beginner': 'Boshlangich',
            'elementary': 'Elementary',
            'pre_intermediate': 'Pre-Intermediate',
            'intermediate': 'Intermediate',
            'upper_intermediate': 'Upper-Intermediate',
            'advanced': 'Advanced'
        }
        
        # Daraja tavsiflari
        self.level_descriptions = {
            'beginner': 'Asosiy sozlar va oddiy gaplar',
            'elementary': 'Kundalik iboralar va asosiy grammatika',
            'pre_intermediate': 'Oddiy suhbatlar olib borish',
            'intermediate': 'Tanish mavzular boyicha suhbat',
            'upper_intermediate': 'Erkin va oz-o\'zidan muloqot',
            'advanced': 'Tilni moslashuvchan va samarali ishlatish'
        }
        
        # Har bir daraja uchun test savollari soni
        self.questions_per_level = {
            'beginner': 5,
            'elementary': 7,
            'pre_intermediate': 8,
            'intermediate': 10,
            'upper_intermediate': 12,
            'advanced': 15
        }
        
    def init_database(self):
        """SQLite ma'lumotlar bazasini ishga tushirish"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Foydalanuvchilar jadvali
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                phone_number TEXT,
                joined_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                total_tests INTEGER DEFAULT 0,
                best_score INTEGER DEFAULT 0,
                current_level TEXT DEFAULT 'beginner',
                is_active BOOLEAN DEFAULT 1,
                last_active DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Test natijalari jadvali
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                level TEXT,
                score INTEGER,
                total_questions INTEGER,
                correct_answers INTEGER,
                wrong_answers INTEGER,
                percentage REAL,
                test_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_offline BOOLEAN DEFAULT 0,
                details TEXT,
                is_reviewed BOOLEAN DEFAULT 0,
                review_notes TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Savollar jadvali
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT,
                question_type TEXT DEFAULT 'multiple_choice',
                question_text TEXT,
                option_a TEXT,
                option_b TEXT,
                option_c TEXT,
                option_d TEXT,
                correct_answer TEXT,
                explanation TEXT,
                difficulty INTEGER DEFAULT 1,
                is_active BOOLEAN DEFAULT 1,
                created_by TEXT DEFAULT 'system',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Admin sessiyalari jadvali
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_sessions (
                session_id TEXT PRIMARY KEY,
                admin_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME,
                is_active BOOLEAN DEFAULT 1
            )
        ''')
        
        # Xabarlar (broadcast) jadvali
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                message_text TEXT,
                sent_to INTEGER DEFAULT 0,
                total_users INTEGER DEFAULT 0,
                sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
        ''')
        
        # Jadvalarni to'ldirish
        self.initialize_sample_data(cursor, conn)
        
        conn.commit()
        return conn
    
    def initialize_sample_data(self, cursor, conn):
        """Namuna ma'lumotlarni yaratish"""
        # Admin ma'lumotlari
        cursor.execute("SELECT COUNT(*) FROM users WHERE telegram_id IN (?, ?)", ADMINS[:2])
        admin_count = cursor.fetchone()[0]
        
        if admin_count == 0:
            for admin_id in ADMINS:
                cursor.execute('''
                    INSERT OR IGNORE INTO users (telegram_id, username, first_name, is_active)
                    VALUES (?, ?, ?, 1)
                ''', (admin_id, f"admin_{admin_id}", "Admin"))
        
        # Savollar mavjudligini tekshirish
        cursor.execute("SELECT COUNT(*) FROM questions")
        count = cursor.fetchone()[0]
        
        if count == 0:
            # Namuna savollar (beginner uchun)
            sample_questions = [
                # Beginner level questions
                {
                    'level': 'beginner',
                    'question_text': 'What ___ your name?',
                    'option_a': 'is',
                    'option_b': 'am',
                    'option_c': 'are',
                    'option_d': 'be',
                    'correct_answer': 'A',
                    'explanation': 'What is your name? - Ismingiz nima?',
                    'difficulty': 1
                },
                {
                    'level': 'beginner',
                    'question_text': 'I ___ from Uzbekistan.',
                    'option_a': 'am',
                    'option_b': 'is',
                    'option_c': 'are',
                    'option_d': 'be',
                    'correct_answer': 'A',
                    'explanation': 'I am from Uzbekistan. - Men O\'zbekistondanman.',
                    'difficulty': 1
                },
                {
                    'level': 'beginner',
                    'question_text': 'She ___ a teacher.',
                    'option_a': 'am',
                    'option_b': 'is',
                    'option_c': 'are',
                    'option_d': 'be',
                    'correct_answer': 'B',
                    'explanation': 'She is a teacher. - U o\'qituvchi.',
                    'difficulty': 1
                },
                {
                    'level': 'beginner',
                    'question_text': 'They ___ students.',
                    'option_a': 'am',
                    'option_b': 'is',
                    'option_c': 'are',
                    'option_d': 'be',
                    'correct_answer': 'C',
                    'explanation': 'They are students. - Ular talabalar.',
                    'difficulty': 1
                },
                {
                    'level': 'beginner',
                    'question_text': 'My name ___ John.',
                    'option_a': 'am',
                    'option_b': 'is',
                    'option_c': 'are',
                    'option_d': 'be',
                    'correct_answer': 'B',
                    'explanation': 'My name is John. - Mening ismim John.',
                    'difficulty': 1
                },
                # Elementary level questions
                {
                    'level': 'elementary',
                    'question_text': 'She usually ___ to work by bus.',
                    'option_a': 'go',
                    'option_b': 'goes',
                    'option_c': 'going',
                    'option_d': 'went',
                    'correct_answer': 'B',
                    'explanation': 'Present Simple: She goes to work by bus.',
                    'difficulty': 2
                },
                {
                    'level': 'elementary',
                    'question_text': 'I ___ TV every evening.',
                    'option_a': 'watch',
                    'option_b': 'watches',
                    'option_c': 'watching',
                    'option_d': 'watched',
                    'correct_answer': 'A',
                    'explanation': 'Present Simple: I watch TV every evening.',
                    'difficulty': 2
                }
            ]
            
            for q in sample_questions:
                cursor.execute('''
                    INSERT INTO questions 
                    (level, question_text, option_a, option_b, option_c, option_d, correct_answer, explanation, difficulty)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    q['level'], q['question_text'], 
                    q['option_a'], q['option_b'], q['option_c'], q['option_d'],
                    q['correct_answer'], q['explanation'], q['difficulty']
                ))
        
        conn.commit()
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/start komandasi"""
        user = update.effective_user
        user_id = user.id
        
        # Admin tekshirish
        if user_id in ADMINS:
            await self.show_admin_login(update, context)
            return
        
        # Oddiy foydalanuvchi
        self.add_user(user_id, user.username, user.first_name, user.last_name)
        
        welcome_text = f"""Assalomu alaykum, {user.first_name}!

*IT House English Test Bot* ga xush kelibsiz!

Bu bot orqali siz ingliz tili darajangizni sinab koring va natijalaringizni oling."""
        
        keyboard = [
            [
                InlineKeyboardButton("Test yechish", callback_data="start_test"),
                InlineKeyboardButton("Natijalarim", callback_data="my_results")
            ],
            [
                InlineKeyboardButton("Profil", callback_data="profile"),
                InlineKeyboardButton("Yordam", callback_data="help")
            ]
        ]
        
        # Agar admin bo'lsa, admin tugmasi
        if user_id in ADMINS:
            keyboard.append([
                InlineKeyboardButton("Admin panel", callback_data="admin_login")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            welcome_text, 
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    # ==================== USER TEST FUNCTIONS ====================
    
    async def start_test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Testni boshlash"""
        query = update.callback_query
        await query.answer()
        
        await self.show_level_selection(update, context)
    
    async def show_level_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Darajalarni tanlash"""
        query = update.callback_query if hasattr(update, 'callback_query') else None
        
        level_text = "*Test darajasini tanlang:*\n\n"
        
        keyboard = []
        for level_key, level_name in self.levels.items():
            description = self.level_descriptions.get(level_key, '')
            # Har bir daraja uchun savollar sonini ko'rsatish
            question_count = self.get_question_count(level_key)
            button_text = f"{level_name} ({question_count} savol)"
            keyboard.append([
                InlineKeyboardButton(button_text, callback_data=f"select_level_{level_key}")
            ])
            level_text += f"*{level_name}:* {description}\n\n"
        
        keyboard.append([
            InlineKeyboardButton("Orqaga", callback_data="main_menu")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if query:
            await query.edit_message_text(
                level_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                level_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
    
    def get_question_count(self, level: str) -> int:
        """Berilgan daraja uchun mavjud savollar soni"""
        cursor = self.db.cursor()
        cursor.execute("SELECT COUNT(*) FROM questions WHERE level = ? AND is_active = 1", (level,))
        return cursor.fetchone()[0]
    
    async def select_test_level(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Test darajasini tanlash"""
        query = update.callback_query
        await query.answer()
        
        level = query.data.replace("select_level_", "")
        user_id = update.effective_user.id
        
        # Daraja uchun mavjud savollar sonini tekshirish
        question_count = self.get_question_count(level)
        if question_count < 3:  # Kamida 3 ta savol bo'lishi kerak
            await query.edit_message_text(
                f"❌ {self.levels.get(level)} darajasi uchun yetarli savol mavjud emas.\n"
                f"Hozirda faqat {question_count} ta savol mavjud.\n\n"
                f"Admin bilan bog'laning yoki boshqa darajani tanlang.",
                parse_mode='Markdown'
            )
            return
        
        # Test sessiyasini boshlash
        self.user_test_sessions[user_id] = {
            'level': level,
            'questions': [],
            'current_question': 0,
            'answers': [],
            'score': 0,
            'start_time': datetime.now(),
            'question_count': min(question_count, self.questions_per_level.get(level, 10))
        }
        
        # Savollarni yuklash
        questions = self.get_test_questions(level, self.user_test_sessions[user_id]['question_count'])
        self.user_test_sessions[user_id]['questions'] = questions
        
        if not questions:
            await query.edit_message_text(
                f"❌ {self.levels.get(level)} darajasi uchun savollar topilmadi.",
                parse_mode='Markdown'
            )
            del self.user_test_sessions[user_id]
            return
        
        await self.show_test_question(update, context)
    
    def get_test_questions(self, level: str, count: int) -> List[Dict]:
        """Berilgan daraja uchun test savollarini olish"""
        cursor = self.db.cursor()
        cursor.execute('''
            SELECT id, question_text, option_a, option_b, option_c, option_d, correct_answer, explanation
            FROM questions 
            WHERE level = ? AND is_active = 1
            ORDER BY RANDOM()
            LIMIT ?
        ''', (level, count))
        
        questions = []
        columns = [desc[0] for desc in cursor.description]
        
        for row in cursor.fetchall():
            question = dict(zip(columns, row))
            questions.append(question)
        
        return questions
    
    async def show_test_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Test savolini ko'rsatish"""
        query = update.callback_query if hasattr(update, 'callback_query') else None
        user_id = update.effective_user.id
        
        if user_id not in self.user_test_sessions:
            if query:
                await query.edit_message_text("Test sessiyasi tugadi. Qayta boshlash uchun /start buyrugini yuboring.")
            else:
                await update.message.reply_text("Test sessiyasi tugadi. Qayta boshlash uchun /start buyrugini yuboring.")
            return
        
        session = self.user_test_sessions[user_id]
        current_q = session['current_question']
        
        if current_q >= len(session['questions']):
            await self.finish_user_test(update, context)
            return
        
        question = session['questions'][current_q]
        
        # Variantlar tugmalari
        keyboard = []
        if question['option_a']:
            keyboard.append([InlineKeyboardButton(f"A: {question['option_a']}", callback_data="answer_A")])
        if question['option_b']:
            keyboard.append([InlineKeyboardButton(f"B: {question['option_b']}", callback_data="answer_B")])
        if question['option_c']:
            keyboard.append([InlineKeyboardButton(f"C: {question['option_c']}", callback_data="answer_C")])
        if question['option_d']:
            keyboard.append([InlineKeyboardButton(f"D: {question['option_d']}", callback_data="answer_D")])
        
        keyboard.append([
            InlineKeyboardButton("Otkazib yuborish", callback_data="skip_question"),
            InlineKeyboardButton("Testni tugatish", callback_data="cancel_test")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        question_text = f"""*Savol {current_q + 1}/{len(session['questions'])}*

{question['question_text']}

Daraja: {self.levels.get(session['level'], session['level'])}"""
        
        if query:
            await query.edit_message_text(
                question_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                question_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
    
    async def handle_test_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Test javobini qayta ishlash"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        answer = query.data.replace("answer_", "")
        
        if user_id not in self.user_test_sessions:
            return
        
        session = self.user_test_sessions[user_id]
        current_q = session['current_question']
        question = session['questions'][current_q]
        
        # Javobni tekshirish
        is_correct = answer == question['correct_answer']
        
        # Javobni saqlash
        session['answers'].append({
            'question_id': question['id'],
            'question_text': question['question_text'],
            'answer': answer,
            'correct_answer': question['correct_answer'],
            'is_correct': is_correct,
            'explanation': question['explanation']
        })
        
        if is_correct:
            session['score'] += 1
        
        # Keyingi savolga o'tish
        session['current_question'] += 1
        
        # Kechiktirish va keyingi savol
        await asyncio.sleep(1)
        await self.show_test_question(update, context)
    
    async def skip_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Savolni o'tkazib yuborish"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        
        if user_id in self.user_test_sessions:
            session = self.user_test_sessions[user_id]
            current_q = session['current_question']
            question = session['questions'][current_q]
            
            session['current_question'] += 1
            session['answers'].append({
                'question_id': question['id'],
                'question_text': question['question_text'],
                'answer': 'SKIP',
                'is_correct': False,
                'explanation': question['explanation']
            })
            
            await self.show_test_question(update, context)
    
    async def cancel_test(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Testni bekor qilish"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        
        if user_id in self.user_test_sessions:
            del self.user_test_sessions[user_id]
        
        await query.edit_message_text(
            "❌ Test bekor qilindi.\n\n"
            "Yana test yechish uchun /start buyrugini yuboring.",
            parse_mode='Markdown'
        )
    
    async def finish_user_test(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Testni tugatish va natijalarni ko'rsatish"""
        query = update.callback_query if hasattr(update, 'callback_query') else None
        user_id = update.effective_user.id
        
        if user_id not in self.user_test_sessions:
            if query:
                await query.edit_message_text("Test sessiyasi topilmadi.")
            else:
                await update.message.reply_text("Test sessiyasi topilmadi.")
            return
        
        session = self.user_test_sessions[user_id]
        
        # Natijalarni hisoblash
        total_questions = len(session['questions'])
        correct_answers = session['score']
        wrong_answers = total_questions - correct_answers
        percentage = (correct_answers / total_questions) * 100 if total_questions > 0 else 0
        time_taken = datetime.now() - session['start_time']
        
        # Natijani saqlash
        result_id = self.save_test_result(
            user_id=user_id,
            level=session['level'],
            score=correct_answers,
            total_questions=total_questions,
            correct_answers=correct_answers,
            wrong_answers=wrong_answers,
            percentage=percentage,
            details=json.dumps(session['answers'])
        )
        
        # Foydalanuvchi statistikasini yangilash
        self.update_user_stats(user_id, session['level'], correct_answers)
        
        # Natijalarni formatlash
        result_text = f"""*TEST NATIJALARI*

Daraja: *{self.levels.get(session['level'], session['level'])}*
Umumiy savollar: *{total_questions}*
Togri javoblar: *{correct_answers}*
Notogri javoblar: *{wrong_answers}*
Foiz: *{percentage:.1f}%*
Vaqt: *{time_taken.seconds // 60}:{time_taken.seconds % 60:02d}*

Sana: {datetime.now().strftime('%d.%m.%Y %H:%M')}
Natija ID: #{result_id}"""
        
        # Tafsilotlar
        details_text = "\n\n*Tafsilotlar:*\n"
        for i, answer in enumerate(session['answers'], 1):
            status = "✅" if answer['is_correct'] else "❌"
            user_answer = answer['answer'] if answer['answer'] != 'SKIP' else "O'tkazib yuborildi"
            correct_answer = answer['correct_answer']
            
            details_text += f"\n{i}. {status} {answer['question_text']}\n"
            details_text += f"   Sizning javobingiz: {user_answer}\n"
            if not answer['is_correct'] and answer['answer'] != 'SKIP':
                details_text += f"   Togri javob: {correct_answer}\n"
            if answer['explanation']:
                details_text += f"   Izoh: {answer['explanation']}\n"
        
        # Adminlarga xabar yuborish
        await self.notify_admins_about_test_result(update, context, session, user_id, result_id, percentage)
        
        # Harakat tugmalari
        keyboard = [
            [
                InlineKeyboardButton("Yangi test", callback_data="start_test"),
                InlineKeyboardButton("Bosh menyu", callback_data="main_menu")
            ]
        ]
        
        if user_id in ADMINS:
            keyboard.append([
                InlineKeyboardButton("Admin panel", callback_data="admin_login")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        full_text = result_text + details_text
        
        # Telegram xabar chegarasini hisobga olish (4096 belgi)
        if len(full_text) > 4000:
            full_text = result_text + "\n\n*Tafsilotlar juda uzun. Faqat natijalar ko'rsatilmoqda.*"
        
        if query:
            await query.edit_message_text(
                full_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                full_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        
        # Test sessiyasini tozalash
        del self.user_test_sessions[user_id]
    
    def save_test_result(self, user_id: int, level: str, score: int, 
                        total_questions: int, correct_answers: int, 
                        wrong_answers: int, percentage: float, details: str) -> int:
        """Test natijasini saqlash"""
        cursor = self.db.cursor()
        
        # Foydalanuvchi ID sini olish
        cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (user_id,))
        user_db_id = cursor.fetchone()
        
        if not user_db_id:
            # Agar foydalanuvchi mavjud bo'lmasa, yaratish
            cursor.execute('''
                INSERT INTO users (telegram_id, username, first_name)
                VALUES (?, ?, ?)
            ''', (user_id, "user_" + str(user_id), "User"))
            user_db_id = cursor.lastrowid
        else:
            user_db_id = user_db_id[0]
        
        cursor.execute('''
            INSERT INTO test_results 
            (user_id, level, score, total_questions, correct_answers, 
             wrong_answers, percentage, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_db_id, level, score, total_questions, 
            correct_answers, wrong_answers, percentage, details
        ))
        
        result_id = cursor.lastrowid
        self.db.commit()
        
        return result_id
    
    def update_user_stats(self, telegram_id: int, level: str, score: int) -> None:
        """Foydalanuvchi statistikasini yangilash"""
        cursor = self.db.cursor()
        
        # Testlar sonini oshirish
        cursor.execute('''
            UPDATE users 
            SET total_tests = total_tests + 1,
                best_score = MAX(best_score, ?),
                current_level = ?,
                last_active = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
        ''', (score, level, telegram_id))
        
        self.db.commit()
    
    async def notify_admins_about_test_result(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                            session: Dict, user_id: int, result_id: int, percentage: float) -> None:
        """Adminlarga yangi test natijasi haqida xabar berish"""
        
        username = update.effective_user.username
        if not username:
            username = "Nomalum"
        
        notification_text = f"""*YANGI TEST NATIJASI*

Foydalanuvchi: @{username}
User ID: `{user_id}`
Daraja: *{self.levels.get(session['level'], session['level'])}*
Ball: *{session['score']}/{len(session['questions'])}*
Foiz: *{percentage:.1f}%*
Vaqt: {datetime.now().strftime('%H:%M:%S')}
Natija ID: #{result_id}"""
        
        # Barcha adminlarga xabar yuborish
        for admin_id in ADMINS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=notification_text,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Admin {admin_id} ga xabar yuborishda xatolik: {e}")
    
    async def show_results_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Natijalarni ko'rsatish"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        
        cursor = self.db.cursor()
        
        # Foydalanuvchi ID sini olish
        cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (user_id,))
        user_db_id = cursor.fetchone()
        
        if not user_db_id:
            await query.edit_message_text("Siz hali test topshirmagansiz.")
            return
        
        # So'nggi 5 ta natija
        cursor.execute('''
            SELECT level, score, total_questions, percentage, test_date
            FROM test_results
            WHERE user_id = ?
            ORDER BY test_date DESC
            LIMIT 5
        ''', (user_db_id[0],))
        
        results = cursor.fetchall()
        
        if not results:
            await query.edit_message_text("Siz hali test topshirmagansiz.")
            return
        
        results_text = "*SIZNING NATIJALARINGIZ*\n\n"
        
        for i, result in enumerate(results, 1):
            date = datetime.strptime(result[4], '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y')
            level_name = self.levels.get(result[0], result[0])
            
            results_text += (
                f"{i}. {level_name}\n"
                f"   Ball: {result[1]}/{result[2]}\n"
                f"   Foiz: {result[3]:.1f}%\n"
                f"   Sana: {date}\n\n"
            )
        
        # Umumiy statistika
        cursor.execute("SELECT COUNT(*), AVG(percentage), MAX(score) FROM test_results WHERE user_id = ?", (user_db_id[0],))
        stats = cursor.fetchone()
        
        stats_text = f"""*UMUMIY STATISTIKA:*
Testlar soni: {stats[0] or 0}
Ortacha foiz: {stats[1] or 0:.1f}%
Eng yuqori ball: {stats[2] or 0}"""
        
        keyboard = [
            [
                InlineKeyboardButton("Yangi test", callback_data="start_test"),
                InlineKeyboardButton("Bosh menyu", callback_data="main_menu")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            results_text + stats_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def show_profile_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Profilni ko'rsatish"""
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        user_id = user.id
        
        cursor = self.db.cursor()
        
        # Foydalanuvchi ma'lumotlari
        cursor.execute('''
            SELECT username, first_name, last_name, joined_date, total_tests, best_score, current_level
            FROM users
            WHERE telegram_id = ?
        ''', (user_id,))
        
        user_data = cursor.fetchone()
        
        if not user_data:
            await query.edit_message_text("Profil topilmadi.")
            return
        
        current_level = self.levels.get(user_data[6], user_data[6])
        
        profile_text = f"""*PROFIL MALUMOTLARI*

Ism: {user_data[1]} {user_data[2] or ''}
Username: @{user_data[0] or 'Nomalum'}
Qoshilgan sana: {user_data[3][:10]}

*STATISTIKA*
Testlar soni: {user_data[4]}
Eng yaxshi natija: {user_data[5]} ball
Joriy daraja: {current_level}

Foydalanuvchi ID: `{user_id}`"""
        
        keyboard = [
            [
                InlineKeyboardButton("Test yechish", callback_data="start_test"),
                InlineKeyboardButton("Natijalarim", callback_data="my_results")
            ]
        ]
        
        if user_id in ADMINS:
            keyboard.append([
                InlineKeyboardButton("Admin panel", callback_data="admin_login")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            profile_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    # ==================== ADMIN FUNCTIONS ====================
    
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/admin komandasi"""
        user_id = update.effective_user.id
        
        if user_id not in ADMINS:
            await update.message.reply_text(
                "❌ Siz admin emassiz!",
                parse_mode='Markdown'
            )
            return
        
        await self.show_admin_login(update, context)
    
    async def show_admin_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Admin login ekranini ko'rsatish"""
        user_id = update.effective_user.id
        
        if user_id not in ADMINS:
            await update.message.reply_text("❌ Siz admin emassiz!")
            return
        
        # Admin login kodini yaratish
        login_code = secrets.token_hex(3).upper()  # 6 ta raqamli kod
        session_id = hashlib.sha256(f"{user_id}_{login_code}".encode()).hexdigest()[:16]
        
        # Session ni saqlash
        cursor = self.db.cursor()
        cursor.execute('''
            INSERT INTO admin_sessions (session_id, admin_id, expires_at)
            VALUES (?, ?, ?)
        ''', (session_id, user_id, (datetime.now() + timedelta(minutes=10)).isoformat()))
        self.db.commit()
        
        login_text = f"""*ADMIN PANELGA KIRISH*

Admin ID: `{user_id}`
Kirish kodi: `{login_code}`
Kod amal qilish muddati: 10 daqiqa

Iltimos, parolni kiriting:"""
        
        await update.message.reply_text(
            login_text,
            parse_mode='Markdown'
        )
        
        # Admin holatini o'rnatish
        self.admin_sessions[user_id] = {
            'state': AdminStates.WAITING_FOR_PASSWORD,
            'session_id': session_id,
            'login_code': login_code
        }
    
    async def handle_admin_password(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Admin parolini tekshirish"""
        user_id = update.effective_user.id
        
        if user_id not in self.admin_sessions:
            return
        
        if self.admin_sessions[user_id]['state'] != AdminStates.WAITING_FOR_PASSWORD:
            return
        
        password = update.message.text.strip()
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        # Parolni tekshirish
        if password_hash == ADMIN_PASSWORDS.get("admin"):
            # Session ni tasdiqlash
            cursor = self.db.cursor()
            session_id = self.admin_sessions[user_id]['session_id']
            cursor.execute('''
                UPDATE admin_sessions 
                SET is_active = 1 
                WHERE session_id = ? AND admin_id = ?
            ''', (session_id, user_id))
            self.db.commit()
            
            # Admin panelni ko'rsatish
            self.admin_sessions[user_id]['state'] = AdminStates.MAIN_MENU
            await self.show_admin_panel(update, context)
        else:
            await update.message.reply_text(
                "❌ Noto'g'ri parol! Qayta urinib koring yoki /admin buyrug'i bilan yangi kod oling."
            )
            # Session ni bekor qilish
            if user_id in self.admin_sessions:
                del self.admin_sessions[user_id]
    
    async def show_admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Admin panelni ko'rsatish"""
        user_id = update.effective_user.id
        
        # Umumiy statistikani hisoblash
        cursor = self.db.cursor()
        
        # Foydalanuvchilar soni
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
        total_users = cursor.fetchone()[0]
        
        # Testlar soni
        cursor.execute("SELECT COUNT(*) FROM test_results")
        total_tests = cursor.fetchone()[0]
        
        # Savollar soni
        cursor.execute("SELECT COUNT(*) FROM questions WHERE is_active = 1")
        total_questions = cursor.fetchone()[0]
        
        # Bugungi testlar
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("SELECT COUNT(*) FROM test_results WHERE DATE(test_date) = ?", (today,))
        today_tests = cursor.fetchone()[0]
        
        admin_text = f"""*ADMIN PANEL*

Foydalanuvchilar: *{total_users}*
Testlar: *{total_tests}*
Savollar: *{total_questions}*
Bugungi testlar: *{today_tests}*
Sana: {datetime.now().strftime('%d.%m.%Y %H:%M')}"""
        
        keyboard = [
            [
                InlineKeyboardButton("Foydalanuvchilar", callback_data="admin_users"),
                InlineKeyboardButton("Test natijalari", callback_data="admin_results")
            ],
            [
                InlineKeyboardButton("Savollar boshqaruvi", callback_data="admin_questions"),
                InlineKeyboardButton("Xabar yuborish", callback_data="admin_broadcast")
            ],
            [
                InlineKeyboardButton("Statistika", callback_data="admin_stats"),
                InlineKeyboardButton("Chiqish", callback_data="admin_logout")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            admin_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def admin_questions_management(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Savollarni boshqarish"""
        query = update.callback_query
        await query.answer()
        
        cursor = self.db.cursor()
        
        # Daraja bo'yicha savollar soni
        questions_by_level = {}
        for level in self.levels.keys():
            cursor.execute("SELECT COUNT(*) FROM questions WHERE level = ? AND is_active = 1", (level,))
            count = cursor.fetchone()[0]
            questions_by_level[level] = count
        
        questions_text = "*SAVOLLAR BOSHQARUVI*\n\n"
        
        for level, count in questions_by_level.items():
            level_name = self.levels.get(level, level)
            questions_text += f"{level_name}: *{count}* ta savol\n"
        
        # Umumiy statistika
        cursor.execute("SELECT COUNT(*) FROM questions WHERE is_active = 1")
        total_questions = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM questions WHERE is_active = 0")
        inactive_questions = cursor.fetchone()[0]
        
        stats_text = f"""\n*STATISTIKA:*
Faol savollar: *{total_questions}*
Faol emas: *{inactive_questions}*"""
        
        keyboard = [
            [
                InlineKeyboardButton("Savol qoshish", callback_data="admin_add_question"),
                InlineKeyboardButton("Savollarni korish", callback_data="admin_view_questions")
            ],
            [
                InlineKeyboardButton("Statistika", callback_data="admin_questions_stats"),
            ],
            [
                InlineKeyboardButton("Orqaga", callback_data="admin_back")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            questions_text + stats_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def admin_add_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Savol qo'shish"""
        query = update.callback_query
        await query.answer()
        
        # Darajalarni tanlash
        keyboard = []
        for level_key, level_name in self.levels.items():
            # Har bir daraja uchun mavjud savollar soni
            question_count = self.get_question_count(level_key)
            button_text = f"{level_name} ({question_count} savol)"
            keyboard.append([
                InlineKeyboardButton(button_text, callback_data=f"admin_add_level_{level_key}")
            ])
        
        keyboard.append([
            InlineKeyboardButton("Orqaga", callback_data="admin_questions")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "*YANGI SAVOL QOSHISH*\n\n"
            "Iltimos, darajani tanlang:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def admin_add_question_process(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Savol qo'shish jarayoni"""
        query = update.callback_query
        await query.answer()
        
        level = query.data.replace("admin_add_level_", "")
        
        # Savol ma'lumotlarini so'rash
        context.user_data['adding_question'] = {'level': level}
        self.admin_sessions[update.effective_user.id]['state'] = AdminStates.ADDING_QUESTION
        
        level_name = self.levels.get(level, level)
        
        await query.edit_message_text(
            f"*{level_name} darajasi uchun savol qoshish*\n\n"
            "Iltimos, savolni quyidagi formatda yuboring:\n\n"
            "Savol matni\n"
            "A) variant 1\n"
            "B) variant 2\n"
            "C) variant 3\n"
            "D) variant 4\n"
            "Togri javob (A, B, C, D)\n"
            "Izoh (ixtiyoriy)\n\n"
            "Misol:\n"
            "What is your ___?\n"
            "A) name\n"
            "B) named\n"
            "C) names\n"
            "D) naming\n"
            "A\n"
            "What is your name? - Ismingiz nima?",
            parse_mode='Markdown'
        )
    
    async def handle_admin_question_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Admin tomonidan kiritilgan savolni qayta ishlash"""
        user_id = update.effective_user.id
        
        if user_id not in self.admin_sessions:
            return
        
        if self.admin_sessions[user_id]['state'] != AdminStates.ADDING_QUESTION:
            return
        
        question_data = update.message.text.strip()
        lines = question_data.split('\n')
        
        try:
            # Savol ma'lumotlarini ajratish
            question_text = lines[0].strip()
            options = []
            correct_answer = None
            explanation = ""
            
            for line in lines[1:]:
                line = line.strip()
                if line.startswith(('A)', 'B)', 'C)', 'D)')):
                    options.append(line[2:].strip())
                elif line.upper() in ['A', 'B', 'C', 'D']:
                    correct_answer = line.upper()
                elif line:
                    explanation = line
            
            if len(options) < 2 or not correct_answer:
                raise ValueError("Notogri format")
            
            # Savolni ma'lumotlar bazasiga qo'shish
            cursor = self.db.cursor()
            cursor.execute('''
                INSERT INTO questions 
                (level, question_text, option_a, option_b, option_c, option_d, correct_answer, explanation, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                context.user_data['adding_question']['level'],
                question_text,
                options[0] if len(options) > 0 else '',
                options[1] if len(options) > 1 else '',
                options[2] if len(options) > 2 else '',
                options[3] if len(options) > 3 else '',
                correct_answer,
                explanation,
                f"admin_{user_id}"
            ))
            self.db.commit()
            
            level_name = self.levels.get(context.user_data['adding_question']['level'])
            
            await update.message.reply_text(
                f"✅ Savol muvaffaqiyatli qoshildi!\n\n"
                f"Savol: {question_text}\n"
                f"Daraja: {level_name}\n"
                f"Togri javob: {correct_answer}\n\n"
                "Boshqa savol qoshish uchun /admin buyrugidan foydalaning.",
                parse_mode='Markdown'
            )
            
            # Admin holatini tiklash
            del self.admin_sessions[user_id]
            if 'adding_question' in context.user_data:
                del context.user_data['adding_question']
            
        except Exception as e:
            logger.error(f"Savol qoshishda xatolik: {e}")
            await update.message.reply_text(
                "❌ Xatolik! Iltimos, qayta urinib koring.\n\n"
                "Togri format:\n"
                "Savol matni\n"
                "A) variant 1\n"
                "B) variant 2\n"
                "...\n"
                "Togri javob harfi\n"
                "Izoh (ixtiyoriy)"
            )
    
    async def admin_view_questions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Savollarni ko'rish"""
        query = update.callback_query
        await query.answer()
        
        cursor = self.db.cursor()
        
        # Har bir daraja uchun savollar
        questions_text = "*MAVJUD SAVOLLAR*\n\n"
        
        for level_key, level_name in self.levels.items():
            cursor.execute('''
                SELECT id, question_text, correct_answer
                FROM questions 
                WHERE level = ? AND is_active = 1
                ORDER BY id
                LIMIT 5
            ''', (level_key,))
            
            questions = cursor.fetchall()
            
            if questions:
                questions_text += f"*{level_name}:*\n"
                for q in questions:
                    questions_text += f"{q[0]}. {q[1][:50]}... (Javob: {q[2]})\n"
                questions_text += "\n"
        
        keyboard = [
            [
                InlineKeyboardButton("Barcha savollar", callback_data="admin_all_questions"),
                InlineKeyboardButton("Savol qidirish", callback_data="admin_search_question")
            ],
            [
                InlineKeyboardButton("Orqaga", callback_data="admin_questions")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            questions_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Statistika ko'rsatish"""
        query = update.callback_query
        await query.answer()
        
        cursor = self.db.cursor()
        
        # Keng qamrovli statistika
        stats = self.calculate_comprehensive_stats()
        
        stats_text = f"""*UMUMIY STATISTIKA*

*Foydalanuvchilar:*
• Jami royhatdan otgan: {stats['total_users']}
• Faol (oxirgi 7 kun): {stats['active_week']}
• Faol (oxirgi 30 kun): {stats['active_month']}
• Test topshirgan: {stats['tested_users']}
• Yangi (bugun): {stats['new_today']}

*Testlar:*
• Jami testlar: {stats['total_tests']}
• Bugungi testlar: {stats['today_tests']}
• Ortacha foiz: {stats['avg_percentage']:.1f}%
• Eng yuqori ball: {stats['max_score']}
• Eng past ball: {stats['min_score']}

*Savollar:*
• Jami savollar: {stats['total_questions']}
• Faol savollar: {stats['active_questions']}
• Beginner: {stats['beginner_q']}
• Elementary: {stats['elementary_q']}
• Pre-Intermediate: {stats['pre_intermediate_q']}
• Intermediate: {stats['intermediate_q']}
• Upper-Intermediate: {stats['upper_intermediate_q']}
• Advanced: {stats['advanced_q']}"""
        
        keyboard = [
            [
                InlineKeyboardButton("Kunlik statistika", callback_data="admin_daily_stats"),
                InlineKeyboardButton("Oylik statistika", callback_data="admin_monthly_stats")
            ],
            [
                InlineKeyboardButton("Orqaga", callback_data="admin_back")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            stats_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    def calculate_comprehensive_stats(self) -> Dict:
        """Keng qamrovli statistika hisoblash"""
        cursor = self.db.cursor()
        stats = {}
        
        # Foydalanuvchilar statistika
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
        stats['total_users'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE last_active > DATE('now', '-7 day')")
        stats['active_week'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE last_active > DATE('now', '-30 day')")
        stats['active_month'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE total_tests > 0")
        stats['tested_users'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE DATE(joined_date) = DATE('now')")
        stats['new_today'] = cursor.fetchone()[0]
        
        # Testlar statistika
        cursor.execute("SELECT COUNT(*) FROM test_results")
        stats['total_tests'] = cursor.fetchone()[0]
        
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("SELECT COUNT(*) FROM test_results WHERE DATE(test_date) = ?", (today,))
        stats['today_tests'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT AVG(percentage) FROM test_results")
        stats['avg_percentage'] = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT MAX(score) FROM test_results")
        stats['max_score'] = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT MIN(score) FROM test_results WHERE score > 0")
        stats['min_score'] = cursor.fetchone()[0] or 0
        
        # Savollar statistika
        cursor.execute("SELECT COUNT(*) FROM questions")
        stats['total_questions'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM questions WHERE is_active = 1")
        stats['active_questions'] = cursor.fetchone()[0]
        
        # Daraja bo'yicha savollar
        for level in ['beginner', 'elementary', 'pre_intermediate', 'intermediate', 'upper_intermediate', 'advanced']:
            cursor.execute("SELECT COUNT(*) FROM questions WHERE level = ? AND is_active = 1", (level,))
            stats[f"{level}_q"] = cursor.fetchone()[0]
        
        return stats
    
    async def admin_logout(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Admin paneldan chiqish"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        
        if user_id in self.admin_sessions:
            # Session ni yopish
            cursor = self.db.cursor()
            if 'session_id' in self.admin_sessions[user_id]:
                cursor.execute('''
                    UPDATE admin_sessions 
                    SET is_active = 0 
                    WHERE session_id = ?
                ''', (self.admin_sessions[user_id]['session_id'],))
                self.db.commit()
            
            del self.admin_sessions[user_id]
        
        await query.edit_message_text(
            "✅ Admin paneldan muvaffaqiyatli chiqdingiz!\n\n"
            "Qayta kirish uchun /admin buyrugini yuboring.",
            parse_mode='Markdown'
        )
    
    async def handle_admin_buttons(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
        """Admin tugmalarini qayta ishlash"""
        user_id = update.effective_user.id
        
        # Admin tekshirish
        if user_id not in ADMINS:
            await update.callback_query.edit_message_text("❌ Siz admin emassiz!")
            return
        
        if data == "admin_login":
            await self.show_admin_login(update, context)
        
        elif data == "admin_users":
            await self.admin_users_management(update, context)
        
        elif data == "admin_results":
            await self.admin_results_management(update, context)
        
        elif data == "admin_questions":
            await self.admin_questions_management(update, context)
        
        elif data == "admin_add_question":
            await self.admin_add_question(update, context)
        
        elif data.startswith("admin_add_level_"):
            await self.admin_add_question_process(update, context)
        
        elif data == "admin_view_questions":
            await self.admin_view_questions(update, context)
        
        elif data == "admin_stats":
            await self.admin_stats(update, context)
        
        elif data == "admin_logout":
            await self.admin_logout(update, context)
        
        elif data == "admin_back":
            await self.show_admin_panel(update, context)
    
    # ==================== MAIN HANDLERS ====================
    
    def add_user(self, telegram_id: int, username: str, first_name: str, last_name: str) -> None:
        """Yangi foydalanuvchi qo'shish"""
        cursor = self.db.cursor()
        
        # Foydalanuvchi mavjudligini tekshirish
        cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
        user = cursor.fetchone()
        
        if not user:
            cursor.execute('''
                INSERT INTO users (telegram_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
            ''', (telegram_id, username, first_name, last_name))
        else:
            # Faollikni yangilash
            cursor.execute('''
                UPDATE users 
                SET username = ?, first_name = ?, last_name = ?, last_active = CURRENT_TIMESTAMP
                WHERE telegram_id = ?
            ''', (username, first_name, last_name, telegram_id))
        
        self.db.commit()
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Tugmalarni qayta ishlash"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        # Admin tugmalari
        if data.startswith('admin_'):
            await self.handle_admin_buttons(update, context, data)
        
        # User test tugmalari
        elif data == "start_test":
            await self.start_test_command(update, context)
        
        elif data.startswith("select_level_"):
            await self.select_test_level(update, context)
        
        elif data.startswith("answer_"):
            await self.handle_test_answer(update, context)
        
        elif data == "skip_question":
            await self.skip_question(update, context)
        
        elif data == "cancel_test":
            await self.cancel_test(update, context)
        
        elif data == "my_results":
            await self.show_results_command(update, context)
        
        elif data == "profile":
            await self.show_profile_command(update, context)
        
        elif data == "help":
            await self.help_command_button(update, context)
        
        elif data == "main_menu":
            await self.start(update, context)
    
    async def help_command_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Yordam tugmasi"""
        query = update.callback_query
        await query.answer()
        
        await self.help_command(update, context)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Xabarlarni qayta ishlash"""
        user_id = update.effective_user.id
        
        # Admin holatlarini tekshirish
        if user_id in self.admin_sessions:
            state = self.admin_sessions[user_id]['state']
            
            if state == AdminStates.WAITING_FOR_PASSWORD:
                await self.handle_admin_password(update, context)
                return
            
            elif state == AdminStates.ADDING_QUESTION:
                await self.handle_admin_question_input(update, context)
                return
        
        # Oddiy xabarlar
        message = update.message.text
        
        if message.startswith('RESULT:'):
            await self.handle_test_result(update, context)
        elif message.startswith('/'):
            # Komandalarni boshqa handlerlar qayta ishlaydi
            pass
        else:
            await update.message.reply_text(
                "Botdan foydalanish uchun /help buyrugini yuboring."
            )
    
    async def handle_test_result(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Web ilovadan kelgan test natijasini qayta ishlash"""
        try:
            result_data = json.loads(update.message.text.replace('RESULT:', ''))
            user_id = update.effective_user.id
            
            # Foydalanuvchini qo'shish/yangilash
            self.add_user(user_id, update.effective_user.username, 
                         update.effective_user.first_name, update.effective_user.last_name)
            
            # Natijani saqlash
            cursor = self.db.cursor()
            
            # Foydalanuvchi ID sini olish
            cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (user_id,))
            user_db_id = cursor.fetchone()
            
            if not user_db_id:
                await update.message.reply_text("❌ Foydalanuvchi topilmadi.")
                return
            
            cursor.execute('''
                INSERT INTO test_results 
                (user_id, level, score, total_questions, correct_answers, wrong_answers, percentage, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_db_id[0],
                result_data.get('level', 'unknown'),
                result_data.get('score', 0),
                result_data.get('total_questions', 0),
                result_data.get('correct_answers', 0),
                result_data.get('wrong_answers', 0),
                result_data.get('percentage', 0),
                json.dumps(result_data.get('details', {}))
            ))
            
            result_id = cursor.lastrowid
            
            # Foydalanuvchi statistikasini yangilash
            cursor.execute('''
                UPDATE users 
                SET total_tests = total_tests + 1,
                    best_score = MAX(best_score, ?),
                    last_active = CURRENT_TIMESTAMP
                WHERE telegram_id = ?
            ''', (result_data.get('score', 0), user_id))
            
            self.db.commit()
            
            # Adminlarga xabar berish
            await self.notify_admins_about_test_result_web(update, context, result_data, user_id, result_id)
            
            # Foydalanuvchiga javob
            await update.message.reply_text(
                f"✅ Test natijangiz saqlandi! ID: #{result_id}\n\n"
                f"Daraja: {result_data.get('level', 'Nomalum')}\n"
                f"Ball: {result_data.get('score', 0)}\n"
                f"Togri: {result_data.get('correct_answers', 0)}\n"
                f"Notogri: {result_data.get('wrong_answers', 0)}",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Natijani saqlashda xatolik: {e}")
            await update.message.reply_text("❌ Xatolik yuz berdi. Iltimos, keyinroq qayta urinib koring.", parse_mode='Markdown')
    
    async def notify_admins_about_test_result_web(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                                result_data: Dict, user_id: int, result_id: int) -> None:
        """Web ilovadan kelgan natija uchun adminlarga xabar berish"""
        
        username = update.effective_user.username
        if not username:
            username = "Nomalum"
        
        notification_text = f"""*WEB ILOVA NATIJASI*

Foydalanuvchi: @{username}
User ID: `{user_id}`
Daraja: *{result_data.get('level', 'Nomalum')}*
Ball: *{result_data.get('score', 0)}*
Foiz: *{result_data.get('percentage', 0):.1f}%*
Vaqt: {datetime.now().strftime('%H:%M:%S')}
Natija ID: #{result_id}"""
        
        # Barcha adminlarga xabar yuborish
        for admin_id in ADMINS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=notification_text,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Admin {admin_id} ga xabar yuborishda xatolik: {e}")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/help komandasi"""
        help_text = """*BOTDAN FOYDALANISH BOYICHA YORDAM*

*Asosiy komandalar:*
/start - Botni ishga tushirish
/test - Test yechishni boshlash (tugma orqali)
/results - Natijalaringizni korish
/profile - Profilingizni korish
/help - Yordam
/admin - Admin panel (faqat adminlar uchun)

*Test jarayoni:*
1. Test yechish tugmasini bosing
2. Darajangizni tanlang
3. Har bir savolga javob bering
4. Test tugaganda natijangizni koring

*Admin panel:*
- Foydalanuvchilarni boshqarish
- Test natijalarini korish
- Savollar qoshish/tahrirlash
- Barchaga xabar yuborish
- Statistika

*Aloqa:*
Muammo yuz bersa: @your_support
Takliflar uchun: @your_feedback"""
        
        if isinstance(update, Update) and update.message:
            await update.message.reply_text(help_text, parse_mode='Markdown')
        elif hasattr(update, 'callback_query'):
            await update.callback_query.edit_message_text(help_text, parse_mode='Markdown')
    
    def setup_handlers(self):
        """Handlerni sozlash"""
        # Asosiy komandalar
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("admin", self.admin_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        
        # Callback query handler
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Message handler
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
    
    def run(self):
        """Botni ishga tushirish"""
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.setup_handlers()
        
        logger.info("Bot ishga tushdi...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    """Asosiy funksiya"""
    bot = EnglishTestBot()
    bot.run()


if __name__ == '__main__':
    main()