import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GROUPS = ('JSS1','JSS2','JSS3','SS1','SS2','SS3')
TERMS = ('First Term','Second Term','Third Term')
DB = os.getenv('SCHOOL_DB', str(ROOT / 'school.db'))

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000)
    return salt + ':' + digest.hex()

def connect():
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    return db

def initialize():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, name TEXT, password TEXT, role TEXT, class TEXT);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user INTEGER, expires INTEGER);
        CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, owner INTEGER, topic TEXT, subject TEXT, class TEXT, term TEXT, body TEXT, published INTEGER);
        CREATE TABLE IF NOT EXISTS exams(id INTEGER PRIMARY KEY, owner INTEGER, note INTEGER, title TEXT, topic TEXT, subject TEXT, class TEXT, term TEXT, questions TEXT, published INTEGER);
        CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, exam INTEGER, student INTEGER, answers TEXT, marks TEXT, released INTEGER DEFAULT 0, UNIQUE(exam, student));
        """)
        if not db.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
            password = os.environ.get('SCHOOL_PASSWORD', '')
            if len(password) < 12:
                raise SystemExit('Set SCHOOL_PASSWORD to at least 12 characters for first run.')
            db.execute("INSERT INTO users(username,name,password,role,class) VALUES ('admin','School Administrator',?,'admin','')", (password_hash(password),))

class Problem(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message

def require(condition, message='Check the supplied values.', status=400):
    if not condition:
        raise Problem(status, message)

def field(data, key, limit=160):
    value = data.get(key)
    require(isinstance(value,str) and 0 < len(value.strip()) <= limit, f'Enter a valid {key}.')
    return value.strip()

def rows(db, sql, params=()):
    return [dict(row) for row in db.execute(sql, params)]

def owned(db, table, id, user):
    row = db.execute(f'SELECT * FROM {table} WHERE id=?', (id,)).fetchone()
    require(row and (user['role']=='admin' or row['owner']==user['id']), 'Record unavailable.', 404)
    return row

def generate(note, objective, theory):
    sentences = [s.strip(' •-') for s in re.split(r'(?<=[.!?])\s+|\n+', note['body']) if len(s.strip()) >= 15]
    require(len(sentences)>=max(objective,theory), 'Add more complete sentences to the lesson note or request fewer questions.')
    questions = []
    for index, sentence in enumerate(sentences[:objective]):
        words = list(re.finditer(r'\b[a-zA-Z][a-zA-Z-]{3,}\b', sentence))
        require(words, 'Add more written detail to the lesson note.')
        word = max(words, key=lambda item: len(item.group()))
        answer = word.group()
        alternatives = list(dict.fromkeys(w.lower() for w in re.findall(r'\b[A-Za-z]{4,}\b', ' '.join(sentences)) if w.lower()!=answer.lower()))
        distractors = (alternatives + ['none of these'])[:3]
        options = distractors[:]
        position = index % (len(options)+1)
        options.insert(position, answer)
        questions.append(dict(kind='objective', text=f"Complete the statement about {note['topic']}. {sentence[:word.start()]}____{sentence[word.end():]}", options=options, answer=position, marks=1, guide=sentence))
    for index, sentence in enumerate(sentences[:theory]):
        cue = ' '.join(sentence.split()[:min(5, max(2, len(sentence.split())//2))]).rstrip('.,:;')
        questions.append(dict(kind='theory', text=f"Explain the point in the notes on {note['topic']} that begins “{cue}…”.", options=[], answer=None, marks=5, guide=sentence))
    return questions

def validate_questions(questions):
    require(isinstance(questions,list) and 1<=len(questions)<=100, 'Include between 1 and 100 questions.')
    for question in questions:
        require(isinstance(question,dict))
        field(question,'text',2000)
        field(question,'guide',4000)
        marks = question.get('marks')
        require(type(marks) is int and 1<=marks<=100, 'Each question needs 1 to 100 marks.')
        require(question.get('kind') in ('objective','theory'))
        if question['kind']=='objective':
            options, answer = question.get('options'), question.get('answer')
            require(isinstance(options,list) and 2<=len(options)<=8 and all(isinstance(x,str) and 0<len(x.strip())<=240 for x in options), 'Enter 2 to 8 answer options.')
            require(len({option.strip().casefold() for option in options}) == len(options), 'Use distinct answer options.')
            require(type(answer) is int and 0<=answer<len(options), 'Select the correct option.')

class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value, cookie=None):
        raw = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(raw)))
        if cookie:
            self.send_header('Set-Cookie',cookie)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path=='/':
            raw = (ROOT / 'index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        else:
            self.api()

    def do_POST(self):
        self.api()

    def api(self):
        try:
            data = {}
            if self.command=='POST':
                require(self.headers.get_content_type()=='application/json', 'Expected JSON.', 415)
                length = int(self.headers.get('Content-Length','0'))
                require(0<length<=750000, 'Request is too large.', 413)
                data = json.loads(self.rfile.read(length))
                require(isinstance(data,dict))
            with connect() as db:
                if self.command=='POST':
                    db.execute('BEGIN IMMEDIATE')
                result, cookie = self.dispatch(db,data)
            self.reply(200,result,cookie)
        except Problem as error:
            self.reply(error.status,dict(error=error.message))
        except (ValueError, TypeError, KeyError, sqlite3.InterfaceError, sqlite3.ProgrammingError):
            self.reply(400,dict(error='Check the supplied values.'))
        except sqlite3.IntegrityError:
            self.reply(409,dict(error='That username or exam submission already exists.'))

    def dispatch(self, db, data):
        path = self.path
        secure = '; Secure' if os.getenv('SCHOOL_SECURE_COOKIE')=='1' else ''
        cookie_flags = '; Path=/; HttpOnly; SameSite=Strict'+secure
        if path=='/api/login' and self.command=='POST':
            name, password = field(data,'username').lower(), field(data,'password',256)
            user = db.execute('SELECT * FROM users WHERE username=?',(name,)).fetchone()
            stored = user['password'] if user else '0'*32+':'+ '0'*64
            valid = hmac.compare_digest(password_hash(password,stored.split(':')[0]),stored)
            require(user and valid,'Username or password is incorrect.',401)
            token = secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires<=?', (int(time.time()),))
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],int(time.time())+43200))
            return {}, 'school='+token+cookie_flags+'; Max-Age=43200'
        cookies = SimpleCookie(self.headers.get('Cookie',''))
        token = hashlib.sha256(cookies['school'].value.encode()).hexdigest() if 'school' in cookies else ''
        user = db.execute('SELECT users.* FROM sessions JOIN users ON users.id=sessions.user WHERE token=? AND expires>?',(token,int(time.time()))).fetchone()
        require(user,'Sign in to continue.',401)
        role, uid = user['role'], user['id']
        if path=='/api/state' and self.command=='GET':
            return self.state(db,user),None
        require(self.command=='POST','Page unavailable.',404)
        if path=='/api/logout':
            db.execute('DELETE FROM sessions WHERE token=?',(token,))
            return {},'school='+cookie_flags+'; Max-Age=0'
        if path=='/api/password':
            old, new = field(data,'current',256), field(data,'password',256)
            require(len(new)>=12,'Use at least 12 characters.')
            require(hmac.compare_digest(password_hash(old,user['password'].split(':')[0]),user['password']),'Current password is incorrect.',403)
            db.execute('UPDATE users SET password=? WHERE id=?',(password_hash(new),uid))
            db.execute('DELETE FROM sessions WHERE user=? AND token<>?',(uid,token))
            return {},None
        if path=='/api/submit':
            require(role=='student','Student account required.',403)
            exam = db.execute('SELECT * FROM exams WHERE id=? AND class=? AND published=1',(data.get('exam'),user['class'])).fetchone()
            require(exam,'Exam unavailable.',404)
            questions, answers = json.loads(exam['questions']),data.get('answers')
            require(isinstance(answers,list) and len(questions)==len(answers),'Submit an answer entry for each question.')
            marks = []
            for q,a in zip(questions,answers):
                if q['kind']=='objective':
                    require(a is None or type(a) is int and 0<=a<len(q['options']))
                    marks.append(q['marks'] if a==q['answer'] else 0)
                else:
                    require(isinstance(a,str) and len(a)<=12000)
                    marks.append(None)
            cur = db.execute('INSERT INTO attempts(exam,student,answers,marks) VALUES(?,?,?,?)',(exam['id'],uid,json.dumps(answers),json.dumps(marks)))
            return dict(id=cur.lastrowid),None
        require(role!='student','Staff access required.',403)
        if path=='/api/account':
            role_to_create, group = data.get('role'),data.get('group','')
            require(role_to_create=='student' or role=='admin' and role_to_create=='teacher','You cannot create this account type.',403)
            require(role_to_create=='teacher' or group in GROUPS,'Choose a class.')
            name, username, password = field(data,'name'),field(data,'username',50).lower(),field(data,'password',256)
            require(re.fullmatch(r'[a-z0-9._-]{3,50}',username),'Use at least three letters, digits, dots, underscores or hyphens in the username.')
            require(len(password)>=12,'Use at least 12 characters for passwords.')
            db.execute('INSERT INTO users(username,name,password,role,class) VALUES(?,?,?,?,?)',(username,name,password_hash(password),role_to_create,group if role_to_create=='student' else ''))
            return {},None
        if path=='/api/note':
            group,term = data.get('group'),data.get('term')
            require(group in GROUPS and term in TERMS,'Select a class and term.')
            values = (field(data,'topic'),field(data,'subject'),group,term,field(data,'body',48000),int(data.get('published') is True))
            if data.get('id'):
                record = owned(db,'notes',data['id'],user)
                if (group,term) != (record['class'],record['term']):
                    require(not db.execute('SELECT 1 FROM exams WHERE note=?',(record['id'],)).fetchone(),'An exam already uses this note. Create a new note to change class or term.')
                db.execute('UPDATE notes SET topic=?,subject=?,class=?,term=?,body=?,published=? WHERE id=?',values+(record['id'],))
                return dict(id=record['id']),None
            cur = db.execute('INSERT INTO notes(topic,subject,class,term,body,published,owner) VALUES(?,?,?,?,?,?,?)',values+(uid,))
            return dict(id=cur.lastrowid),None
        if path=='/api/generate':
            note = owned(db,'notes',data.get('note'),user)
            objective,theory=data.get('objective'),data.get('theory')
            require(all(type(n) is int and 0<=n<=30 for n in (objective,theory)) and objective+theory>0,'Choose 0 to 30 questions of each type and at least one in total.')
            return dict(questions=generate(note,objective,theory)),None
        if path=='/api/exam':
            questions = data.get('questions')
            validate_questions(questions)
            published = int(data.get('published') is True)
            title = field(data,'title')
            if data.get('id'):
                exam = owned(db,'exams',data['id'],user)
                require(not exam['published'] and not db.execute('SELECT 1 FROM attempts WHERE exam=?',(exam['id'],)).fetchone(),'Published exams are locked.',409)
                db.execute('UPDATE exams SET title=?,questions=?,published=? WHERE id=?',(title,json.dumps(questions),published,exam['id']))
                return dict(id=exam['id']),None
            note = owned(db,'notes',data.get('note'),user)
            cur = db.execute('INSERT INTO exams(owner,note,title,topic,subject,class,term,questions,published) VALUES(?,?,?,?,?,?,?,?,?)',(uid,note['id'],title,note['topic'],note['subject'],note['class'],note['term'],json.dumps(questions),published))
            return dict(id=cur.lastrowid),None
        if path=='/api/grade':
            attempt = db.execute('SELECT * FROM attempts WHERE id=?',(data.get('attempt'),)).fetchone()
            require(attempt,'Submission unavailable.',404)
            exam = owned(db,'exams',attempt['exam'],user)
            questions, marks, provided = json.loads(exam['questions']),json.loads(attempt['marks']),data.get('marks')
            require(isinstance(provided,list) and len(provided)==len(marks))
            for index,q in enumerate(questions):
                if q['kind']=='theory':
                    mark = provided[index]
                    require(type(mark) is int and 0<=mark<=q['marks'],'Enter valid marks for every theory answer.')
                    marks[index]=mark
            db.execute('UPDATE attempts SET marks=?,released=1 WHERE id=?',(json.dumps(marks),attempt['id']))
            return {},None
        raise Problem(404,'Page unavailable.')

    def state(self, db, user):
        role, uid = user['role'], user['id']
        if role=='student':
            where, params = ' WHERE class=? AND published=1',(user['class'],)
            attempt_where, attempt_params = ' WHERE attempts.student=?',(uid,)
        elif role=='teacher':
            where, params = ' WHERE owner=?',(uid,)
            attempt_where, attempt_params = ' WHERE exams.owner=?',(uid,)
        else:
            where,params,attempt_where,attempt_params='',(),' ',()
        notes = rows(db,'SELECT * FROM notes'+where+' ORDER BY id DESC',params)
        exams = rows(db,'SELECT * FROM exams'+where+' ORDER BY id DESC',params)
        attempts = rows(db,'SELECT attempts.*, users.name, exams.title, exams.questions FROM attempts JOIN users ON users.id=attempts.student JOIN exams ON exams.id=attempts.exam'+attempt_where+' ORDER BY attempts.id DESC',attempt_params)
        for exam in exams:
            exam['questions']=json.loads(exam['questions'])
            if role=='student':
                exam['questions']=[{key:q[key] for key in ('kind','text','options','marks')} for q in exam['questions']]
        for attempt in attempts:
            questions = json.loads(attempt.pop('questions'))
            marks = json.loads(attempt['marks'])
            attempt['total']=sum(q['marks'] for q in questions)
            if attempt['released'] or role!='student':
                attempt['score']=sum(m or 0 for m in marks)
            if role=='student':
                attempt.pop('marks')
                attempt.pop('answers')
            else:
                attempt['marks']=marks
                attempt['answers']=json.loads(attempt['answers'])
        accounts = [] if role=='student' else rows(db,'SELECT id, username, name, role, class FROM users ORDER BY id DESC')
        return dict(user={k:user[k] for k in ('id','username','name','role','class')}, notes=notes, exams=exams, attempts=attempts, accounts=accounts)

if __name__=='__main__':
    initialize()
    host, port = os.getenv('SCHOOL_HOST','127.0.0.1'), int(os.getenv('PORT','8000'))
    print(f'Classroom NG is listening on http://{host}:{port}',flush=True)
    ThreadingHTTPServer((host,port),Handler).serve_forever()
