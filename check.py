import os, subprocess, sys, tempfile, time
from urllib.request import build_opener, HTTPCookieProcessor, Request
from urllib.error import HTTPError
import json

def client():
    browser = build_opener(HTTPCookieProcessor())
    def call(path, data=None, expected=200):
        req = Request('http://127.0.0.1:8759/api/'+path,
                      None if data is None else json.dumps(data).encode(),
                      {'Content-Type':'application/json'})
        try:
            with browser.open(req) as response:
                assert response.status == expected
                return json.load(response)
        except HTTPError as e:
            assert e.code == expected, (e.code, e.read())
    return call

with tempfile.TemporaryDirectory() as directory:
    app = subprocess.Popen([sys.executable, 'app.py'], env=dict(os.environ, SCHOOL_DB=directory+'/db', SCHOOL_PASSWORD='Teacher-Example-88', PORT='8759'))
    try:
        time.sleep(.45)
        teacher, student, outsider = client(), client(), client()
        student('state', expected=401)
        teacher('login', dict(username='admin', password='Teacher-Example-88'))
        for browser, name, group in [(student,'ada','JSS1'),(outsider,'tobi','SS3')]:
            teacher('account', dict(name=name, username=name, password='Student-Example-88', group=group, role='student'))
            browser('login', dict(username=name, password='Student-Example-88'))
        note = teacher('note', dict(topic='Fractions', subject='Mathematics', group='JSS1', term='First Term', body='The numerator shows the number of selected parts. The denominator shows the total number of equal parts.', published=True))
        assert len(student('state')['notes'])==1
        assert outsider('state')['notes']==[]
        student('note', {}, expected=403)
        questions = teacher('generate', dict(note=note['id'], objective=1, theory=1))['questions']
        assert len(questions)==2
        exam = teacher('exam', dict(title='Fractions assessment', note=note['id'], questions=questions, published=True))
        assert outsider('state')['exams']==[]
        visible = student('state')['exams'][0]
        assert all('answer' not in q for q in visible['questions'])
        outsider('submit', dict(exam=exam['id'], answers=[]), expected=404)
        payload = dict(exam=exam['id'], answers=[questions[0]['answer'],'It represents the selected parts.'])
        result = student('submit', payload)
        student('submit', payload, expected=409)
        assert 'score' not in student('state')['attempts'][0]
        teacher('grade', dict(attempt=result['id'], marks=[None,2]))
        assert student('state')['attempts'][0]['score']==3
        print('Verified teacher setup, note visibility, exam drafting, answer-key protection, submission and grading.')
    finally:
        app.terminate()
        app.wait()
