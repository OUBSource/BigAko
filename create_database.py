# create_database.py
import sqlite3
import hashlib
import secrets
import os

def generate_salt():
    return secrets.token_hex(16)

def hash_password(password, salt):
    return hashlib.sha256((password + salt).encode()).hexdigest()

def init_database():
    # Удаляем старую базу если существует
    if os.path.exists('users.db'):
        try:
            os.remove('users.db')
            print("Старая база данных удалена")
        except Exception as e:
            print(f"Ошибка при удалении старой базы: {e}")
            return False
    
    try:
        # Создаем подключение к базе
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        print("Создаем таблицу users...")
        # Создаем таблицу пользователей
        cursor.execute('''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        print("Создаем таблицу messages...")
        # Создаем таблицу сообщений
        cursor.execute('''
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                message TEXT NOT NULL,
                message_type TEXT DEFAULT 'text',
                file_name TEXT,
                file_size INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        print("Добавляем тестовых пользователей...")
        # Добавляем тестовых пользователей
        test_users = [
            ('admin', 'admin123'),
            ('user1', 'password1'),
            ('user2', 'password2'),
            ('test', 'test123'),
            ('demo', 'demo123')
        ]
        
        for username, password in test_users:
            salt = generate_salt()
            password_hash = hash_password(password, salt)
            try:
                cursor.execute(
                    "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
                    (username, password_hash, salt)
                )
                print(f"✓ Пользователь {username} добавлен")
            except sqlite3.IntegrityError:
                print(f"✗ Пользователь {username} уже существует")
        
        print("Добавляем тестовые сообщения...")
        # Добавляем тестовые сообщения
        test_messages = [
            ('admin', 'Добро пожаловать в BigAko Messenger! 🚀', 'text', None, None),
            ('admin', 'Это самый современный мессенджер с лучшим дизайном!', 'text', None, None),
            ('user1', 'Привет всем! Как дела?', 'text', None, None),
            ('user2', 'Отлично! Дизайн просто огонь! 🔥', 'text', None, None),
            ('test', 'Тестирую работу мессенджера', 'text', None, None),
            ('demo', 'Отличная работа! 👍', 'text', None, None)
        ]
        
        for username, message, message_type, file_name, file_size in test_messages:
            cursor.execute(
                "INSERT INTO messages (username, message, message_type, file_name, file_size) VALUES (?, ?, ?, ?, ?)",
                (username, message, message_type, file_name, file_size)
            )
            print(f"✓ Сообщение от {username} добавлено")
        
        # Создаем папку для загрузок
        os.makedirs('uploads', exist_ok=True)
        print("✓ Папка uploads создана")
        
        # Сохраняем изменения
        conn.commit()
        
        # Проверяем созданные таблицы
        print("\nПроверяем созданные таблицы...")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print("Таблицы в базе данных:")
        for table in tables:
            print(f"  - {table[0]}")
        
        # Показываем пользователей
        print("\nПользователи в системе:")
        cursor.execute("SELECT id, username, created_at FROM users")
        users = cursor.fetchall()
        for user in users:
            print(f"  ID: {user[0]}, Имя: {user[1]}, Создан: {user[2]}")
        
        # Показываем сообщения
        print("\nПоследние сообщения:")
        cursor.execute("SELECT username, message, timestamp FROM messages ORDER BY id DESC LIMIT 5")
        messages = cursor.fetchall()
        for msg in messages:
            print(f"  {msg[2]} - {msg[0]}: {msg[1]}")
        
        print(f"\n✅ База данных успешно создана: users.db")
        print("📊 Статистика:")
        print(f"   Пользователей: {len(users)}")
        print(f"   Сообщений: {cursor.execute('SELECT COUNT(*) FROM messages').fetchone()[0]}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при создании базы данных: {e}")
        return False
    finally:
        if conn:
            conn.close()

def verify_database():
    """Проверяет корректность структуры базы данных"""
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        # Проверяем структуру таблицы users
        cursor.execute("PRAGMA table_info(users)")
        users_columns = cursor.fetchall()
        expected_users_columns = ['id', 'username', 'password_hash', 'salt', 'created_at']
        actual_users_columns = [col[1] for col in users_columns]
        
        print("Проверка структуры таблицы users:")
        for col in expected_users_columns:
            if col in actual_users_columns:
                print(f"  ✓ {col}")
            else:
                print(f"  ✗ {col} - отсутствует")
        
        # Проверяем структуру таблицы messages
        cursor.execute("PRAGMA table_info(messages)")
        messages_columns = cursor.fetchall()
        expected_messages_columns = ['id', 'username', 'message', 'message_type', 'file_name', 'file_size', 'timestamp']
        actual_messages_columns = [col[1] for col in messages_columns]
        
        print("\nПроверка структуры таблицы messages:")
        for col in expected_messages_columns:
            if col in actual_messages_columns:
                print(f"  ✓ {col}")
            else:
                print(f"  ✗ {col} - отсутствует")
        
        conn.close()
        return all(col in actual_users_columns for col in expected_users_columns) and \
               all(col in actual_messages_columns for col in expected_messages_columns)
        
    except Exception as e:
        print(f"Ошибка при проверке базы данных: {e}")
        return False

def add_test_user(username, password):
    """Добавляет тестового пользователя в существующую базу"""
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        salt = generate_salt()
        password_hash = hash_password(password, salt)
        
        cursor.execute(
            "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
            (username, password_hash, salt)
        )
        
        conn.commit()
        conn.close()
        print(f"✅ Пользователь {username} успешно добавлен")
        return True
        
    except sqlite3.IntegrityError:
        print(f"❌ Пользователь {username} уже существует")
        return False
    except Exception as e:
        print(f"❌ Ошибка при добавлении пользователя: {e}")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("СОЗДАНИЕ БАЗЫ ДАННЫХ BIGAKO MESSENGER")
    print("=" * 50)
    
    # Проверяем, существует ли база
    if os.path.exists('users.db'):
        print("Обнаружена существующая база данных.")
        choice = input("Пересоздать базу? (y/n): ").lower()
        if choice == 'y':
            success = init_database()
        else:
            print("Проверяем структуру существующей базы...")
            verify_database()
            
            # Предлагаем добавить тестового пользователя
            add_user = input("Добавить тестового пользователя? (y/n): ").lower()
            if add_user == 'y':
                username = input("Имя пользователя: ")
                password = input("Пароль: ")
                add_test_user(username, password)
    else:
        success = init_database()
    
    print("\n" + "=" * 50)
    print("ИНСТРУКЦИЯ ПО ЗАПУСКУ:")
    print("1. Запустите основной сервер: python bigako_server.py")
    print("2. Откройте в браузере: http://localhost:8000")
    print("3. Тестовые пользователи: admin/admin123, user1/password1, etc.")
    print("=" * 50)