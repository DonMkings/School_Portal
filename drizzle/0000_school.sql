CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, name TEXT, password TEXT, role TEXT, class TEXT);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user INTEGER, expires INTEGER);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, owner INTEGER, topic TEXT, subject TEXT, class TEXT, term TEXT, body TEXT, published INTEGER);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS exams(id INTEGER PRIMARY KEY, owner INTEGER, note INTEGER, title TEXT, topic TEXT, subject TEXT, class TEXT, term TEXT, questions TEXT, published INTEGER);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, exam INTEGER, student INTEGER, answers TEXT, marks TEXT, released INTEGER DEFAULT 0, UNIQUE(exam, student));
--> statement-breakpoint
CREATE TABLE login_limits (bucket TEXT PRIMARY KEY, count INTEGER NOT NULL);
