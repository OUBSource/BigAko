import http.server
import socketserver
import sqlite3
import json
import hashlib
import secrets
import time
import base64
import os
import uuid
from urllib.parse import parse_qs, urlparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import threading

class BigAkoServer:
    def __init__(self):
        self.connections: Dict[str, List] = {}
        self.message_history: List[Dict] = []
        self.lock = threading.Lock()
        self.session_tokens: Dict[str, str] = {}
        self.init_db()
        
    def generate_salt(self) -> str:
        return secrets.token_hex(16)
    
    def hash_password(self, password: str, salt: str) -> str:
        return hashlib.sha256((password + salt).encode()).hexdigest()
    
    def init_db(self):
        if os.path.exists('users.db'):
            try:
                conn = sqlite3.connect('users.db')
                cursor = conn.cursor()
                
                # Проверяем существование таблиц и обновляем структуру если нужно
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
                if not cursor.fetchone():
                    cursor.execute('''
                        CREATE TABLE users (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            username TEXT UNIQUE NOT NULL,
                            password_hash TEXT NOT NULL,
                            salt TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')
                
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
                if not cursor.fetchone():
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
                
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Database error: {e}")
                os.remove('users.db')
        
        # Создаем папку для файлов
        os.makedirs('uploads', exist_ok=True)
    
    def register_user(self, username: str, password: str) -> bool:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        try:
            salt = self.generate_salt()
            password_hash = self.hash_password(password, salt)
            
            cursor.execute(
                "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
                (username, password_hash, salt)
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    
    def verify_user(self, username: str, password: str) -> bool:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT password_hash, salt FROM users WHERE username = ?",
            (username,)
        )
        result = cursor.fetchone()
        conn.close()
        
        if result:
            stored_hash, salt = result
            return self.hash_password(password, salt) == stored_hash
        return False
    
    def add_message(self, username: str, message: str, message_type: str = 'text', 
                   file_name: str = None, file_size: int = None):
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO messages (username, message, message_type, file_name, file_size) VALUES (?, ?, ?, ?, ?)",
            (username, message, message_type, file_name, file_size)
        )
        conn.commit()
        conn.close()
        
        with self.lock:
            self.message_history.append({
                'username': username,
                'message': message,
                'message_type': message_type,
                'file_name': file_name,
                'file_size': file_size,
                'timestamp': datetime.now().isoformat()
            })
            if len(self.message_history) > 100:
                self.message_history = self.message_history[-100:]
    
    def get_recent_messages(self, limit: int = 50) -> List[Dict]:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT username, message, message_type, file_name, file_size, timestamp FROM messages ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        messages = [
            {
                'username': row[0],
                'message': row[1],
                'message_type': row[2],
                'file_name': row[3],
                'file_size': row[4],
                'timestamp': row[5]
            }
            for row in cursor.fetchall()
        ]
        conn.close()
        return messages[::-1]

class BigAkoHandler(http.server.SimpleHTTPRequestHandler):
    server_instance = BigAkoServer()
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        try:
            if self.path == '/':
                self.serve_html('index')
            elif self.path == '/login':
                self.serve_html('login')
            elif self.path == '/register':
                self.serve_html('register')
            elif self.path == '/messenger':
                if self.verify_session():
                    self.serve_html('messenger')
                else:
                    self.redirect('/login')
            elif self.path == '/api/messages':
                if self.verify_session():
                    self.serve_json({'messages': self.server_instance.get_recent_messages()})
                else:
                    self.send_error(401)
            elif self.path.startswith('/download/'):
                self.handle_download()
            elif self.path == '/style.css':
                self.serve_css()
            elif self.path == '/script.js':
                self.serve_js()
            elif self.path == '/api/userinfo':
                if self.verify_session():
                    username = self.get_username_from_session()
                    self.serve_json({'username': username})
                else:
                    self.send_error(401)
            else:
                self.send_error(404)
        except Exception as e:
            print(f"GET error: {e}")
            self.send_error(500)
    
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                post_data = self.rfile.read(content_length)
            else:
                post_data = b''
            
            content_type = self.headers.get('Content-Type', '')
            
            if 'multipart/form-data' in content_type:
                self.handle_multipart(post_data, content_type)
            else:
                data = parse_qs(post_data.decode('utf-8'))
                
                if self.path == '/api/register':
                    self.handle_register(data)
                elif self.path == '/api/login':
                    self.handle_login(data)
                elif self.path == '/api/message':
                    self.handle_message(data)
                elif self.path == '/api/logout':
                    self.handle_logout()
                else:
                    self.send_error(404)
        except Exception as e:
            print(f"POST error: {e}")
            self.send_error(500)
    
    def handle_multipart(self, data, content_type):
        try:
            # Простой парсинг multipart данных
            boundary = content_type.split('boundary=')[1]
            parts = data.split(b'--' + boundary.encode())
            
            file_data = None
            filename = None
            message_text = ''
            
            for part in parts:
                if b'name="file"' in part and b'filename="' in part:
                    headers, file_content = part.split(b'\r\n\r\n', 1)
                    file_content = file_content.rsplit(b'\r\n', 1)[0]
                    
                    # Извлекаем имя файла
                    filename_start = headers.find(b'filename="') + 10
                    filename_end = headers.find(b'"', filename_start)
                    filename = headers[filename_start:filename_end].decode()
                    
                    file_data = file_content
                
                elif b'name="message"' in part:
                    headers, message_content = part.split(b'\r\n\r\n', 1)
                    message_text = message_content.rsplit(b'\r\n', 1)[0].decode()
            
            if file_data and filename:
                file_size = len(file_data)
                if file_size > 50 * 1024 * 1024:  # 50MB limit
                    self.serve_json({'success': False, 'error': 'File too large'})
                    return
                
                # Сохраняем файл
                file_id = str(uuid.uuid4())
                filename = f"{file_id}_{filename}"
                filepath = os.path.join('uploads', filename)
                
                with open(filepath, 'wb') as f:
                    f.write(file_data)
                
                username = self.get_username_from_session()
                if username:
                    self.server_instance.add_message(
                        username, 
                        message_text or 'Shared a file', 
                        'file', 
                        filename, 
                        file_size
                    )
                    self.serve_json({'success': True})
                else:
                    self.send_error(401)
            
        except Exception as e:
            print(f"Multipart error: {e}")
            self.serve_json({'success': False, 'error': 'File upload failed'})
    
    def handle_download(self):
        try:
            filename = self.path.split('/')[-1]
            filepath = os.path.join('uploads', filename)
            
            if os.path.exists(filepath):
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Disposition', f'attachment; filename="{filename.split("_", 1)[1]}"')
                
                with open(filepath, 'rb') as f:
                    file_data = f.read()
                
                self.send_header('Content-Length', str(len(file_data)))
                self.end_headers()
                self.wfile.write(file_data)
            else:
                self.send_error(404)
        except Exception as e:
            print(f"Download error: {e}")
            self.send_error(500)
    
    def handle_register(self, data):
        username = data.get('username', [''])[0]
        password = data.get('password', [''])[0]
        
        if username and password:
            if self.server_instance.register_user(username, password):
                self.serve_json({'success': True})
            else:
                self.serve_json({'success': False, 'error': 'Username already exists'})
        else:
            self.serve_json({'success': False, 'error': 'Invalid data'})
    
    def handle_login(self, data):
        username = data.get('username', [''])[0]
        password = data.get('password', [''])[0]
        
        if username and password:
            if self.server_instance.verify_user(username, password):
                token = secrets.token_hex(32)
                self.server_instance.session_tokens[token] = username
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Set-Cookie', f'session={token}; Path=/; HttpOnly')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True}).encode())
            else:
                self.serve_json({'success': False, 'error': 'Invalid credentials'})
        else:
            self.serve_json({'success': False, 'error': 'Invalid data'})
    
    def handle_message(self, data):
        if not self.verify_session():
            self.send_error(401)
            return
        
        message = data.get('message', [''])[0]
        username = self.get_username_from_session()
        
        if message and username:
            self.server_instance.add_message(username, message)
            self.serve_json({'success': True})
        else:
            self.serve_json({'success': False, 'error': 'Invalid message'})
    
    def handle_logout(self):
        token = self.get_session_token()
        if token in self.server_instance.session_tokens:
            del self.server_instance.session_tokens[token]
        self.send_response(200)
        self.send_header('Set-Cookie', 'session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT')
        self.end_headers()
    
    def verify_session(self) -> bool:
        token = self.get_session_token()
        return token in self.server_instance.session_tokens
    
    def get_session_token(self) -> Optional[str]:
        cookie = self.headers.get('Cookie', '')
        for part in cookie.split(';'):
            if 'session=' in part:
                return part.split('session=')[1].strip()
        return None
    
    def get_username_from_session(self) -> Optional[str]:
        token = self.get_session_token()
        return self.server_instance.session_tokens.get(token)
    
    def redirect(self, location):
        self.send_response(302)
        self.send_header('Location', location)
        self.end_headers()
    
    def serve_html(self, page_type):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
        if page_type == 'index':
            html = self.get_index_html()
        elif page_type == 'login':
            html = self.get_login_html()
        elif page_type == 'register':
            html = self.get_register_html()
        elif page_type == 'messenger':
            html = self.get_messenger_html()
        
        self.wfile.write(html.encode())
    
    def serve_json(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def serve_css(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/css')
        self.end_headers()
        self.wfile.write(self.get_css().encode())
    
    def serve_js(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/javascript')
        self.end_headers()
        self.wfile.write(self.get_js().encode())
    
    def get_index_html(self):
        return '''<!DOCTYPE html><html lang="ru"><head>
            <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>BigAko - Главная</title><link rel="stylesheet" href="/style.css">
        </head><body><div class="container">
            <header class="header"><h1>BigAko</h1><p>Современный веб-мессенджер</p></header>
            <main class="main-content"><div class="hero">
                <h2>Общайтесь свободно</h2><p>Присоединяйтесь к нашему сообществу</p>
                <div class="buttons"><a href="/login" class="btn btn-primary">Войти</a>
                <a href="/register" class="btn btn-secondary">Регистрация</a></div>
            </div></main>
        </div></body></html>'''
    
    def get_login_html(self):
        return '''<!DOCTYPE html><html lang="ru"><head>
            <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>BigAko - Вход</title><link rel="stylesheet" href="/style.css">
        </head><body><div class="container"><div class="auth-container">
            <div class="auth-card"><h2>Вход в BigAko</h2>
            <form id="loginForm" class="auth-form"><div class="form-group">
                <input type="text" id="username" name="username" placeholder="Имя пользователя" required>
            </div><div class="form-group">
                <input type="password" id="password" name="password" placeholder="Пароль" required>
            </div><button type="submit" class="btn btn-primary">Войти</button></form>
            <p>Нет аккаунта? <a href="/register">Зарегистрироваться</a></p>
            <div id="error" class="error-message"></div></div>
        </div></div><script src="/script.js"></script></body></html>'''
    
    def get_register_html(self):
        return '''<!DOCTYPE html><html lang="ru"><head>
            <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>BigAko - Регистрация</title><link rel="stylesheet" href="/style.css">
        </head><body><div class="container"><div class="auth-container">
            <div class="auth-card"><h2>Регистрация в BigAko</h2>
            <form id="registerForm" class="auth-form"><div class="form-group">
                <input type="text" id="username" name="username" placeholder="Имя пользователя" required>
            </div><div class="form-group">
                <input type="password" id="password" name="password" placeholder="Пароль" required>
            </div><button type="submit" class="btn btn-primary">Зарегистрироваться</button></form>
            <p>Уже есть аккаунт? <a href="/login">Войти</a></p>
            <div id="error" class="error-message"></div></div>
        </div></div><script src="/script.js"></script></body></html>'''
    
    def get_messenger_html(self):
        return '''<!DOCTYPE html><html lang="ru"><head>
            <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>BigAko - Мессенджер</title><link rel="stylesheet" href="/style.css">
        </head><body><div class="container">
            <header class="header"><h1>BigAko Messenger</h1>
            <div class="user-info"><span id="usernameDisplay"></span>
            <button id="logoutBtn" class="btn btn-secondary">Выйти</button></div></header>
            
            <main class="messenger-container"><div class="messages-container" id="messagesContainer">
                <div class="messages" id="messages"></div></div>
                
                <div class="message-input"><form id="messageForm" class="message-form">
                    <input type="text" id="messageInput" placeholder="Введите сообщение..." required>
                    <button type="button" id="fileBtn" class="btn btn-file">📎</button>
                    <input type="file" id="fileInput" style="display: none" accept="*/*">
                    <button type="submit" class="btn btn-primary">Отправить</button>
                </form><div id="fileInfo" class="file-info"></div></div>
            </main>
        </div><script src="/script.js"></script></body></html>'''
    
    def get_css(self):
        return '''*{margin:0;padding:0;box-sizing:border-box}body{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;
        background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);min-height:100vh;color:#333}.container{max-width:1200px;
        margin:0 auto;padding:20px}.header{text-align:center;margin-bottom:40px;color:white;display:flex;justify-content:space-between;
        align-items:center}.header h1{font-size:3rem;margin-bottom:10px;text-shadow:2px 2px 4px rgba(0,0,0,0.3)}.user-info{
        display:flex;align-items:center;gap:15px}.main-content{display:flex;justify-content:center;align-items:center;min-height:60vh}
        .hero{text-align:center;color:white}.hero h2{font-size:2.5rem;margin-bottom:20px}.hero p{font-size:1.2rem;margin-bottom:30px}
        .buttons{display:flex;gap:20px;justify-content:center}.btn{padding:15px 30px;border:none;border-radius:25px;font-size:1.1rem;
        font-weight:600;text-decoration:none;cursor:pointer;transition:all 0.3s ease;display:inline-block}.btn-primary{
        background:linear-gradient(45deg,#ff6b6b,#ee5a24);color:white}.btn-primary:hover{transform:translateY(-2px);
        box-shadow:0 5px 15px rgba(0,0,0,0.2)}.btn-secondary{background:rgba(255,255,255,0.2);color:white;backdrop-filter:blur(10px)}
        .btn-secondary:hover{background:rgba(255,255,255,0.3);transform:translateY(-2px)}.btn-file{background:#4ecdc4;padding:10px 15px}
        .auth-container{display:flex;justify-content:center;align-items:center;min-height:100vh}.auth-card{background:rgba(255,255,255,0.95);
        padding:40px;border-radius:20px;box-shadow:0 20px 40px rgba(0,0,0,0.1);backdrop-filter:blur(10px);width:100%;max-width:400px}
        .auth-card h2{text-align:center;margin-bottom:30px;color:#333}.auth-form{display:flex;flex-direction:column;gap:20px}
        .form-group{display:flex;flex-direction:column}.form-group input{padding:15px;border:2px solid #ddd;border-radius:10px;
        font-size:1rem;transition:border-color 0.3s ease}.form-group input:focus{outline:none;border-color:#667eea}.error-message{
        color:#e74c3c;text-align:center;margin-top:20px;font-weight:500}.messenger-container{background:rgba(255,255,255,0.95);
        border-radius:20px;overflow:hidden;box-shadow:0 20px 40px rgba(0,0,0,0.1);height:80vh;display:flex;flex-direction:column}
        .messages-container{flex:1;overflow-y:auto;padding:20px}.messages{display:flex;flex-direction:column;gap:15px}.message{
        padding:15px 20px;border-radius:15px;max-width:70%;word-wrap:break-word}.message.own{align-self:flex-end;
        background:linear-gradient(45deg,#667eea,#764ba2);color:white}.message.other{align-self:flex-start;background:#f1f3f4;color:#333}
        .message-header{font-weight:600;margin-bottom:5px;font-size:0.9rem}.message-time{font-size:0.8rem;opacity:0.7;margin-top:5px}
        .message-file{background:#e3f2fd;border:2px dashed #2196f3;padding:10px}.file-link{color:#2196f3;text-decoration:none;font-weight:600}
        .file-link:hover{text-decoration:underline}.file-size{font-size:0.8rem;color:#666}.message-input{padding:20px;background:#f8f9fa;
        border-top:1px solid #e9ecef}.message-form{display:flex;gap:10px;align-items:center}.message-form input[type="text"]{flex:1;
        padding:15px;border:2px solid #ddd;border-radius:25px;font-size:1rem}.message-form input:focus{outline:none;border-color:#667eea}
        .file-info{margin-top:10px;font-size:0.9rem;color:#666}@media (max-width:768px){.container{padding:10px}.header h1{font-size:2rem}
        .buttons{flex-direction:column;align-items:center}.btn{width:200px}.auth-card{padding:30px 20px}.message{max-width:85%}
        .message-form{flex-direction:column}}'''
    
    def get_js(self):
        return '''class BigAkoClient{constructor(){this.currentUser=null;this.selectedFile=null;this.init()}
        init(){this.setupEventListeners();this.checkAuth()}
        setupEventListeners(){const loginForm=document.getElementById('loginForm');
        if(loginForm){loginForm.addEventListener('submit',(e)=>this.handleLogin(e))}
        const registerForm=document.getElementById('registerForm');
        if(registerForm){registerForm.addEventListener('submit',(e)=>this.handleRegister(e))}
        const messageForm=document.getElementById('messageForm');
        if(messageForm){messageForm.addEventListener('submit',(e)=>this.handleMessage(e))}
        const logoutBtn=document.getElementById('logoutBtn');
        if(logoutBtn){logoutBtn.addEventListener('click',()=>this.handleLogout())}
        const fileBtn=document.getElementById('fileBtn');
        const fileInput=document.getElementById('fileInput');
        if(fileBtn&&fileInput){fileBtn.addEventListener('click',()=>fileInput.click());
        fileInput.addEventListener('change',(e)=>this.handleFileSelect(e))}}
        async handleLogin(e){e.preventDefault();const formData=new FormData(e.target);const data={
        username:formData.get('username'),password:formData.get('password')};
        try{const response=await fetch('/api/login',{method:'POST',headers:{
        'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(data)});
        const result=await response.json();if(result.success){window.location.href='/messenger'}
        else{this.showError(result.error)}}catch(error){this.showError('Ошибка соединения')}}
        async handleRegister(e){e.preventDefault();const formData=new FormData(e.target);const data={
        username:formData.get('username'),password:formData.get('password')};
        try{const response=await fetch('/api/register',{method:'POST',headers:{
        'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(data)});
        const result=await response.json();if(result.success){window.location.href='/login'}
        else{this.showError(result.error)}}catch(error){this.showError('Ошибка соединения')}}
        async handleMessage(e){e.preventDefault();const input=document.getElementById('messageInput');
        const message=input.value.trim();const fileInput=document.getElementById('fileInput');
        if(this.selectedFile){await this.uploadFile(message);this.selectedFile=null;
        document.getElementById('fileInfo').textContent='';fileInput.value=''}else if(message){
        try{const response=await fetch('/api/message',{method:'POST',headers:{
        'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({message})});
        const result=await response.json();if(result.success){input.value='';this.loadMessages()}}
        catch(error){console.error('Ошибка отправки сообщения:',error)}}}
        async uploadFile(message){const formData=new FormData();formData.append('file',this.selectedFile);
        if(message){formData.append('message',message)}try{const response=await fetch('/api/message',{
        method:'POST',body:formData});const result=await response.json();if(result.success){
        this.loadMessages()}}catch(error){console.error('Ошибка загрузки файла:',error)}}
        handleFileSelect(e){const file=e.target.files[0];if(file){if(file.size>50*1024*1024){
        this.showError('Файл слишком большой (макс. 50MB)');return}this.selectedFile=file;
        document.getElementById('fileInfo').textContent=`Файл: ${file.name} (${this.formatFileSize(file.size)})`}}
        formatFileSize(bytes){if(bytes===0)return'0 Bytes';const k=1024;const sizes=['Bytes','KB','MB','GB'];
        const i=Math.floor(Math.log(bytes)/Math.log(k));return parseFloat((bytes/Math.pow(k,i)).toFixed(2))+' '+sizes[i]}
        async handleLogout(){try{await fetch('/api/logout',{method:'POST'});window.location.href='/'}
        catch(error){console.error('Ошибка выхода:',error)}}
        async loadMessages(){try{const response=await fetch('/api/messages');const data=await response.json();
        this.displayMessages(data.messages)}catch(error){console.error('Ошибка загрузки сообщений:',error)}}
        displayMessages(messages){const container=document.getElementById('messages');if(!container)return;
        container.innerHTML=messages.map(msg=>{let content=msg.message_type==='file'?
        `<div class="message-file"><a href="/download/${msg.file_name}" class="file-link" download>📎 ${this.escapeHtml(msg.file_name.split('_',2)[1])}</a>
        <div class="file-size">${this.formatFileSize(msg.file_size)}</div>${msg.message?`<div>${this.escapeHtml(msg.message)}</div>`:''}</div>`:
        `<div class="message-text">${this.escapeHtml(msg.message)}</div>`;
        return `<div class="message ${msg.username===this.currentUser?'own':'other'}">
        <div class="message-header">${this.escapeHtml(msg.username)}</div>${content}
        <div class="message-time">${new Date(msg.timestamp).toLocaleTimeString()}</div></div>`}).join('');
        const messagesContainer=document.getElementById('messagesContainer');if(messagesContainer){
        messagesContainer.scrollTop=messagesContainer.scrollHeight}}checkAuth(){
        if(window.location.pathname==='/messenger'){this.startMessenger()}}
        async startMessenger(){try{const userResponse=await fetch('/api/userinfo');
        if(userResponse.ok){const userData=await userResponse.json();this.currentUser=userData.username;
        document.getElementById('usernameDisplay').textContent=userData.username;}
        await this.loadMessages();setInterval(()=>this.loadMessages(),2000);}catch(error){
        console.error('Ошибка запуска мессенджера:',error);window.location.href='/login'}}
        showError(message){const errorDiv=document.getElementById('error');if(errorDiv){
        errorDiv.textContent=message;setTimeout(()=>{errorDiv.textContent=''},3000)}}
        escapeHtml(text){const div=document.createElement('div');div.textContent=text;return div.innerHTML}}
        document.addEventListener('DOMContentLoaded',()=>{window.bigAkoClient=new BigAkoClient()});'''

def run_server():
    PORT = 8000
    with socketserver.TCPServer(("", PORT), BigAkoHandler) as httpd:
        print(f"BigAko server running on port {PORT}")
        print(f"Open http://localhost:{PORT} in your browser")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped")

if __name__ == "__main__":
    run_server()