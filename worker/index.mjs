const groups=['JSS1','JSS2','JSS3','SS1','SS2','SS3'], terms=['First Term','Second Term','Third Term'];
const encoder=new TextEncoder();
const hex=bytes=>Array.from(new Uint8Array(bytes),b=>b.toString(16).padStart(2,'0')).join('');
const random=()=>hex(crypto.getRandomValues(new Uint8Array(32)));
const hash=async value=>hex(await crypto.subtle.digest('SHA-256',encoder.encode(value)));
async function passwordHash(password,salt=random()){
  const key=await crypto.subtle.importKey('raw',encoder.encode(password),'PBKDF2',false,['deriveBits']);
  const digest=await crypto.subtle.deriveBits({name:'PBKDF2',hash:'SHA-256',salt:Uint8Array.from(salt.match(/../g),v=>parseInt(v,16)),iterations:600000},key,256);
  return salt+':'+hex(digest);
}
function equal(left,right){
  let diff=left.length^right.length;
  for(let i=0;i<left.length;i++) diff|=left.charCodeAt(i)^right.charCodeAt(i);
  return diff===0;
}
class Problem extends Error{constructor(status,message){super(message);this.status=status}}
function requireValue(ok,message='Check the supplied values.',status=400){if(!ok)throw new Problem(status,message)}
function field(data,key,max=160){
  const value=data[key];
  requireValue(typeof value==='string'&&value.trim().length>0&&value.trim().length<=max,'Enter a valid '+key+'.');
  return value.trim();
}
const query=(db,sql,...values)=>values.length?db.prepare(sql).bind(...values):db.prepare(sql);
const first=(db,sql,...values)=>query(db,sql,...values).first();
const run=(db,sql,...values)=>query(db,sql,...values).run();
const all=async(db,sql,...values)=>(await query(db,sql,...values).all()).results;
async function owned(db,table,id,user){
  const row=await first(db,'SELECT * FROM '+table+' WHERE id=?',id??null);
  requireValue(row&&(user.role==='admin'||row.owner===user.id),'Record unavailable.',404);
  return row;
}
function generate(note,objective,theory){
  const sentences=note.body.split(/(?<=[.!?])\s+|\n+/).map(s=>s.trim()).filter(s=>s.length>=15);
  requireValue(sentences.length>=Math.max(objective,theory),'Add more complete sentences to the lesson note or request fewer questions.');
  const words=[...new Set(sentences.join(' ').toLowerCase().match(/\b[a-z]{4,}\b/g)||[])];
  const questions=sentences.slice(0,objective).map((sentence,index)=>{
    const tokens=[...sentence.matchAll(/\b[a-zA-Z][a-zA-Z-]{3,}\b/g)].sort((a,b)=>b[0].length-a[0].length);
    requireValue(tokens.length,'Add more written detail to the lesson note.');
    const word=tokens[0], options=[...words.filter(w=>w!==word[0].toLowerCase()),'none of these'].slice(0,3);
    const answer=index%(options.length+1);
    options.splice(answer,0,word[0]);
    return {kind:'objective',text:'Complete the statement about '+note.topic+'. '+sentence.slice(0,word.index)+'____'+sentence.slice(word.index+word[0].length),options,answer,marks:1,guide:sentence};
  });
  return questions.concat(sentences.slice(0,theory).map(sentence=>({kind:'theory',text:'Explain the point about '+note.topic+' that begins “'+sentence.split(/\s+/).slice(0,4).join(' ')+'…”.',options:[],answer:null,marks:5,guide:sentence})));
}
function validated(questions){
  requireValue(Array.isArray(questions)&&questions.length>=1&&questions.length<=100,'Include between 1 and 100 questions.');
  return questions.map(q=>{
    requireValue(q&&['objective','theory'].includes(q.kind)&&Number.isInteger(q.marks)&&q.marks>=1&&q.marks<=100);
    const result={kind:q.kind,marks:q.marks,text:field(q,'text',2000),guide:field(q,'guide',4000),options:[],answer:null};
    if(q.kind==='objective'){
      requireValue(Array.isArray(q.options)&&q.options.length>=2&&q.options.length<=8&&q.options.every(x=>typeof x==='string'&&x.trim()&&x.length<=240),'Enter 2 to 8 answer options.');
      requireValue(new Set(q.options.map(x=>x.trim().toLowerCase())).size===q.options.length,'Use distinct answer options.');
      requireValue(Number.isInteger(q.answer)&&q.answer>=0&&q.answer<q.options.length,'Select the correct option.');
      result.options=q.options.map(x=>x.trim());result.answer=q.answer;
    }
    return result;
  });
}
const json=(data,status=200,headers={})=>Response.json(data,{status,headers:{'Cache-Control':'no-store',...headers}});
const now=()=>Math.floor(Date.now()/1000);
const cookie='; Path=/; HttpOnly; SameSite=Strict; Secure';
async function state(db,user){
  const student=user.role==='student';
  const scope=student?[' WHERE class=? AND published=1',user.class]:user.role==='teacher'?[' WHERE owner=?',user.id]:[''];
  const attemptScope=student?[' WHERE attempts.student=?',user.id]:user.role==='teacher'?[' WHERE exams.owner=?',user.id]:[''];
  const [notes,exams,attempts,accounts]=await Promise.all([
    all(db,'SELECT * FROM notes'+scope[0]+' ORDER BY id DESC',...scope.slice(1)),
    all(db,'SELECT * FROM exams'+scope[0]+' ORDER BY id DESC',...scope.slice(1)),
    all(db,'SELECT attempts.*, users.name, exams.title, exams.questions FROM attempts JOIN users ON users.id=attempts.student JOIN exams ON exams.id=attempts.exam'+attemptScope[0]+' ORDER BY attempts.id DESC',...attemptScope.slice(1)),
    student?[]:all(db,'SELECT id,username,name,role,class FROM users ORDER BY id DESC')
  ]);
  for(const exam of exams){
    const questions=JSON.parse(exam.questions);
    exam.questions=student?questions.map(({kind,text,options,marks})=>({kind,text,options,marks})):questions;
  }
  for(const attempt of attempts){
    attempt.total=JSON.parse(attempt.questions).reduce((sum,q)=>sum+q.marks,0);
    delete attempt.questions;
    const marks=JSON.parse(attempt.marks);
    if(attempt.released||!student)attempt.score=marks.reduce((sum,m)=>sum+(m||0),0);
    if(student){delete attempt.marks;delete attempt.answers}
    else{attempt.marks=marks;attempt.answers=JSON.parse(attempt.answers)}
  }
  const {id,username,name,role,class:group}=user;
  return {user:{id,username,name,role,class:group},notes,exams,attempts,accounts};
}
async function route(request,env){
  const path=new URL(request.url).pathname, db=env.DB;
  if(path==='/'&&request.method==='GET')return new Response(PAGE,{headers:{'Content-Type':'text/html; charset=utf-8','X-Content-Type-Options':'nosniff'}});
  if(!path.startsWith('/api/'))throw new Problem(404,'Page unavailable.');
  let data={};
  if(request.method==='POST'){
    const origin=request.headers.get('origin');
    requireValue(!origin||origin===new URL(request.url).origin,'Invalid origin.',403);
    requireValue(request.headers.get('content-type')?.split(';')[0]==='application/json','Expected JSON.',415);
    const body=await request.text();
    requireValue(body.length<=750000,'Request is too large.',413);
    data=JSON.parse(body);
    requireValue(data&&typeof data==='object'&&!Array.isArray(data));
  }
  if(path==='/api/login'&&request.method==='POST'){
    const name=field(data,'username').toLowerCase(), password=field(data,'password',256);
    const clock=Math.floor(now()/900);
    const limiter=clock+':'+await hash(request.headers.get('CF-Connecting-IP')||'unknown');
    const limit=await first(db,'INSERT INTO login_limits VALUES(?,1) ON CONFLICT(bucket) DO UPDATE SET count=count+1 RETURNING count',limiter);
    requireValue(limit.count<=60,'Too many sign-in attempts. Try again shortly.',429);
    if(limit.count===1)await run(db,'DELETE FROM login_limits WHERE CAST(bucket AS INTEGER)<?',clock-2);
    let user=await first(db,'SELECT * FROM users WHERE username=?',name);
    if(!user&&name==='admin'&&typeof env.SCHOOL_PASSWORD==='string'&&env.SCHOOL_PASSWORD.length>=12&&equal(password,env.SCHOOL_PASSWORD)){
      await run(db,"INSERT OR IGNORE INTO users(username,name,password,role,class) VALUES ('admin','School Administrator',?,'admin','')",await passwordHash(password));
      user=await first(db,"SELECT * FROM users WHERE username='admin'");
    }
    const stored=user?.password||'0'.repeat(64)+':'+ '0'.repeat(64);
    requireValue(equal(await passwordHash(password,stored.split(':')[0]),stored)&&user,'Username or password is incorrect.',401);
    const token=random();
    await run(db,'DELETE FROM sessions WHERE expires<=?',now());
    await run(db,'INSERT INTO sessions VALUES(?,?,?)',await hash(token),user.id,now()+43200);
    return json({},200,{'Set-Cookie':'school='+token+cookie+'; Max-Age=43200'});
  }
  const session=request.headers.get('cookie')?.match(/(?:^|; )school=([a-f0-9]{64})(?:;|$)/)?.[1];
  const token=session?await hash(session):'';
  const user=await first(db,'SELECT users.* FROM sessions JOIN users ON users.id=sessions.user WHERE token=? AND expires>?',token,now());
  requireValue(user,'Sign in to continue.',401);
  if(path==='/api/state'&&request.method==='GET')return json(await state(db,user));
  requireValue(request.method==='POST','Page unavailable.',404);
  if(path==='/api/logout'){
    await run(db,'DELETE FROM sessions WHERE token=?',token);
    return json({},200,{'Set-Cookie':'school='+cookie+'; Max-Age=0'});
  }
  if(path==='/api/password'){
    const current=field(data,'current',256),next=field(data,'password',256);
    requireValue(next.length>=12,'Use at least 12 characters.');
    requireValue(equal(await passwordHash(current,user.password.split(':')[0]),user.password),'Current password is incorrect.',403);
    await db.batch([query(db,'UPDATE users SET password=? WHERE id=?',await passwordHash(next),user.id),query(db,'DELETE FROM sessions WHERE user=? AND token<>?',user.id,token)]);
    return json({});
  }
  if(path==='/api/submit'){
    requireValue(user.role==='student','Student account required.',403);
    const exam=await first(db,'SELECT * FROM exams WHERE id=? AND class=? AND published=1',data.exam??null,user.class);
    requireValue(exam,'Exam unavailable.',404);
    const questions=JSON.parse(exam.questions),answers=data.answers;
    requireValue(Array.isArray(answers)&&answers.length===questions.length,'Submit an answer entry for each question.');
    const marks=questions.map((q,i)=>{
      const a=answers[i];
      if(q.kind==='theory'){requireValue(typeof a==='string'&&a.length<=12000);return null}
      requireValue(a===null||(Number.isInteger(a)&&a>=0&&a<q.options.length));
      return a===q.answer?q.marks:0;
    });
    const created=await first(db,'INSERT INTO attempts(exam,student,answers,marks) VALUES(?,?,?,?) ON CONFLICT(exam,student) DO NOTHING RETURNING id',exam.id,user.id,JSON.stringify(answers),JSON.stringify(marks));
    requireValue(created,'You have already submitted this exam.',409);
    return json(created);
  }
  requireValue(user.role!=='student','Staff access required.',403);
  if(path==='/api/account'){
    const {role,group}=data, name=field(data,'name'),username=field(data,'username',50).toLowerCase(),password=field(data,'password',256);
    requireValue(role==='student'||(role==='teacher'&&user.role==='admin'),'You cannot create this account type.',403);
    requireValue(role==='teacher'||groups.includes(group),'Choose a class.');
    requireValue(/^[a-z0-9._-]{3,50}$/.test(username)&&password.length>=12,'Use a valid username and a password of at least 12 characters.');
    const created=await first(db,'INSERT INTO users(username,name,password,role,class) VALUES(?,?,?,?,?) ON CONFLICT(username) DO NOTHING RETURNING id',username,name,await passwordHash(password),role,role==='student'?group:'');
    requireValue(created,'That username already exists.',409);
    return json({});
  }
  if(path==='/api/note'){
    const {group,term}=data;
    requireValue(groups.includes(group)&&terms.includes(term),'Select a class and term.');
    const values=[field(data,'topic'),field(data,'subject'),group,term,field(data,'body',48000),Number(data.published===true)];
    if(data.id){
      await owned(db,'notes',data.id,user);
      const updated=await first(db,'UPDATE notes SET topic=?,subject=?,class=?,term=?,body=?,published=? WHERE id=? AND ((class=? AND term=?) OR NOT EXISTS (SELECT 1 FROM exams WHERE note=notes.id)) RETURNING id',...values,data.id,group,term);
      requireValue(updated,'An exam already uses this note. Create a new note to change class or term.',409);
      return json(updated);
    }
    return json(await first(db,'INSERT INTO notes(topic,subject,class,term,body,published,owner) VALUES(?,?,?,?,?,?,?) RETURNING id',...values,user.id));
  }
  if(path==='/api/generate'){
    const note=await owned(db,'notes',data.note,user);
    const {objective,theory}=data;
    requireValue([objective,theory].every(n=>Number.isInteger(n)&&n>=0&&n<=30)&&objective+theory>0,'Choose 0 to 30 questions of each type and at least one in total.');
    return json({questions:generate(note,objective,theory)});
  }
  if(path==='/api/exam'){
    const title=field(data,'title'), questions=JSON.stringify(validated(data.questions)),published=Number(data.published===true);
    if(data.id){
      await owned(db,'exams',data.id,user);
      const updated=await first(db,'UPDATE exams SET title=?,questions=?,published=? WHERE id=? AND published=0 RETURNING id',title,questions,published,data.id);
      requireValue(updated,'Published exams are locked.',409);
      return json(updated);
    }
    const note=await owned(db,'notes',data.note,user);
    return json(await first(db,'INSERT INTO exams(owner,note,title,topic,subject,class,term,questions,published) SELECT ?,id,?,topic,subject,class,term,?,? FROM notes WHERE id=? RETURNING id',user.id,title,questions,published,note.id));
  }
  if(path==='/api/grade'){
    const attempt=await first(db,'SELECT * FROM attempts WHERE id=?',data.attempt??null);
    requireValue(attempt,'Submission unavailable.',404);
    const exam=await owned(db,'exams',attempt.exam,user),marks=JSON.parse(attempt.marks),questions=JSON.parse(exam.questions);
    requireValue(Array.isArray(data.marks)&&data.marks.length===marks.length);
    questions.forEach((q,i)=>{
      if(q.kind==='theory'){
        const m=data.marks[i];
        requireValue(Number.isInteger(m)&&m>=0&&m<=q.marks,'Enter valid marks for every theory answer.');
        marks[i]=m;
      }
    });
    await run(db,'UPDATE attempts SET marks=?,released=1 WHERE id=?',JSON.stringify(marks),attempt.id);
    return json({});
  }
  throw new Problem(404,'Page unavailable.');
}
export default {
  async fetch(request,env){
    try{return await route(request,env)}
    catch(error){
      if(error instanceof Problem)return json({error:error.message},error.status);
      if(error instanceof SyntaxError||error instanceof TypeError)return json({error:'Check the supplied values.'},400);
      console.error(error.message);
      return json({error:'Could not complete the request.'},500);
    }
  }
};
