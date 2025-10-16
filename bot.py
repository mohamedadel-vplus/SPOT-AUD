import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import subprocess
import re
import tempfile
import shutil

# إعدادات التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# توكن البوت - ضع توكنك هنا
BOT_TOKEN = "8363807979:AAE6YEVpBwOdE4ry4DYFG_WXTCDKZwNq9bs"

# مجلد مؤقت للتحميلات
TEMP_DIR = "temp_downloads"

# إنشاء المجلد المؤقت إذا لم يكن موجوداً
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# تنظيف الملفات المؤقتة القديمة
def cleanup_old_files():
    try:
        for filename in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                logging.error(f"Error deleting {file_path}: {e}")
    except Exception as e:
        logging.error(f"Error in cleanup: {e}")

# استخراج معلومات الأغنية من رابط سبوتيفاي
def get_track_info(url):
    try:
        track_pattern = r'https://open\.spotify\.com/track/([a-zA-Z0-9]+)'
        match = re.search(track_pattern, url)
        
        if match:
            return {'track_id': match.group(1), 'url': url}
        return None
    except Exception as e:
        logging.error(f"Error extracting track info: {e}")
        return None

# تحميل الأغنية باستخدام spotdl
def download_with_spotdl(spotify_url):
    try:
        # تنظيف الملفات القديمة أولاً
        cleanup_old_files()
        
        # استخدام مجلد مؤقت للتحميل
        temp_download_dir = os.path.join(TEMP_DIR, "current_download")
        if not os.path.exists(temp_download_dir):
            os.makedirs(temp_download_dir)
        
        # أمر spotdl للتحميل
        cmd = [
            'spotdl',
            'download',
            spotify_url,
            '--output', os.path.join(temp_download_dir, '{artist} - {title}.{ext}'),
            '--format', 'mp3'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0:
            # البحث عن الملف الذي تم تحميله
            for file in os.listdir(temp_download_dir):
                if file.endswith('.mp3'):
                    file_path = os.path.join(temp_download_dir, file)
                    return file_path
        
        return None
        
    except subprocess.TimeoutExpired:
        logging.error("Download timeout")
        return None
    except Exception as e:
        logging.error(f"Error with spotdl: {e}")
        return None

# الحصول على معلومات الملف للمساعدة في إرساله
def get_audio_info(file_path):
    try:
        import mutagen
        audio = mutagen.File(file_path)
        
        if audio is not None:
            title = ""
            artist = ""
            duration = 0
            
            # محاولة استخراج المعلومات من metadata
            if 'TIT2' in audio:  # Title in ID3
                title = str(audio['TIT2'])
            if 'TPE1' in audio:  # Artist in ID3
                artist = str(audio['TPE1'])
            if audio.info.length:
                duration = int(audio.info.length)
            
            # إذا لم توجد metadata، استخدام اسم الملف
            if not title:
                title = os.path.basename(file_path).replace('.mp3', '')
            
            return {
                'title': title,
                'artist': artist,
                'duration': duration,
                'file_size': os.path.getsize(file_path)
            }
    except Exception as e:
        logging.error(f"Error getting audio info: {e}")
    
    # المعلومات الافتراضية إذا فشل الاستخراج
    return {
        'title': os.path.basename(file_path).replace('.mp3', ''),
        'artist': 'Unknown Artist',
        'duration': 0,
        'file_size': os.path.getsize(file_path)
    }

# إرسال الملف وحذفه محلياً
async def send_and_cleanup(update: Update, file_path):
    try:
        if not file_path or not os.path.exists(file_path):
            await update.message.reply_text("❌ الملف غير موجود للإرسال")
            return False
        
        # الحصول على معلومات الملف
        audio_info = get_audio_info(file_path)
        
        # التحقق من حجم الملف (تيليجرام حد 50MB)
        if audio_info['file_size'] > 50 * 1024 * 1024:
            await update.message.reply_text("❌ حجم الملف كبير جداً للإرسال عبر تيليجرام")
            return False
        
        await update.message.reply_text("📤 جاري رفع الملف إلى سيرفرات تيليجرام...")
        
        # إرسال الملف الصوتي
        with open(file_path, 'rb') as audio_file:
            await update.message.reply_audio(
                audio_file,
                title=audio_info['title'],
                performer=audio_info['artist'],
                duration=audio_info['duration']
            )
        
        await update.message.reply_text("✅ تم رفع الملف بنجاح!")
        
        # حذف الملف محلياً بعد الرفع الناجح
        try:
            os.remove(file_path)
            # حذف المجلد إذا كان فارغاً
            folder_path = os.path.dirname(file_path)
            if os.path.exists(folder_path) and not os.listdir(folder_path):
                os.rmdir(folder_path)
            logging.info(f"تم حذف الملف محلياً: {file_path}")
        except Exception as e:
            logging.error(f"Error deleting file {file_path}: {e}")
        
        return True
        
    except Exception as e:
        logging.error(f"Error in send_and_cleanup: {e}")
        await update.message.reply_text("  🫷 انتظر قليلا")
        return False

# معالجة الأمر /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎵 بوت تحميل سبوتيفاي الذكي\n\n"
        "أرسل رابط أغنية من سبوتيفاي الآن!"
    )

# معالجة الأمر /cleanup
async def cleanup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cleanup_old_files()
        await update.message.reply_text("🧹 تم تنظيف الملفات المؤقتة بنجاح!")
    except Exception as e:
        await update.message.reply_text("❌ حدث خطأ أثناء التنظيف")

# معالجة الأمر /status
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        temp_size = 0
        file_count = 0
        
        for root, dirs, files in os.walk(TEMP_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                temp_size += os.path.getsize(file_path)
                file_count += 1
        
        await update.message.reply_text(
            f"📊 **حالة النظام:**\n"
            f"• عدد الملفات المؤقتة: {file_count}\n"
            f"• المساحة المستخدمة: {temp_size / 1024 / 1024:.2f} MB\n"
            f"• الحالة: ✅ جاهز للاستخدام"
        )
    except Exception as e:
        await update.message.reply_text("❌ حدث خطأ في التحقق من الحالة")

# معالجة رسائل المستخدم
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip()
    
    # التحقق من أن الرسالة تحتوي على رابط سبوتيفاي
    spotify_pattern = r'https://open\.spotify\.com/track/([a-zA-Z0-9]+)'
    match = re.search(spotify_pattern, user_message)
    
    if match:
        await update.message.reply_text("🔍 جاري معالجة الرابط...")
        
        # استخراج معلومات الأغنية
        track_info = get_track_info(user_message)
        
        if track_info:
            await update.message.reply_text("⬇️ جاري تحميل الأغنية من سبوتيفاي...")
            
            # تحميل الأغنية
            file_path = download_with_spotdl(user_message)
            
            if file_path and os.path.exists(file_path):
                await update.message.reply_text("✅ تم التحميل بنجاح! جاري الرفع...")
                
                # إرسال الملف وحذفه محلياً
                success = await send_and_cleanup(update, file_path)
                
                if not success:
                    # محاولة تنظيف إذا فشل الإرسال
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    except:
                        pass
                    
            else:
                await update.message.reply_text(
                    "❌ لم أتمكن من تحميل الأغنية.\n\n"
                    "**الأسباب المحتملة:**\n"
                    "• الأغنية محمية بحقوق الطبع\n"
                    "• مشكلة في الاتصال بالإنترنت\n"
                    "• الرابط غير صالح\n"
                    "• حاول بأغنية أخرى"
                )
        else:
            await update.message.reply_text("❌ رابط غير صحيح")
    else:
        await update.message.reply_text(
            "⚠️ يرجى إرسال رابط صحيح لأغنية على سبوتيفاي\n\n"
            "مثال:\n"
            "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"
        )

# معالجة الأخطاء
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Exception while handling an update: {context.error}")
    
    try:
        await update.message.reply_text(
            "❌ حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى لاحقاً."
        )
    except:
        pass

# الدالة الرئيسية
def main():
    # تنظيف الملفات القديمة عند البدء
    cleanup_old_files()
    
    # إنشاء تطبيق البوت
    application = Application.builder().token(BOT_TOKEN).build()
    
    # إضافة المعالجات
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cleanup", cleanup_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # إضافة معالج الأخطاء
    application.add_error_handler(error_handler)
    
    # بدء البوت
    print("🎵 بوت سبوتيفاي الذكي يعمل...")
    print("💾 الملفات تحذف تلقائياً بعد الرفع")
    application.run_polling()

if __name__ == '__main__':
    main()