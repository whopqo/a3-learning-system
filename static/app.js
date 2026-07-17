var PAGES=[{id:'chat',t:'对话'},{id:'profile',t:'画像'},{id:'path',t:'路径'},{id:'resources',t:'资源库'},{id:'knowledge',t:'知识库'},{id:'records',t:'记录'},{id:'settings',t:'设置'}];
document.getElementById('nav-tabs').innerHTML=PAGES.map(function(p,i){return'<button class="'+(i===0?'on':'')+'" data-p="'+p.id+'">'+p.t+'</button>';}).join('');

var S={sid:'u'+Date.now(),profile:null,resources:null,path:null,recs:[],allRes:[],quizResults:{},streaming:false,resFilter:'all',chatModel:null,skills:[]};var _abortCtrl=null;
(function(){try{var sid=localStorage.getItem('a3_sid');if(sid)S.sid=sid;else localStorage.setItem('a3_sid',S.sid);}catch(e){}
try{var saved=localStorage.getItem('a3_recs');if(saved)S.recs=JSON.parse(saved);}catch(e){}
try{var qr=localStorage.getItem('a3_quiz');if(qr)S.quizResults=JSON.parse(qr);}catch(e){}
try{var cm=localStorage.getItem('a3_model');if(cm)S.chatModel=JSON.parse(cm);}catch(e){}
try{var sk=localStorage.getItem('a3_skills');if(sk)S.skills=JSON.parse(sk);}catch(e){}})();
var M=document.getElementById('modal'),PD=[],KD=[];

(function init(){
  document.querySelectorAll('nav .tabs button').forEach(function(b){b.onclick=function(){go(b.dataset.p);};});
  fetch('/api/health').then(function(r){return r.json()}).then(function(d){document.getElementById('sdot').className='dot'+(d.kb_ready?'':' off');}).catch(function(){});
  document.getElementById('chat-scroll').innerHTML='<div class="msg assistant"><div class="av">AI</div><div class="bubble"><h3>同学你好！</h3><p>我是你的AI学习助手，专门帮你学<strong>机器学习</strong>。</p><p>先跟我说说你的情况吧～也可以点下面的按钮<strong>快速开始</strong>：</p><div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px"><button class="btn-sm" onclick="quickSend(\'我是零基础小白，完全没学过机器学习，Python和数学都比较薄弱，目标是系统入门，平时喜欢看视频和生动比喻的讲解，每周能学5小时左右，暂时说不上来哪里薄弱\')">🌱 我是零基础</button><button class="btn-sm" onclick="quickSend(\'我学过一点机器学习，会写Python代码，数学一般，目标是考研，喜欢动手写代码学习，每周能学10小时，觉得SVM和神经网络比较难，讲解希望通俗易懂\')">📗 有一点基础</button><button class="btn-sm" onclick="quickSend(\'我是计算机科班出身，机器学习基础不错，Python很熟练，数学比较扎实，目标是找算法岗位工作，喜欢看书推导公式，每周能学15小时，集成学习和概率图模型掌握得还不够，讲解严谨学术一些\')">🚀 想进阶提升</button></div></div></div>';
  loadKBDocs();loadModelSel();loadSkills();restoreSession();loadHistory();
  go(location.hash.slice(1)||'chat');
})();

function go(p){
  if(window.SET&&SET.timer){clearInterval(SET.timer);SET.timer=null;}
  document.querySelectorAll('nav .tabs button').forEach(function(b){b.classList.toggle('on',b.dataset.p===p);});
  document.querySelectorAll('.page').forEach(function(pg){pg.classList.toggle('show',pg.id==='page-'+p);});
  if(p==='profile')renderProfile();else if(p==='path')renderPath();else if(p==='resources')renderResources();
  else if(p==='knowledge')renderKnowledge();else if(p==='records')renderRecords();
  else if(p==='settings')renderSettings();
  else{var cs=document.getElementById('chat-scroll');if(cs)cs.scrollTop=cs.scrollHeight;loadModelSel();}
}

function jsq(s){return esc(String(s||'').replace(/['"\\]/g,''));}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function md(t){if(!t)return'';var mmCodes=[],preCodes=[];var h=esc(t);
h=h.replace(/^### (.+)$/gm,'<h3>$1</h3>');h=h.replace(/^## (.+)$/gm,'<h2>$1</h2>');h=h.replace(/^# (.+)$/gm,'<h1>$1</h1>');h=h.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');h=h.replace(/\*(.+?)\*/g,'<em>$1</em>');
// mermaid代码先摘出来存好，占位符顶着——不然后面的换行转<br>会把图表代码搅烂
h=h.replace(/```mermaid\n?([\s\S]*?)```/g,function(_,code){mmCodes.push(code);return'@@MM'+(mmCodes.length-1)+'@@';});
h=h.replace(/```(\w*)\n?([\s\S]*?)```/g,function(_,lang,code){preCodes.push(code);return'@@PP'+(preCodes.length-1)+'@@';});h=h.replace(/`([^`]+)`/g,'<code>$1</code>');h=h.replace(/^- (.+)$/gm,'<li>$1</li>');h=h.replace(/((?:<li>.*<\/li>\n?)+)/g,'<ul>$1</ul>');h=h.replace(/^\d+\. (.+)$/gm,'<li>$1</li>');h=h.replace(/^>(.+)$/gm,'<blockquote>$1</blockquote>');h=h.replace(/\n\n/g,'</p><p>');h=h.replace(/\n/g,'<br>');
preCodes.forEach(function(code,i){h=h.replace('@@PP'+i+'@@','<pre><code>'+code+'</code></pre>');});
// 占位符换回图表容器，代码用textContent塞进去保住换行
mmCodes.forEach(function(code,i){var id='mm-'+Date.now()+'-'+i+'-'+Math.floor(Math.random()*1e5);
  h=h.replace('@@MM'+i+'@@','<div class="mermaid" id="'+id+'"></div>');
  setTimeout(function(){try{var el=document.getElementById(id);if(!el)return;
    var ta=document.createElement('textarea');ta.innerHTML=code;el.textContent=ta.value;
    mermaid.run({nodes:[el]}).catch(function(){el.innerHTML='<span style="color:var(--muted);font-size:.78rem">（图解渲染失败，不影响正文内容）</span>';});
  }catch(e){}},60);});
return'<p>'+h+'</p>';}
function mdKb(t){if(!t)return'';var h=esc(t);h=h.replace(/^### (.+)$/gm,'<h3 style=\"margin-top:16px\">$1</h3>');h=h.replace(/^## (.+)$/gm,'<h2 style=\"margin-top:20px\">$1</h2>');h=h.replace(/^# (.+)$/gm,'<h1>$1</h1>');h=h.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');var paras=h.split(/\n{2,}/);return'<div class=\"kb-text\">'+paras.map(function(p){return'<p class=\"kb-p\" style=\"margin-bottom:8px;line-height:1.9\">'+p.replace(/\n/g,'<br>')+'</p>';}).join('')+'</div>';}

function addMsg(role,html){var cs=document.getElementById('chat-scroll');var d=document.createElement('div');d.className='msg '+role;d.innerHTML='<div class="av">'+(role==='user'?'我':'AI')+'</div><div class="bubble">'+html+'</div>';cs.appendChild(d);cs.scrollTop=cs.scrollHeight;}

function stopStream(){if(_abortCtrl){_abortCtrl.abort();_abortCtrl=null;}}
function quickSend(msg){document.getElementById('msg-in').value=msg;send();}

async function send(){
  var inp=document.getElementById('msg-in'),msg=inp.value.trim();
  if(!msg||S.streaming)return;inp.value='';S.streaming=true;document.getElementById('send-btn').disabled=true;document.getElementById('stop-btn').classList.add('show');
  
  var start=Date.now();addMsg('user',esc(msg));
  var cs=document.getElementById('chat-scroll'),d=document.createElement('div');
  d.className='msg assistant';d.innerHTML='<div class="av">AI</div><div class="bubble" id="sB"><div style="display:flex;align-items:center;gap:8px;color:var(--muted);font-size:.82rem;padding:8px 0"><span class="spin"></span> <span id="sB-label">思考中</span> <span class="tick" id="sB-tick">0s</span></div><div class="prog" id="sB-bar" style="display:none"><div class="track"><div class="fill" style="width:0%"></div></div></div></div>';
  cs.appendChild(d);cs.scrollTop=cs.scrollHeight;
  var b=document.getElementById('sB'),tickEl=document.getElementById('sB-tick'),raw='',progLabel=document.getElementById('sB-label');
  var timer=setInterval(function(){if(tickEl)tickEl.textContent=Math.round((Date.now()-start)/1000)+'s';},1000);
  _abortCtrl=new AbortController();
  try{
    var chatBody={message:msg,session_id:S.sid};
    if(S.chatModel&&S.chatModel.service){chatBody.service=S.chatModel.service;chatBody.model=S.chatModel.model;}
    if(S.skills&&S.skills.length)chatBody.skills=S.skills;
    var resp=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(chatBody),signal:_abortCtrl.signal});
    var reader=resp.body.getReader(),decoder=new TextDecoder(),buf='',et='',ed='';
    while(true){var rv=await reader.read();if(rv.done)break;buf+=decoder.decode(rv.value,{stream:true});
      var lines=buf.split('\n');buf=lines.pop()||'';
      for(var i=0;i<lines.length;i++){var l=lines[i];
        if(l.indexOf('event: ')===0)et=l.slice(7).trim();else if(l.indexOf('data: ')===0)ed=l.slice(6);
        else if(l===''){if(et&&ed!==undefined)raw=sse(et,ed,b,raw,start);et='';ed='';}}}
    if(et)raw=sse(et,ed,b,raw,start);
  }catch(e){if(e.name!=='AbortError')b.innerHTML='<span style="color:var(--rust)">网络错误</span>';else b.innerHTML='<span style="color:var(--muted)">已停止生成</span>';clearInterval(timer);S.streaming=false;document.getElementById('send-btn').disabled=false;document.getElementById('stop-btn').classList.remove('show');_abortCtrl=null;b.removeAttribute('id');cs.scrollTop=cs.scrollHeight;}
  clearInterval(timer);b.removeAttribute('id');S.streaming=false;document.getElementById('send-btn').disabled=false;document.getElementById('stop-btn').classList.remove('show');_abortCtrl=null;cs.scrollTop=cs.scrollHeight;
}

function sse(type,data,b,raw,start){
  try{
    var lbl=document.getElementById('sB-label'),bar=document.getElementById('sB-bar'),fill=bar?bar.querySelector('.fill'):null;
    if(type==='skills'){try{var sn=JSON.parse(data);lbl.textContent='已启用: '+sn.join('、');}catch(e){}}
    else if(type==='text'){raw+=data;if(raw.length<2)return raw;
      if(lbl)lbl.textContent='收到回复（生成完成）';if(bar)bar.style.display='none';
      var e=Math.round((Date.now()-start)/1000);b.innerHTML='<div class="think-done">耗时 '+e+' 秒</div>'+md(raw);}
    else if(type==='progress'){var p=JSON.parse(data);
      if(lbl){lbl.textContent=p.label||'处理中';
        if(bar){bar.style.display='block';if(p.step&&p.total)fill.style.width=Math.round(p.step/p.total*100)+'%';}}
      else{b.innerHTML='<div class="think-done"><span class="spin"></span> '+esc(p.label||'处理中')+' '+Math.round((Date.now()-start)/1000)+'s</div>'+(raw?md(raw):'');}}
    else if(type==='done'){try{var d=JSON.parse(data);b.innerHTML='<div class="think-done">耗时 '+Math.round((Date.now()-start)/1000)+' 秒</div>'+md(d.content||'');updateState(d);
      if(d.resources&&d.type==='resources'){var link=document.createElement('div');link.className='res-link';link.textContent='在资源库中查看 >';link.onclick=function(){go('resources');};b.appendChild(link);}}catch(e){b.innerHTML='<span style="color:var(--rust)">解析错误</span>';}}
    else if(type==='error'){b.innerHTML='<span style="color:var(--rust)">错误: '+esc(data)+'</span>';}
  }catch(e){}
  var cs=document.getElementById('chat-scroll');if(cs)cs.scrollTop=cs.scrollHeight;return raw;
}

function updateState(d){if(d.profile)S.profile=d.profile;if(d.resources){S.resources=d.resources;var ok=S.allRes.some(function(x){return x.topic===d.resources.topic&&x.generated_at===d.resources.generated_at;});if(!ok){S.allRes.unshift(d.resources);if(S.allRes.length>50)S.allRes=S.allRes.slice(0,50);}}if(d.learning_path)S.path=d.learning_path;}

// 画像
function renderProfile(){var el=document.getElementById('profile-el'),p=S.profile;
  if(!p){el.innerHTML='<div class="empty"><h3>画像尚未构建</h3><p>去对话页面聊聊你的学习情况吧</p><button class="btn" onclick="go(\'chat\')">去聊天</button></div>';return;}
  var fd=p.knowledge_foundation||{},completion=S.recs.length?Math.min(S.recs.reduce(function(s,r){return s+(r.correct||0)},0)/Math.max(S.recs.reduce(function(s,r){return s+(r.total||0)},0),1),1):0.5,vals=[parseFloat(fd.math)||0.4,parseFloat(fd.programming)||0.4,parseFloat(fd.ml_prerequisites)||0.4,(p.difficulty_level=='入门'?0.3:p.difficulty_level=='中级'?0.6:0.85),completion];
  var gaps=p.struggling_topics||[],done=p.mastered_topics||[];
  el.innerHTML='<div class="ph" style="display:flex;justify-content:space-between;align-items:flex-end"><div><h2>我的画像</h2><p>'+esc(p.target_course||'机器学习')+'</p></div><button class="btn-sm" onclick="editProfile()">✏️ 修正画像</button></div>'+
    '<div class="profile-grid"><div class="card"><h4>能力雷达</h4><div style="display:flex;justify-content:center"><div id="radar" style="width:300px;height:280px"></div></div></div>'+
    '<div class="card"><h4>学习特征</h4>'+row('学习目标',(p.short_term_goal||p.mid_term_goal||'?').substring(0,20))+row('认知风格',p.cognitive_style)+row('语言偏好',(p.language_style||'待了解'))+row('难度偏好',p.difficulty_level)+row('每周时间',(p.time_per_week||'待了解'))+'</div></div>';
  // 知识点掌握度地图（带遗忘衰减）+ 该复习了 + 错因分布
  var mm=p.mastery_map||{};var mmKeys=Object.keys(mm);
  if(mmKeys.length){
    var rows=mmKeys.map(function(k){return{k:k,eff:effScore(mm[k]),raw:mm[k].score||0};}).sort(function(a,b){return a.eff-b.eff;});
    var due=rows.filter(function(r){return r.raw>=0.6&&r.eff<0.55;}).map(function(r){return r.k;});
    var h2='<div class="card" style="margin-top:16px"><h4>知识点掌握度（颜色越绿越熟，随时间自然衰减）</h4>';
    rows.slice(0,12).forEach(function(r){var pct=Math.round(r.eff*100);var col=r.eff>=0.7?'var(--sage)':(r.eff>=0.4?'var(--accent)':'var(--rust)');
      h2+='<div style="display:flex;align-items:center;gap:10px;padding:4px 0"><span style="width:130px;font-size:.82rem;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+esc(r.k)+'</span><div style="flex:1;height:8px;background:var(--border);border-radius:4px;overflow:hidden"><div style="width:'+pct+'%;height:100%;background:'+col+';border-radius:4px"></div></div><span style="width:38px;font-size:.76rem;color:var(--muted);text-align:right">'+pct+'%</span></div>';});
    if(due.length)h2+='<div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border)"><span style="font-size:.8rem;font-weight:600">⏰ 该复习了：</span><span class="tags" style="display:inline-flex">'+due.map(function(d){return'<span class="tag warn" style="cursor:pointer" onclick="go(\'chat\');setTimeout(function(){var i=document.getElementById(\'msg-in\');if(i){i.value=\'出几道关于'+jsq(d)+'的题帮我复习\';send();}},100)">'+esc(d)+'</span>';}).join('')+'</span></div>';
    h2+='</div>';el.innerHTML+=h2;}
  var ep=p.error_patterns;
  if(ep&&!Array.isArray(ep)&&Object.keys(ep).length){
    var tot=0;Object.keys(ep).forEach(function(k){tot+=ep[k];});
    el.innerHTML+='<div class="card" style="margin-top:16px"><h4>错因分布（出题会针对主要错因加强训练）</h4><div class="tags">'+Object.keys(ep).sort(function(a,b){return ep[b]-ep[a];}).map(function(k){return'<span class="tag warn">'+esc(k)+' ×'+ep[k]+'</span>';}).join('')+'</div></div>';}
  // AI判断依据（证据溯源）
  var ev=p._evidence||{};var evKeys=Object.keys(ev);
  if(evKeys.length){var dimNames={ml:'机器学习基础',prog:'编程水平',math:'数学基础',goal:'学习目标',style:'认知风格',time:'时间投入',weak:'薄弱点',lang:'语言偏好'};
    el.innerHTML+='<div class="card" style="margin-top:16px"><h4>AI 判断依据（点击展开）</h4><div id="ev-list" style="display:none">'+evKeys.map(function(k){return'<div class="stat-row"><span class="l">'+esc(dimNames[k]||k)+'</span><span class="v" style="max-width:70%;text-align:right">你说："'+esc(ev[k])+'"</span></div>';}).join('')+'</div><button class="btn-sm" style="margin-top:6px" onclick="var d=document.getElementById(\'ev-list\');d.style.display=d.style.display===\'none\'?\'block\':\'none\'">展开/收起</button></div>';}
  if(S.path&&S.path.steps){var ph='<div class="card" style="margin-top:16px"><h4>学习路径摘要</h4><div class="steps-grid">';S.path.steps.slice(0,3).forEach(function(s,i){ph+='<div class="step-card'+(s._done?' ok':'')+'"><div class="name">'+(i+1)+'. '+esc(s.name||'')+'</div><div class="reason">难度:'+esc(s.difficulty||'?')+' 约'+esc(String(s.estimated_hours||'?'))+'h</div></div>';});ph+='</div><div style="margin-top:10px"><button class="btn-sm" onclick="go(\'path\')">查看完整路径</button></div></div>';el.innerHTML+=ph;}setTimeout(function(){drawRadar('radar',vals);},120);}
function row(l,v){return'<div class="stat-row"><span class="l">'+esc(l)+'</span><span class="v">'+esc(String(v||'?'))+'</span></div>';}
// 掌握度带遗忘衰减：和后端 utils/mastery.py 用同一个公式
function effScore(e){var s=e.score||0.4,days=0;
  try{days=Math.max(0,(Date.now()-new Date(String(e.updated||'').replace(' ','T')).getTime())/86400000);}catch(x){}
  var st=14+7*(e.attempts||0);return s*Math.exp(-days/st);}

// 手动修正画像：AI判断错了自己改
function editProfile(){var p=S.profile||{},fd=p.knowledge_foundation||{};
  function lvlSel(id,val){var opts=[[0.15,'比较弱'],[0.5,'一般'],[0.7,'不错'],[0.9,'很强']];
    return'<select id="'+id+'" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:.85rem">'+opts.map(function(o){var sel=Math.abs((val||0.4)-o[0])<0.15?' selected':'';return'<option value="'+o[0]+'"'+sel+'>'+o[1]+'</option>';}).join('')+'</select>';}
  var mc=document.getElementById('modal-content');
  mc.innerHTML='<h3>修正我的画像</h3><p style="font-size:.8rem;color:var(--muted);margin-bottom:12px">AI 判断不准的地方自己改，保存后学习路径和出题难度都会跟着调整</p>'+
    '<div class="set-form" style="box-shadow:none;border:none;padding:0">'+
    '<div class="fr"><label>机器学习基础</label>'+lvlSel('ep-ml',fd.ml_prerequisites)+'</div>'+
    '<div class="fr"><label>编程水平</label>'+lvlSel('ep-prog',fd.programming)+'</div>'+
    '<div class="fr"><label>数学基础</label>'+lvlSel('ep-math',fd.math)+'</div>'+
    '<div class="fr"><label>学习目标</label><input type="text" id="ep-goal" value="'+esc(p.short_term_goal||'')+'" placeholder="考研 / 找工作 / 兴趣..."></div>'+
    '<div class="fr"><label>认知风格</label><select id="ep-style" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:.85rem">'+['视觉型','文字型','动手型','听觉型'].map(function(s){return'<option'+(p.cognitive_style===s?' selected':'')+'>'+s+'</option>';}).join('')+'</select></div>'+
    '<div class="fr"><label>每周学习时间</label><input type="text" id="ep-time" value="'+esc(p.time_per_week||'')+'" placeholder="如：10小时"></div>'+
    '<div class="fr"><label>讲解风格偏好</label><select id="ep-lang" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:.85rem"><option'+(p.language_style==='生动比喻'?' selected':'')+'>生动比喻</option><option'+(p.language_style==='严谨学术'?' selected':'')+'>严谨学术</option></select></div>'+
    '<div id="ep-status" style="font-size:.82rem;margin-bottom:8px"></div>'+
    '<button class="btn" onclick="saveProfileEdit()">保存修正</button></div>';
  M.classList.add('show');}
async function saveProfileEdit(){var st=document.getElementById('ep-status');
  var body={session_id:S.sid,ml:document.getElementById('ep-ml').value,prog:document.getElementById('ep-prog').value,math:document.getElementById('ep-math').value,
    goal:document.getElementById('ep-goal').value,style:document.getElementById('ep-style').value,time:document.getElementById('ep-time').value,lang:document.getElementById('ep-lang').value};
  try{var r=await(await fetch('/api/profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
    if(r.ok){S.profile=r.profile;M.classList.remove('show');renderProfile();}
    else st.innerHTML='<span style="color:var(--rust)">'+esc(r.error||'保存失败')+'</span>';
  }catch(e){st.innerHTML='<span style="color:var(--rust)">网络错误</span>';}}

// 学习路径
function renderPath(){var el=document.getElementById('path-el'),lp=S.path;
  if(!lp||((!lp.phases||!lp.phases.length)&&(!lp.steps||!lp.steps.length))){el.innerHTML='<div class="empty"><h3>学习路径尚未规划</h3><p>去聊天让我了解你，帮你规划学习路径</p><button class="btn" onclick="go(\'chat\')">去聊天</button></div>';return;}
  var phases=lp.phases||[],hasPhases=phases.length>0;
  var html='<div class="ph"><h2>学习路径</h2><p>'+esc(lp.course_name||'机器学习')+' · '+esc(lp.type||'个性化')+'</p></div>';
  if(lp.overview)html+='<div class="hero" style="margin-bottom:20px"><div class="title">学习建议</div><p style="font-size:.88rem;color:var(--ink)">'+esc(lp.overview)+'</p></div>';

  if(hasPhases){
    html+='<div class="pbar"><div class="row"><span>学习阶段</span><span>共 '+phases.length+' 个阶段</span></div></div>';
    phases.forEach(function(p,i){
      var emoji={'入门':'🟢','中等':'🟡','进阶':'🔴'}[p.difficulty]||'⚪';
      html+='<div class="card" style="margin-bottom:12px">';
      html+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><h3 style="margin:0;font-size:1rem">'+emoji+' 阶段'+(p.phase||(i+1))+'：'+esc(p.title||'')+'</h3><span style="font-size:.78rem;color:var(--muted)">'+esc(p.duration||'')+'</span></div>';
      if(p.goal)html+='<p style="font-size:.85rem;margin-bottom:8px"><strong>目标</strong>：'+esc(p.goal)+'</p>';
      var chs=p.chapters||[];
      if(chs.length)html+='<div style="margin:8px 0"><strong style="font-size:.82rem">涵盖章节</strong>：<div class="tags" style="margin-top:4px">'+chs.map(function(c){return'<span class="tag ok" style="cursor:pointer" onclick="go(\'chat\');setTimeout(function(){var i=document.getElementById(\'msg-in\');if(i){i.value=\'帮我生成'+jsq(c)+'的学习资料\';send();}},100)" title=\'点击学习 '+esc(c)+'\'>'+esc(c)+'</span>';}).join('')+'</div></div>';
      if(p.extra_content)html+='<p style="font-size:.82rem;color:var(--muted);margin:6px 0">'+esc(p.extra_content.substring(0,150))+'</p>';
      var tasks=p.tasks||[];
      if(tasks.length)html+='<div style="margin:6px 0;font-size:.82rem"><strong>动手任务</strong>：<ul style="margin:4px 0 0 16px">'+tasks.slice(0,3).map(function(t){return'<li>'+esc(t)+'</li>';}).join('')+'</ul></div>';
      var resources=p.resources||[];
      if(resources.length)html+='<div style="margin:6px 0;font-size:.8rem;color:var(--sage)"><strong>推荐资源</strong>：'+esc(resources.slice(0,2).join('、'))+'</div>';
      html+='</div>';
    });
  }else if(lp.steps){
    // 兼容旧格式
    var steps=lp.steps,mas=(S.profile&&S.profile.mastered_topics)?S.profile.mastered_topics:[],mSet={};mas.forEach(function(m){mSet[m.toLowerCase()]=true;});
    var done=steps.filter(function(s){return mSet[s.name.toLowerCase()];}).length;
    html+='<div class="pbar"><div class="row"><span>学习进度</span><span>'+done+'/'+steps.length+'</span></div><div class="bar"><div class="fill" style="width:'+(steps.length?done/steps.length*100:0)+'%"></div></div></div>';
    html+='<div class="steps-grid">'+steps.map(function(s){var isDone=mSet[s.name.toLowerCase()]||s._done;return'<div class="step-card'+(isDone?' ok':'')+'"><div class="name">'+(isDone?'✅ ':'')+esc(s.name)+'</div><div class="reason">'+esc((s.reason||'').substring(0,50))+'</div>'+(isDone?"<div class='rmeta' style='color:var(--sage)'>已掌握</div>":"<button class='btn-sm' onclick=\"go('chat');setTimeout(function(){var i=document.getElementById('msg-in');if(i){i.value='帮我生成'+jsq(s.name)+'的学习资料';send();}},100)\" style='margin-top:4px'>开始学习</button>")+'</div>';}).join('')+'</div>';
  }
  el.innerHTML=html;}

// 资源库
function renderResources(){var el=document.getElementById('resources-el'),all=S.allRes;
  if(!all.length&&!S.resources){el.innerHTML='<div class="empty"><h3>资源库为空</h3><p>去对话页面生成学习资料吧</p><button class="btn" onclick="go(\'chat\')">去聊天</button></div>';return;}
  var tabs=[{k:'all',l:'全部'},{k:'lecture_notes',l:'讲义'},{k:'mind_map',l:'思维导图'},{k:'exercises',l:'练习题'},{k:'reading_materials',l:'阅读材料'},{k:'extended_reading',l:'拓展阅读'},{k:'code_example',l:'代码'},{k:'ppt_outline',l:'PPT'},{k:'video_script',l:'视频'}];
  var cards=buildCards(all.length?all:(S.resources?[S.resources]:[]));
  // 章节筛选：从已生成资料的主题自动归集
  var topics=[];cards.forEach(function(c){if(c.topic&&topics.indexOf(c.topic)<0)topics.push(c.topic);});
  if(S.resTopic&&S.resTopic!=='all'&&topics.indexOf(S.resTopic)<0)S.resTopic='all';
  var ft=cards.filter(function(c){return(S.resFilter==='all'||c.type===S.resFilter)&&(!S.resTopic||S.resTopic==='all'||c.topic===S.resTopic);});
  el.innerHTML='<div class="ph"><h2>资源库</h2><p>共 '+cards.length+' 份资料</p></div>'+
    (topics.length?'<div class="res-ctl"><div class="res-tabs"><span style="font-size:.76rem;color:var(--muted);align-self:center;margin-right:4px">章节:</span><button class="'+((!S.resTopic||S.resTopic==='all')?'on':'')+'" onclick="S.resTopic=\'all\';renderResources()">全部</button>'+topics.map(function(t){return'<button class="'+(S.resTopic===t?'on':'')+'" onclick="S.resTopic=\''+jsq(t)+'\';renderResources()">'+esc(t)+'</button>';}).join('')+'</div></div>':'')+
    '<div class="res-ctl"><div class="res-tabs"><span style="font-size:.76rem;color:var(--muted);align-self:center;margin-right:4px">类型:</span>'+tabs.map(function(t){return'<button class="'+(S.resFilter===t.k?'on':'')+'" onclick="S.resFilter=\''+t.k+'\';renderResources()">'+t.l+'</button>';}).join('')+'</div></div>'+
    (ft.length?'<div class="res-grid">'+ft.map(function(c){return'<div class="res-card"><div class="rtype">'+c.typeLabel+'</div><div class="rtitle">'+esc(c.title)+'</div><div class="rmeta">'+esc(c.topic)+' '+esc(c.time||'')+(c.pathStep?" <span style='color:var(--sage);font-size:.73rem;font-weight:600'>"+esc(c.pathStep)+"</span>":'')+'</div><div class="racts"><button class="btn-sm" onclick="showPreview('+c.idx+')">预览</button>'+(c.type==='ppt_outline'?'<button class="btn-sm" onclick="downloadPPTX()" style="background:var(--ink);color:#fff">下载PPTX</button>':'')+'</div></div>';}).join('')+'</div>':'<div class="empty"><p>无匹配</p></div>');}

function buildCards(list){var lb={lecture_notes:'讲义',mind_map:'思维导图',exercises:'练习题',reading_materials:'阅读材料',extended_reading:'拓展阅读',code_example:'代码',ppt_outline:'PPT',video_script:'视频'};PD=[];var cards=[];list.forEach(function(r){Object.keys(lb).forEach(function(k){var v=r[k];if(v===null||v===undefined||(Array.isArray(v)&&!v.length))return;var idx=PD.length;PD.push({type:k,content:v,topic:r.topic||''});var t='';if(k==='extended_reading'&&Array.isArray(v))t=v.length+'篇阅读';else if(k==='exercises'&&Array.isArray(v))t=v.length+'道题';else t=String(v).replace(/\n/g,' ').substring(0,60);var ps=r.path_step;var psl=ps?('Step '+ps.index+'/'+ps.total+' '+esc(ps.name||'')):'';cards.push({type:k,typeLabel:lb[k],title:t,topic:r.topic||'',time:r.generated_at||'',idx:idx,pathStep:psl,pathStepData:ps});});});return cards;}

function showPreview(idx){var d=PD[idx];if(!d)return;var mc=document.getElementById('modal-content'),h='';
  if(d.type==='exercises'){if(!d.content||(Array.isArray(d.content)&&!d.content.length)){h='<h3>练习题 - '+esc(d.topic)+'</h3><p style="color:var(--muted)">生成失败，请在对话中说「<b>重新生成题目</b>」</p>';}else{try{var exs=Array.isArray(d.content)?d.content:JSON.parse(d.content);h='<h3>练习题 - '+esc(d.topic)+'</h3>';exs.forEach(function(q,i){h+=quizHTML(q,i);});h+='<div style="margin-top:16px;display:flex;gap:8px"><button class="btn" onclick="submitQuiz('+idx+')">提交评估</button><button class="btn-sm" onclick="moreExercises(\''+jsq(d.topic)+'\')">生成更多题</button></div><div id="quiz-result-area" style="margin-top:16px"></div>';}catch(e){h='<pre>'+esc(String(d.content))+'</pre>';}}}
  else if(d.type==='code_example'){h='<h3>代码 - '+esc(d.topic)+'</h3><pre><code>'+esc(String(d.content))+'</code></pre>';}
  else if(d.type==='mind_map'){var mmc=String(d.content).replace(/<\/script/gi,'');
    if(mmc.trim().indexOf('mindmap')===0){
      // 老资料是 Mermaid 格式，继续用 Mermaid 渲染兼容
      h='<h3>思维导图 - '+esc(d.topic)+'</h3><div class="mermaid" id="mermaid-preview" style="background:#faf8f4;padding:16px;border-radius:8px">'+esc(mmc)+'</div>';setTimeout(function(){try{var el=document.getElementById('mermaid-preview');if(el){el.removeAttribute('data-processed');mermaid.run({nodes:[el]}).catch(function(){el.innerHTML='<span style="color:var(--muted);font-size:.8rem">思维导图渲染失败，可以在对话里说「重新生成思维导图」</span>';});}}catch(e){}},50);
    }else{
      // 新资料是 Markdown，用 Markmap 渲染成可折叠交互导图
      h='<h3>思维导图 - '+esc(d.topic)+'</h3><p style="font-size:.76rem;color:var(--muted);margin-bottom:6px">点击节点前的圆圈可以折叠/展开分支，滚轮缩放</p><div style="background:#faf8f4;border-radius:8px;padding:4px"><div class="markmap" style="height:62vh"><script type="text/template">'+mmc+'<\/script></div></div>';
      setTimeout(function(){try{if(window.markmap&&markmap.autoLoader)markmap.autoLoader.renderAll();}catch(e){}},80);
    }}
  else if(d.type==='ppt_outline'){h='<h3>PPT大纲 - '+esc(d.topic)+'</h3>'+md(String(d.content))+'<button class="btn" onclick="_previewPPT.outline=d.content;_previewPPT.topic=d.topic;downloadPPTX()" style="margin-top:12px">下载PPTX</button>';}
  else if(d.type==='video_script'){h='<h3>视频代码 - '+esc(d.topic)+'</h3><pre><code>'+esc(String(d.content))+'</code></pre><button class="btn" onclick="renderVideo('+idx+')" style="margin-top:12px">渲染MP4</button><div id="video-render-status" style="margin-top:8px;font-size:.82rem;color:var(--muted)"></div>';}
  else if(d.type==='reading_materials'){h='<h3>📖 阅读材料 - '+esc(d.topic)+'</h3><div style="line-height:1.9;font-size:.88rem;padding:12px 16px;background:var(--paper);border-radius:8px;max-height:60vh;overflow-y:auto">'+mdKb(String(d.content))+'</div>';}
  else if(d.type==='extended_reading'){h='<h3>📚 拓展阅读 - 小故事</h3>';var items=Array.isArray(d.content)?d.content:[d.content];items.forEach(function(r,i){var txt=typeof r==='string'?r:JSON.stringify(r);h+='<div style="padding:10px 0;border-bottom:1px solid var(--border);line-height:1.8"><strong>'+(i+1)+'.</strong> '+esc(txt)+'</div>';});}
  else{h='<h3>'+esc(d.topic)+'</h3>'+md(String(d.content));}
  mc.innerHTML=h;M.classList.add('show');}

function quizHTML(q,i){var t=q.type||'';var opts=q.options||[];var ans=q.answer||'';var isMulti=t.indexOf('多选')>=0;var isSingle=t.indexOf('单选')>=0||(!isMulti&&t.indexOf('选择')>=0);var isJudge=t.indexOf('判断')>=0;
  // 判断题：固定选项
  if(isJudge){opts=['对','错'];}
  // 选择题但选项为空 — 显示文本输入而不是造假选项
  var hasRealOpts=opts.length>0&&!opts.every(function(o){var s=String(o);return s==='选项A'||s==='选项B'||s==='选项C'||s==='选项D'||s==='选项E';});
  var h='<div class="quiz-item"><div class="q"><strong>'+(i+1)+'.</strong> ['+esc(t||'题')+'] '+esc(q.question||'')+'</div>';
  if(hasRealOpts&&isMulti){opts.forEach(function(o){h+='<label><input type="checkbox" name="qz_'+i+'" value="'+esc(String(o))+'">'+esc(String(o))+'</label>';});}
  else if(hasRealOpts&&isSingle){opts.forEach(function(o){h+='<label><input type="radio" name="qz_'+i+'" value="'+esc(String(o))+'">'+esc(String(o))+'</label>';});}
  else if(isJudge){opts.forEach(function(o){h+='<label><input type="radio" name="qz_'+i+'" value="'+esc(o)+'">'+esc(o)+'</label>';});}
  else{h+='<input type="text" name="qz_'+i+'" placeholder="输入答案..." style="width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:6px;margin-top:4px">';}
  h+='</div>';return h;}

async function submitQuiz(idx){var d=PD[idx];if(!d)return;var exs=Array.isArray(d.content)?d.content:JSON.parse(d.content);var ans={};for(var i=0;i<exs.length;i++){var es=document.getElementsByName('qz_'+i);var vals=[];for(var j=0;j<es.length;j++){if(es[j].checked)vals.push(es[j].value);else if(es[j].type==='text'&&es[j].value)vals.push(es[j].value);}if(vals.length>1)ans[i]=vals.join(', ');else if(vals.length===1)ans[i]=vals[0];}if(!Object.keys(ans).length){alert('请至少回答一道题');return;}var area=document.getElementById('quiz-result-area');area.innerHTML='<div style="color:var(--muted);font-size:.82rem"><span class="spin"></span> 批改中...</div>';try{var r=await fetch('/api/evaluate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({exercises:exs,answers:ans,session_id:S.sid,profile:S.profile||{},topic:d.topic||''})});if(!r.ok){area.innerHTML='<span style="color:var(--rust)">服务器错误: '+r.status+'</span>';return;}var t=await r.text();var j;try{j=JSON.parse(t);}catch(e){area.innerHTML='<span style="color:var(--rust)">解析失败: '+t.substring(0,200)+'</span>';return;}var h='<h4 style="color:var(--sage)">得分：'+j.score+'/100（'+j.correct+'/'+j.total+' 正确）</h4>';(j.results||[]).forEach(function(r,i){var ok=r.is_correct;h+='<div class="quiz-item" style="border-left:3px solid '+(ok?'var(--sage)':'var(--rust)')+'"><strong>'+(i+1)+'.</strong> '+(ok?'正确':'错误')+' '+esc((r.question||'').substring(0,80))+'<div style="font-size:.82rem;margin:6px 0">你的答案：<strong>'+(r.student_answer||'未作答')+'</strong> | 正确答案：<strong style="color:var(--sage)">'+esc(r.correct_answer)+'</strong></div><div style="font-size:.8rem;color:var(--muted);background:var(--paper);padding:6px 10px;border-radius:6px">'+esc((r.explanation||'').substring(0,200))+'</div></div>';});if(j.ai_analysis)h+='<div class="card" style="margin-top:12px"><h4>AI 个性化分析</h4>'+md(j.ai_analysis)+'</div>';area.innerHTML=h;var qr={date:new Date().toISOString().split('T')[0],score:j.score,topic:d.topic||'',total:j.total,correct:j.correct,results:j.results||[],ai_analysis:j.ai_analysis||''};S.recs.push(qr);S.quizResults[d.topic||'default']=qr;if(j.updated_profile){S.profile=j.updated_profile;if(document.getElementById('page-profile').classList.contains('show'))renderProfile();}if(j.score>=60&&j.updated_path_steps&&j.updated_path_steps.length&&S.path){var flat=(S.path.phases||[]).reduce(function(a,p){return a.concat((p.chapters||[]).map(function(c){return{name:c};}));},[]);if(!flat.length)flat=S.path.steps||[];j.updated_path_steps.forEach(function(sn){flat.forEach(function(st){if(st.name===sn){st._done=true;}});if(S.profile){var mt=S.profile.mastered_topics||[];if(mt.indexOf(sn)<0){mt.push(sn);S.profile.mastered_topics=mt;}}});}try{localStorage.setItem('a3_recs',JSON.stringify(S.recs));localStorage.setItem('a3_quiz',JSON.stringify(S.quizResults));}catch(e){}
// 记录页开着的话立刻刷新，不用切页面才看到新答题记录
if(document.getElementById('page-records').classList.contains('show'))renderRecords();
}catch(e){area.innerHTML='<span style="color:var(--rust)">网络错误: '+esc(String(e))+'</span>';}}

function moreExercises(topic){go('chat');var i=document.getElementById('msg-in');if(i){i.value='帮我多出几道关于'+topic+'的练习题';send();}}
var _previewPPT={};async function downloadPPTX(topic,outline){var r=S.resources,t=topic||(r?r.topic:'');if(_previewPPT.outline){t=_previewPPT.topic;outline=_previewPPT.outline;}if(!outline&&(!r||!r.ppt_outline)){alert('暂无PPT大纲');return;}outline=outline||r.ppt_outline;try{var resp=await fetch('/api/export-pptx',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ppt_outline:outline,topic:t||'课件'})});if(!resp.ok)throw new Error('fail');var blob=await resp.blob(),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=(t||'课件')+'.pptx';a.click();}catch(e){alert('导出失败');}}

async function renderVideo(idx){var d=PD[idx];if(!d||d.type!=='video_script')return;var st=document.getElementById('video-render-status');if(!st)return;st.innerHTML='<div style="display:flex;align-items:center;gap:8px;color:var(--muted);font-size:.82rem"><span class="spin"></span> 渲染中（最长等待3分钟）...</div>';try{var r=await fetch('/api/render-video',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:String(d.content),topic:d.topic||'动画'})});var ct=r.headers.get('content-type')||'';if(ct.indexOf('application/json')>=0){var ej=await r.json();st.innerHTML='<span style=\"color:var(--rust)\">渲染失败: '+esc(ej.error||ej.detail||'未知错误')+'</span>';return;}if(!r.ok){st.innerHTML='<span style=\"color:var(--rust)\">服务器错误: '+r.status+'</span>';return;}var blob=await r.blob();if(blob.size<5000){var txt=await blob.text();st.innerHTML='<span style=\"color:var(--rust)\">渲染失败: '+(txt.substring?esc(txt.substring(0,200)):esc(String(txt)))+'</span>';return;}var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=(d.topic||'动画')+'.mp4';a.click();st.innerHTML='<span style=\"color:var(--sage)\">下载成功！可播放视频</span>';}catch(e){st.innerHTML='<span style=\"color:var(--rust)\">网络错误: '+esc(String(e))+'</span>';}}

// 知识库
function renderKnowledge(){var el=document.getElementById('knowledge-el');el.innerHTML='<div class="ph"><h2>知识库管理</h2><p>机器学习课程教材 · '+KD.length+' 个文档</p></div><div class="chart-box"><h4 style="display:flex;justify-content:space-between;align-items:center">章节依赖图（绿色 = 已掌握，箭头 = 先学→后学）<button class="btn-sm" onclick="showGraphBig()">🔍 放大查看</button></h4><div id="kb-graph" style="overflow-x:auto;color:var(--muted);font-size:.85rem">加载中...</div></div><div class="kb-header"><button class="btn-sm" onclick="document.getElementById(\'kb-form\').classList.toggle(\'show\')">+ 添加资料到知识库</button></div><div class="kb-add-form" id="kb-form"><input type="text" id="kb-title" placeholder="标题（会作为文档名）"><textarea id="kb-content" placeholder="粘贴资料正文（至少30字），或用下面的按钮选择 txt/md 文件"></textarea><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><input type="file" id="kb-file" accept=".txt,.md" onchange="readKBFile(this)" style="font-size:.78rem"><button class="btn-sm" onclick="addKBItem(this)">入库（约需1分钟向量化）</button><span id="kb-up-status" style="font-size:.78rem;color:var(--muted)"></span></div></div><div class="kb-grid" id="kb-grid"></div>';renderKBGrid();loadKBGraph();}
function readKBFile(inp){var f=inp.files&&inp.files[0];if(!f)return;var r=new FileReader();r.onload=function(){document.getElementById('kb-content').value=r.result;if(!document.getElementById('kb-title').value)document.getElementById('kb-title').value=f.name.replace(/\.(txt|md)$/,'');};r.readAsText(f,'utf-8');}
async function loadKBGraph(){var el=document.getElementById('kb-graph');if(!el)return;
  if(!window.echarts){el.innerHTML='图表库加载中，请刷新';return;}
  try{var d=await(await fetch('/api/kb/graph')).json();var nodes=d.nodes||[],edges=d.edges||[];
    if(!nodes.length){el.innerHTML='暂无图谱数据';return;}
    var mas=(S.profile&&S.profile.mastered_topics)||[];
    var eNodes=nodes.map(function(n){var nm=String(n.name||n.id).substring(0,16);var mastered=mas.some(function(m){return nm.indexOf(m)>=0||m.indexOf(nm)>=0;});
      return{id:String(n.id),name:nm,category:mastered?0:1,label:{show:true,fontSize:11,color:mastered?'#4a7c59':'#1a2332'},symbolSize:mastered?36:28,itemStyle:{color:mastered?'#4a7c59':'#8b8578'}};});
    var eEdges=edges.map(function(e){return{source:String(e.source),target:String(e.target),lineStyle:{color:'#d0c8b2',curveness:.15}};});
    window._kbgChart=echarts.init(el);el.style.width='100%';el.style.height='460px';
    window._kbgChart.setOption({tooltip:{formatter:function(p){if(p.dataType==='node')return p.name+(p.data.category===0?' (已掌握)':'');}},series:[{type:'graph',layout:'force',force:{repulsion:280,edgeLength:[70,220],gravity:.1},roam:true,draggable:true,data:eNodes,links:eEdges,edgeSymbol:['none','arrow'],edgeSymbolSize:[0,10],lineStyle:{color:'#d0c8b2',curveness:.15},categories:[{name:'已掌握',itemStyle:{color:'#4a7c59'}},{name:'未掌握',itemStyle:{color:'#8b8578'}}]}]});
  }catch(e){el.innerHTML='图谱加载失败';}}
function showGraphBig(){if(!window._kbgChart){alert('图谱还没加载出来，稍等一下');return;}
  M.querySelector('.modal-inner').style.maxWidth='96vw';var mc=document.getElementById('modal-content');
  mc.innerHTML='<h3>章节依赖图</h3><p style="font-size:.78rem;color:var(--muted);margin-bottom:8px">绿色=已掌握 · 灰色=未掌握 · 箭头=先学→后学 · 可拖拽缩放</p><div id="kb-graph-big" style="width:100%;height:75vh"></div>';
  M.classList.add('show');setTimeout(function(){var c=echarts.init(document.getElementById('kb-graph-big'));c.setOption(window._kbgChart.getOption(),true);},120);}
async function loadKBDocs(){try{var r=await fetch('/api/kb/docs');var d=await r.json();KD=d.docs||[];}catch(e){}}
async function importKB(){try{var r=await fetch('/api/kb/import',{method:'POST'});var d=await r.json();alert(d.message||'完成');}catch(e){alert('构建失败');}}
function renderKBGrid(){var g=document.getElementById('kb-grid'),items=KD.length?KD:S.kbItems;if(!items||!items.length){g.innerHTML='<div class="empty"><h3>知识库为空</h3><p>知识库自动从 course_data 目录加载</p></div>';return;}g.innerHTML=items.map(function(it,i){var raw=(it.preview||it.content||'').substring(0,200);var pv=raw.replace(/^#{1,3}\s/gm,'').replace(/\*\*/g,'').replace(/\*/g,'').replace(/\n/g,' ');var sz=it.size_chars?(it.size_chars>1000?Math.round(it.size_chars/1000)+'k字':it.size_chars+'字'):'';return'<div class="kb-card" onclick="showKbContent('+i+')" style="cursor:pointer"><div class="kb-title">'+esc(it.title)+'</div><div class="kb-preview">'+(pv?esc(pv)+'...':'')+'</div><div class="kb-meta"><span>'+esc(it.source||'')+'</span><span>'+sz+' | '+(it.line_count||'')+'行</span></div></div>';}).join('');}
async function addKBItem(btn){var t=document.getElementById('kb-title').value.trim(),c=document.getElementById('kb-content').value.trim();
  if(!t){alert('请输入标题');return;}if(c.length<30){alert('正文至少30个字');return;}
  var st=document.getElementById('kb-up-status');btn.disabled=true;st.textContent='正在写入并向量化，别关页面...';
  try{var r=await(await fetch('/api/kb/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t,content:c})})).json();
    if(r.ok){st.textContent='';await loadKBDocs();renderKnowledge();alert(r.message||'已入库');}
    else{st.textContent='';alert(r.error||'入库失败');}
  }catch(e){st.textContent='';alert('网络错误或超时，稍后刷新看看文档列表');}
  btn.disabled=false;}
async function showKbContent(idx){var items=KD.length?KD:S.kbItems;var it=items[idx];if(!it)return;var mc=document.getElementById('modal-content');mc.innerHTML='<div style=\"text-align:center;padding:40px\"><span class=\"spin\"></span> 加载中...</div>';M.classList.add('show');try{var r=await fetch('/api/kb/doc/'+encodeURIComponent(it.filename));if(!r.ok){mc.innerHTML='<p>加载失败: '+r.status+'</p>';return;}var full=await r.text();var h='<h2>'+esc(it.title)+'</h2><div style=\"color:var(--muted);font-size:.82rem;margin-bottom:12px\">'+esc(it.source||'')+' | '+(it.line_count||'?')+'行 | '+(it.size_chars||'?')+'字</div><div style=\"line-height:1.9;font-size:.9rem;max-height:60vh;overflow-y:auto;padding:16px 20px;background:var(--paper);border-radius:8px\">'+mdKb(full)+'</div>';mc.innerHTML=h;}catch(e){mc.innerHTML='<p>网络错误: '+esc(String(e))+'</p>';}}

// 学习记录
function renderRecords(){var el=document.getElementById('records-el'),recs=S.recs,p=S.profile||{};
  var gaps=p.struggling_topics||[],done=p.mastered_topics||[];
  var tq=recs.reduce(function(s,r){return s+(r.total||0)},0),tc=recs.reduce(function(s,r){return s+(r.correct||0)},0),acc=tq?Math.round(tc/tq*100):0,days=new Set(recs.map(function(r){return r.date})).size;

  var html='<div class="ph"><h2>学习记录</h2></div><div id="daily-quiz-slot"></div><div id="mistake-slot"></div>';
  // 画像薄弱/已掌握卡片
  html+='<div class="profile-grid" style="margin-bottom:16px">';
  html+='<div class="card"><h4>薄弱环节</h4><div class="tags">'+(gaps.length?gaps.map(function(g){return'<span class="tag warn" style="cursor:pointer" onclick="go(\'chat\');setTimeout(function(){var i=document.getElementById(\'msg-in\');if(i){i.value=\'出几道关于'+jsq(g)+'的题\';send();}},100)">'+esc(g)+'</span>';}).join(''):'暂无')+'</div></div>';
  html+='<div class="card"><h4>已掌握</h4><div class="tags">'+(done.length?done.map(function(m){return'<span class="tag ok">'+esc(m)+'</span>';}).join(''):'暂无')+'</div></div></div>';

  if(!recs.length){html+='<div class="empty"><h3>暂无学习记录</h3><p>完成练习评估后展示学习数据</p><button class="btn" onclick="go(\'chat\')">去做练习</button></div>';el.innerHTML=html;loadDailySlot();loadMistakeSlot();return;}

  html+='<div class="stat-grid"><div class="stat-card"><div class="num">'+tq+'</div><div class="lbl">总练习数</div></div><div class="stat-card"><div class="num">'+acc+'%</div><div class="lbl">正确率</div></div><div class="stat-card"><div class="num">'+days+'</div><div class="lbl">学习天数</div></div><div class="stat-card"><div class="num">'+recs.length+'</div><div class="lbl">评估次数</div></div></div>';

  // AI总分析卡片：汇总所有记录的ai_analysis
  var allAnalysis=recs.filter(function(r){return r.ai_analysis&&r.ai_analysis.length>10;}).map(function(r){return r.ai_analysis;});
  if(allAnalysis.length>0){
    html+='<div class="hero" style="margin:16px 0"><div class="title">AI 综合学习分析</div><div style="font-size:.85rem;line-height:1.8;max-height:200px;overflow-y:auto">';
    allAnalysis.slice(0,5).forEach(function(a,i){
      html+='<div style="padding:6px 0;border-bottom:1px solid var(--border)"><strong>'+(i+1)+'.</strong> '+esc(a)+'</div>';
    });
    html+='</div></div>';
  }

  html+='<div class="chart-box"><h4>得分趋势</h4><div id="sc" style="width:100%;height:240px"></div></div>';
  html+='<div class="chart-box" style="margin-top:20px"><h4>答题详情</h4><div id="rec-detail-list"></div></div>';
  el.innerHTML=html;

  var detailList=document.getElementById('rec-detail-list');
  recs.slice().reverse().slice(0,20).forEach(function(r,j){
    var hi=r.score>=60;
    var detail='<div class="tl-item"><div class="dot '+(hi?'high':'low')+'"></div><div class="bd"><div class="l1" style="cursor:pointer" onclick="var d=document.getElementById(\'rd-'+j+'\');d.style.display=d.style.display==\'none\'?\'block\':\'none\'">得分 '+r.score+' - '+r.correct+'/'+r.total+' 正确</div><div class="l2">'+r.date+' '+esc(r.topic||'')+'</div><div id="rd-'+j+'" style="display:none;margin-top:8px;font-size:.82rem;line-height:1.8">'+(r.results||[]).map(function(x,i){var ok=x.is_correct;return'<div style="padding:4px 0;border-bottom:1px solid var(--border)"><strong>'+(i+1)+'.</strong> <span style="color:'+(ok?'var(--sage)':'var(--rust)')+'">'+(ok?'✓':'✗')+'</span> '+esc((x.question||'').substring(0,80))+'<div style="margin:4px 0 4px 14px;font-size:.78rem">你的答案：<strong style="color:'+(ok?'var(--sage)':'var(--rust)')+'">'+esc(x.student_answer||'未作答')+'</strong> | 正确：<strong style="color:var(--sage)">'+esc(x.correct_answer||'')+'</strong></div>'+((x.explanation&&!ok)?'<div style="margin:2px 0 2px 14px;font-size:.76rem;color:var(--muted);background:var(--paper);padding:4px 8px;border-radius:4px">💡 '+esc(x.explanation.substring(0,200))+'</div>':'')+'</div>';}).join('')+'</div></div></div>';
    if(detailList)detailList.insertAdjacentHTML('beforeend',detail);
  });

  setTimeout(function(){drawChart('sc',recs);},150);loadDailySlot();loadMistakeSlot();}

// 每日一练 + 错题本
function openQuiz(exs,topic){if(!exs||!exs.length)return;PD.push({type:'exercises',content:exs,topic:topic});showPreview(PD.length-1);}
var _dailyEx=null;
async function loadDailySlot(){var el=document.getElementById('daily-quiz-slot');if(!el)return;
  try{var d=await(await fetch('/api/daily-quiz')).json();if(!d.exercises||!d.exercises.length)return;
    _dailyEx=d.exercises;var today=new Date().toISOString().split('T')[0];
    el.innerHTML='<div class="hero" style="margin-bottom:16px"><div class="title">📅 每日一练'+(d.date===today?'':'（'+esc(d.date)+' 生成）')+'</div><p style="font-size:.85rem">守护进程根据你的薄弱点「'+esc((d.weak_points||[d.topic]).join('、'))+'」自动出了 '+d.exercises.length+' 道题</p><button class="btn" style="margin-top:8px" onclick="openQuiz(_dailyEx,\'每日一练\')">开始作答</button></div>';
  }catch(e){}}
async function loadMistakeSlot(){var el=document.getElementById('mistake-slot');if(!el)return;
  try{var d=await(await fetch('/api/mistakes?session_id='+encodeURIComponent(S.sid))).json();var ms=d.mistakes||[];if(!ms.length)return;
    var h='<div class="card" style="margin-bottom:16px"><h4>错题本（共 '+ms.length+' 题）</h4>';
    ms.slice(-8).reverse().forEach(function(m,i){h+='<div class="tl-item"><div class="dot low"></div><div class="bd"><div class="l1" style="cursor:pointer" onclick="var d=document.getElementById(\'mk-'+i+'\');d.style.display=d.style.display===\'none\'?\'block\':\'none\'">'+esc(m.question.substring(0,60))+'</div><div class="l2">'+esc(m.time||'')+' · '+esc(m.knowledge_point||m.topic||'')+'</div><div id="mk-'+i+'" style="display:none;font-size:.8rem;margin-top:6px">你的答案：<strong style="color:var(--rust)">'+esc(m.student_answer||'未作答')+'</strong> | 正确：<strong style="color:var(--sage)">'+esc(m.correct_answer)+'</strong>'+(m.explanation?'<div style="color:var(--muted);background:var(--paper);padding:5px 8px;border-radius:4px;margin-top:4px">💡 '+esc(m.explanation.substring(0,150))+'</div>':'')+'</div></div></div>';});
    h+='<div style="margin-top:10px"><button class="btn-sm" onclick="genReviewQuiz(this)" style="border-color:var(--accent);color:var(--accent)">🔄 生成复习卷（针对错题出变式题）</button></div></div>';
    el.innerHTML=h;
  }catch(e){}}
async function genReviewQuiz(btn){var old=btn.textContent;btn.textContent='生成中（约20秒）...';btn.disabled=true;
  try{var r=await(await fetch('/api/mistakes/review-quiz',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:S.sid})})).json();
    if(r.ok)openQuiz(r.exercises,'错题复习');else alert(r.error||'生成失败');
  }catch(e){alert('网络错误');}
  btn.textContent=old;btn.disabled=false;}

// Charts（ECharts：悬停看数值、动画、渐变）
function drawRadar(id,vals){var el=document.getElementById(id);if(!el)return;
  if(!window.echarts){el.innerHTML='<div style="color:var(--muted);font-size:.8rem;text-align:center;padding:100px 0">图表库加载失败，检查网络后刷新</div>';return;}
  var names=[['数学','线代/概率论'],['编程','Python代码力'],['ML基础','了解程度'],['难度','学习阶段'],['完成率','做题正确率']];
  echarts.init(el).setOption({
    tooltip:{confine:true,formatter:function(p){var v=p.value||[];return names.map(function(n,i){return n[0]+'：'+Math.round((v[i]||0)*100)+'%';}).join('<br>');}},
    radar:{radius:'62%',indicator:names.map(function(n){return{name:n[0],max:1};}),
      axisName:{color:'#1a2332',fontWeight:600,fontSize:12},
      splitArea:{areaStyle:{color:['#fffdf9','#faf6ee']}},
      splitLine:{lineStyle:{color:'#e6e0d4'}},axisLine:{lineStyle:{color:'#e6e0d4'}}},
    series:[{type:'radar',symbolSize:5,
      data:[{value:vals,name:'能力值'}],
      lineStyle:{color:'#bf9b4e',width:2.5},itemStyle:{color:'#bf9b4e'},
      areaStyle:{color:{type:'radial',x:.5,y:.5,r:.8,colorStops:[{offset:0,color:'rgba(191,155,78,.45)'},{offset:1,color:'rgba(191,155,78,.12)'}]}}}]
  });}
function drawChart(id,recs){var el=document.getElementById(id);if(!el)return;
  if(!window.echarts){el.innerHTML='<div style="color:var(--muted);font-size:.8rem;text-align:center;padding:60px 0">图表库加载失败，检查网络后刷新</div>';return;}
  var pts=recs.filter(function(r){return typeof r.score==='number';});
  if(pts.length<2){el.innerHTML='<div style="color:var(--muted);font-size:.85rem;text-align:center;padding:80px 0">需2次以上评估才有趋势</div>';return;}
  echarts.init(el).setOption({
    grid:{left:38,right:18,top:24,bottom:30},
    tooltip:{trigger:'axis',formatter:function(ps){var p=ps[0];var r=pts[p.dataIndex]||{};return (r.date||'')+' '+(r.topic||'')+'<br>得分：<b>'+p.value+'</b>（'+(r.correct||0)+'/'+(r.total||0)+' 正确）';}},
    xAxis:{type:'category',data:pts.map(function(r,i){return '第'+(i+1)+'次';}),axisLabel:{fontSize:10,color:'#8b8578'},axisLine:{lineStyle:{color:'#e6e0d4'}}},
    yAxis:{min:0,max:100,splitLine:{lineStyle:{color:'#f0ece2'}},axisLabel:{fontSize:10,color:'#8b8578'}},
    series:[{type:'line',data:pts.map(function(r){return r.score;}),smooth:true,symbolSize:7,
      label:{show:true,fontSize:10,color:'#8b8578'},
      lineStyle:{color:'#bf9b4e',width:3},itemStyle:{color:'#bf9b4e',borderColor:'#fff',borderWidth:2},
      areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(191,155,78,.3)'},{offset:1,color:'rgba(191,155,78,.02)'}]}},
      markLine:{silent:true,symbol:'none',lineStyle:{color:'#4a7c59',type:'dashed'},label:{formatter:'及格线',fontSize:10},data:[{yAxis:60}]}}]
  });}

// 会话恢复：刷新页面后从服务端拿回画像/路径/资源
async function loadHistory(){var cs=document.getElementById('chat-scroll');
  try{var d=await(await fetch('/api/session/'+encodeURIComponent(S.sid)+'/history')).json();
    var h=d.history||[];if(!h.length)return;  // 没历史就保留欢迎语
    cs.innerHTML='<div style="text-align:center;color:var(--muted);font-size:.74rem;padding:6px 0">— 已恢复之前的对话，想重新开始点右上角「重置」 —</div>';
    h.forEach(function(m){addMsg(m.role==='user'?'user':'assistant',m.role==='user'?esc(m.content):md(m.content));});
    cs.scrollTop=cs.scrollHeight;
  }catch(e){}}
async function restoreSession(){try{var d=await(await fetch('/api/profile?session_id='+encodeURIComponent(S.sid))).json();
  if(d.profile)S.profile=d.profile;if(d.learning_path)S.path=d.learning_path;
  var hist=d.resources_history||[];
  if(hist.length)S.allRes=hist.slice().reverse();  // 新的在前，和实时生成的顺序一致
  else if(d.resources&&!S.allRes.length)S.allRes=[d.resources];
}catch(e){}}

// 对话模型选择器
function loadModelSel(){fetch('/api/models').then(function(r){return r.json()}).then(function(d){
  var sel=document.getElementById('model-sel');if(!sel)return;
  var act=d.active||{};var h='<option value="">默认 · '+esc(act.model||act.service||'')+'</option>';
  (d.services||[]).forEach(function(s){
    // 只列设置页真正配置过的服务商（本地Ollama也要配置过才出现），和设置保持一致
    if(!(s.configured||(s.has_key&&!s.no_key)))return;
    var models=[];if(s.model)models.push(s.model);(s.known_models||[]).forEach(function(m){if(models.indexOf(m)<0)models.push(m);});
    if(!models.length)return;
    h+='<optgroup label="'+esc(s.label)+'">'+models.map(function(m){return'<option value="'+esc(s.id)+'||'+esc(m)+'">'+esc(m)+'</option>';}).join('')+'</optgroup>';});
  sel.innerHTML=h;
  // 恢复上次选的模型，模型没了就回落到默认
  if(S.chatModel&&S.chatModel.service){var v=S.chatModel.service+'||'+S.chatModel.model;
    if(sel.querySelector('option[value="'+v.replace(/"/g,'\\"')+'"]'))sel.value=v;else{S.chatModel=null;try{localStorage.removeItem('a3_model');}catch(e){}}}
}).catch(function(){});}
function pickModel(v){if(!v){S.chatModel=null;try{localStorage.removeItem('a3_model');}catch(e){}return;}
  var p=v.split('||');S.chatModel={service:p[0],model:p[1]||''};try{localStorage.setItem('a3_model',JSON.stringify(S.chatModel));}catch(e){}}

// 聊天教学模式选择
var SKL=[];
function loadSkills(cb){fetch('/api/skills').then(function(r){return r.json()}).then(function(d){SKL=d.skills||[];
  // 清掉已被删除的勾选
  S.skills=S.skills.filter(function(id){return SKL.some(function(s){return s.id===id;});});
  updateSkillBtn();if(cb)cb();}).catch(function(){if(cb)cb();});}
function updateSkillBtn(){var b=document.getElementById('skill-btn');if(!b)return;
  b.textContent=S.skills.length?('模式('+S.skills.length+')'):'模式';
  b.style.color=S.skills.length?'var(--accent)':'var(--muted)';b.style.borderColor=S.skills.length?'var(--accent)':'var(--border)';}
function toggleSkillPop(){var p=document.getElementById('skill-pop');
  if(p.style.display!=='none'){p.style.display='none';return;}
  loadSkills(function(){
    p.innerHTML='<div style="font-size:.78rem;color:var(--muted);margin-bottom:8px">勾选教学模式（也可以说话带关键词自动触发）</div>'+
      (SKL.length?SKL.map(function(s){return'<label style="display:block;padding:5px 2px;cursor:pointer;font-size:.84rem"><input type="checkbox" '+(S.skills.indexOf(s.id)>=0?'checked':'')+' onchange="toggleSkill(\''+esc(s.id)+'\',this.checked)"> <strong>'+esc(s.name)+'</strong> <span style="color:var(--muted);font-size:.76rem">'+esc(s.description)+'</span></label>';}).join(''):'<div style="font-size:.82rem;color:var(--muted)">还没有教学模式，去 设置→教学模式 创建</div>')+
      '<div style="margin-top:8px;text-align:right"><button class="btn-sm" onclick="document.getElementById(\'skill-pop\').style.display=\'none\'">关闭</button></div>';
    p.style.display='block';});}
function toggleSkill(id,on){if(on){if(S.skills.indexOf(id)<0)S.skills.push(id);}else{S.skills=S.skills.filter(function(x){return x!==id;});}
  try{localStorage.setItem('a3_skills',JSON.stringify(S.skills));}catch(e){}updateSkillBtn();}

// 设置页
var SET={tab:'models',data:null,editSvc:null,timer:null,testModels:null};
function renderSettings(){var el=document.getElementById('settings-el');
  var tabs=[{k:'models',l:'模型配置'},{k:'skills',l:'教学模式'},{k:'project',l:'项目设置'},{k:'env',l:'环境检测'},{k:'logs',l:'系统日志'},{k:'daemon',l:'守护进程'}];
  el.innerHTML='<div class="ph"><h2>设置</h2><p>模型、参数与系统状态</p></div><div class="set-tabs">'+tabs.map(function(t){return'<button class="'+(SET.tab===t.k?'on':'')+'" onclick="SET.tab=\''+t.k+'\';SET.editSvc=null;renderSettings()">'+t.l+'</button>';}).join('')+'</div><div id="set-body"><div style="color:var(--muted);font-size:.85rem"><span class="spin"></span> 加载中...</div></div>';
  if(SET.timer){clearInterval(SET.timer);SET.timer=null;}
  if(SET.tab==='models')renderModelSet();else if(SET.tab==='project')renderProjSet();
  else if(SET.tab==='skills')renderSkillSet();
  else if(SET.tab==='env')renderEnvSet(false);else if(SET.tab==='logs')renderLogSet();
  else if(SET.tab==='daemon')renderDaemonSet();}

// --- 模型配置 ---
async function renderModelSet(){var bd=document.getElementById('set-body');
  try{var d=await(await fetch('/api/models')).json();SET.data=d;}catch(e){bd.innerHTML='<div class="banner bad">加载失败: '+esc(String(e))+'</div>';return;}
  var act=SET.data.active||{};
  var h='<div class="banner ok">当前使用：'+esc(act.service||'?')+' / '+esc(act.model||'?')+'（切换立即生效，不用重启）</div>';
  h+='<div class="svc-grid">'+SET.data.services.map(function(s){
    var cls='svc-card'+(s.configured||s.has_key?' cfg':'')+(s.id===act.service?' act':'');
    var meta=s.has_key?('密钥 '+esc(s.key_preview)):(s.no_key?'本地运行，不需要密钥':'未配置密钥');
    return'<div class="'+cls+'" onclick="SET.editSvc=\''+s.id+'\';renderSettings()"><div class="sname"><span class="sdot2"></span>'+esc(s.label)+(s.id===act.service?' <span style="font-size:.68rem;color:var(--sage)">使用中</span>':'')+'</div><div class="smeta">'+meta+(s.model?'<br>模型: '+esc(s.model):'')+'</div></div>';}).join('')+'</div>';
  bd.innerHTML=h;
  if(SET.editSvc)bd.insertAdjacentHTML('beforeend',svcFormHTML(SET.editSvc));}

function svcFormHTML(sid){var s=null;SET.data.services.forEach(function(x){if(x.id===sid)s=x;});if(!s)return'';
  var models=SET.testModels||[];if(!models.length){if(s.model)models.push(s.model);(s.known_models||[]).forEach(function(m){if(models.indexOf(m)<0)models.push(m);});}
  var mOpts=models.map(function(m){return'<option value="'+esc(m)+'"'+(m===s.model?' selected':'')+'>'+esc(m)+'</option>';}).join('');
  return'<div class="set-form" id="svc-form"><h3 style="font-size:1rem;margin-bottom:12px">配置 '+esc(s.label)+'</h3>'+
    (s.no_key?'':'<div class="fr"><label>API 密钥'+(s.has_key?'（已保存 '+esc(s.key_preview)+'，留空表示不改）':'')+'</label><div class="key-wrap"><input type="password" id="mf-key" placeholder="sk-..."><button class="eye" onclick="var i=document.getElementById(\'mf-key\');i.type=i.type===\'password\'?\'text\':\'password\'">&#128065;</button></div></div>')+
    '<div class="fr"><label>接口地址'+(sid==='custom'?'（必填）':'（一般不用改）')+'</label><input type="text" id="mf-url" value="'+esc(s.base_url)+'"></div>'+
    '<div class="fr"><label>协议格式（国内厂商都是 OpenAI 兼容；Claude 官方接口选 Anthropic。不确定就点"测试连接"自动识别）</label><select id="mf-fmt"><option value="openai"'+(s.api_format!=='anthropic'?' selected':'')+'>OpenAI 兼容</option><option value="anthropic"'+(s.api_format==='anthropic'?' selected':'')+'>Anthropic (Claude)</option></select></div>'+
    '<div class="fr"><label>模型（点"测试连接"可拉取该服务商的完整模型列表）</label><select id="mf-model">'+mOpts+'</select></div>'+
    '<div id="mf-status" style="font-size:.82rem;margin-bottom:10px"></div>'+
    '<div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn-sm" onclick="testSvc(\''+sid+'\')">测试连接</button><button class="btn" style="padding:7px 18px" onclick="saveSvc(\''+sid+'\')">保存</button><button class="btn-sm" onclick="activateSvc(\''+sid+'\')" style="border-color:var(--sage);color:var(--sage)">保存并设为当前</button>'+((s.configured||s.has_key)?'<button class="btn-sm" onclick="delSvc(\''+sid+'\')" style="border-color:var(--rust);color:var(--rust)">删除配置</button>':'')+'<button class="btn-sm" onclick="SET.editSvc=null;SET.testModels=null;renderSettings()">收起</button></div></div>';}

async function testSvc(sid){var st=document.getElementById('mf-status');st.innerHTML='<span class="spin"></span> 正在连接...';
  var body={service:sid,api_key:(document.getElementById('mf-key')||{}).value||'',base_url:(document.getElementById('mf-url')||{}).value||''};
  try{var r=await(await fetch('/api/models/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
    if(r.ok){st.innerHTML='<span style="color:var(--sage)">连接成功'+(r.note?'（'+esc(r.note)+'）':'，已拉取 '+(r.models||[]).length+' 个模型')+'</span>';
      if(r.detected_format&&document.getElementById('mf-fmt'))document.getElementById('mf-fmt').value=r.detected_format;
      if(r.models&&r.models.length){SET.testModels=r.models;var cur=(document.getElementById('mf-model')||{}).value;document.getElementById('mf-model').innerHTML=r.models.map(function(m){return'<option value="'+esc(m)+'"'+(m===cur?' selected':'')+'>'+esc(m)+'</option>';}).join('');}}
    else st.innerHTML='<span style="color:var(--rust)">连接失败: '+esc(r.error||'')+'</span>';
  }catch(e){st.innerHTML='<span style="color:var(--rust)">网络错误</span>';}}

async function saveSvc(sid,thenActivate){var body={service:sid,api_key:(document.getElementById('mf-key')||{}).value||'',base_url:(document.getElementById('mf-url')||{}).value||'',model:(document.getElementById('mf-model')||{}).value||'',api_format:(document.getElementById('mf-fmt')||{}).value||''};
  if(SET.testModels&&SET.testModels.length)body.models=SET.testModels;
  try{var r=await(await fetch('/api/models/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
    if(!r.ok){alert('保存失败: '+(r.error||''));return false;}
    if(!thenActivate){SET.editSvc=null;SET.testModels=null;renderSettings();loadModelSel();}
    return true;
  }catch(e){alert('网络错误');return false;}}

async function activateSvc(sid){if(!(await saveSvc(sid,true)))return;
  var model=(document.getElementById('mf-model')||{}).value||'';
  try{var r=await(await fetch('/api/models/activate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({service:sid,model:model})})).json();
    if(!r.ok){alert('切换失败: '+(r.error||''));return;}
    SET.editSvc=null;SET.testModels=null;renderSettings();loadModelSel();
  }catch(e){alert('网络错误');}}

async function delSvc(sid){if(!confirm('确定删除这个服务商的配置和密钥吗？'))return;
  try{await fetch('/api/models/'+sid,{method:'DELETE'});SET.editSvc=null;SET.testModels=null;renderSettings();loadModelSel();}catch(e){alert('网络错误');}}

// --- 教学模式管理 ---
async function renderSkillSet(editId){var bd=document.getElementById('set-body');
  try{var d=await(await fetch('/api/skills')).json();SKL=d.skills||[];}catch(e){bd.innerHTML='<div class="banner bad">加载失败</div>';return;}
  var h='<div class="banner ok">教学模式 = 给 AI 的一套教学规则。聊天时点「模式」勾选启用，或者说话带触发关键词自动启用</div>';
  h+='<div class="svc-grid">'+SKL.map(function(s){return'<div class="svc-card cfg" onclick="renderSkillSet(\''+esc(s.id)+'\')"><div class="sname"><span class="sdot2"></span>'+esc(s.name)+'</div><div class="smeta">'+esc(s.description)+(s.triggers&&s.triggers.length?'<br>触发词: '+esc(s.triggers.join('、')):'')+'</div></div>';}).join('')+
    '<div class="svc-card" onclick="renderSkillSet(\'__new__\')" style="display:flex;align-items:center;justify-content:center;color:var(--muted)">+ 新建模式</div></div>';
  var ed=null;if(editId&&editId!=='__new__')SKL.forEach(function(s){if(s.id===editId)ed=s;});
  if(editId){h+='<div class="set-form"><h3 style="font-size:1rem;margin-bottom:12px">'+(ed?'编辑：'+esc(ed.name):'新建教学模式')+'</h3>'+
    '<div class="fr"><label>ID（英文，作为文件夹名'+(ed?'，不可改':'')+'）</label><input type="text" id="sk-id" value="'+esc(ed?ed.id:'')+'"'+(ed?' readonly style="background:#eee"':'')+' placeholder="例如 code-practice"></div>'+
    '<div class="fr"><label>名称</label><input type="text" id="sk-name" value="'+esc(ed?ed.name:'')+'" placeholder="例如 代码实战"></div>'+
    '<div class="fr"><label>一句话说明</label><input type="text" id="sk-desc" value="'+esc(ed?ed.description:'')+'"></div>'+
    '<div class="fr"><label>触发关键词（逗号分隔，用户的话里带这些词就自动启用）</label><input type="text" id="sk-trig" value="'+esc(ed?(ed.triggers||[]).join(', '):'')+'" placeholder="例如 写代码, 实战, 动手"></div>'+
    '<div class="fr"><label>教学规则（给 AI 看的，写清楚要怎么教）</label><textarea id="sk-body" style="width:100%;min-height:160px;padding:10px 12px;border:1px solid var(--border);border-radius:6px;font-size:.85rem;background:var(--paper);font-family:inherit">'+esc(ed?ed.body:'')+'</textarea></div>'+
    '<div id="sk-status" style="font-size:.82rem;margin-bottom:10px"></div>'+
    '<div style="display:flex;gap:8px"><button class="btn" onclick="saveSkillForm()">保存</button>'+(ed?'<button class="btn-sm" onclick="delSkillForm(\''+esc(ed.id)+'\')" style="border-color:var(--rust);color:var(--rust)">删除</button>':'')+'<button class="btn-sm" onclick="renderSkillSet()">收起</button></div></div>';}
  bd.innerHTML=h;}
async function saveSkillForm(){var st=document.getElementById('sk-status');
  var body={id:document.getElementById('sk-id').value,name:document.getElementById('sk-name').value,description:document.getElementById('sk-desc').value,triggers:document.getElementById('sk-trig').value,body:document.getElementById('sk-body').value};
  try{var r=await(await fetch('/api/skills',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
    if(r.ok){renderSkillSet();loadSkills();}else st.innerHTML='<span style="color:var(--rust)">'+esc(r.error||'保存失败')+'</span>';
  }catch(e){st.innerHTML='<span style="color:var(--rust)">网络错误</span>';}}
async function delSkillForm(id){if(!confirm('确定删除这个教学模式吗？'))return;
  try{await fetch('/api/skills/'+id,{method:'DELETE'});renderSkillSet();loadSkills();}catch(e){alert('网络错误');}}

// --- 项目设置 ---
async function renderProjSet(){var bd=document.getElementById('set-body');
  try{var d=await(await fetch('/api/project-settings')).json();}catch(e){bd.innerHTML='<div class="banner bad">加载失败</div>';return;}
  function fr(label,id,val,step){return'<div class="fr"><label>'+label+'</label><input type="'+(step?'number':'text')+'"'+(step?' step="'+step+'"':'')+' id="'+id+'" value="'+esc(String(val))+'"></div>';}
  bd.innerHTML='<div class="set-form"><h3 style="font-size:1rem;margin-bottom:12px">课程信息</h3>'+
    fr('课程名称','ps-course',d.course_name)+fr('课程描述','ps-desc',d.course_description)+'</div>'+
    '<div class="set-form"><h3 style="font-size:1rem;margin-bottom:12px">知识检索参数</h3>'+
    fr('每次检索的片段数 top_k（越大参考越多但越慢）','ps-topk',d.rag_top_k,'1')+
    fr('相似度阈值（0-1，越高越严格）','ps-thr',d.rag_similarity_threshold,'0.05')+'</div>'+
    '<div class="set-form"><h3 style="font-size:1rem;margin-bottom:12px">生成参数（温度 0-2，越高越有创意、越低越严谨）</h3>'+
    fr('资源生成温度','ps-t1',d.temp_resource_generation,'0.1')+fr('辅导答疑温度','ps-t2',d.temp_tutoring,'0.1')+fr('评估打分温度','ps-t3',d.temp_evaluation,'0.1')+
    fr('LLM 失败重试次数','ps-retry',d.max_llm_retries,'1')+'</div>'+
    '<div id="ps-status" style="font-size:.82rem;margin-bottom:10px"></div><button class="btn" onclick="saveProjSet()">保存设置（立即生效）</button>';}

async function saveProjSet(){var st=document.getElementById('ps-status');
  var body={course_name:document.getElementById('ps-course').value,course_description:document.getElementById('ps-desc').value,
    rag_top_k:document.getElementById('ps-topk').value,rag_similarity_threshold:document.getElementById('ps-thr').value,
    temp_resource_generation:document.getElementById('ps-t1').value,temp_tutoring:document.getElementById('ps-t2').value,
    temp_evaluation:document.getElementById('ps-t3').value,max_llm_retries:document.getElementById('ps-retry').value};
  try{var r=await(await fetch('/api/project-settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
    st.innerHTML=r.ok?'<span style="color:var(--sage)">已保存并生效</span>':'<span style="color:var(--rust)">'+esc(r.error||'保存失败')+'</span>';
  }catch(e){st.innerHTML='<span style="color:var(--rust)">网络错误</span>';}}

// --- 环境检测 ---
async function renderEnvSet(deep){var bd=document.getElementById('set-body');
  bd.innerHTML='<div style="color:var(--muted);font-size:.85rem"><span class="spin"></span> 正在体检'+(deep?'（含模型接口连通测试，稍等几秒）':'')+'...</div>';
  try{var d=await(await fetch('/api/env-check'+(deep?'?deep=true':''))).json();}catch(e){bd.innerHTML='<div class="banner bad">检测失败</div>';return;}
  var h='<div class="banner '+(d.all_ok?'ok':'warn')+'">'+(d.all_ok?'✓ 全部检查通过，系统状态良好':'⚠ 部分检查未通过，看下面红叉的项')+'</div>';
  h+='<div class="card">'+d.checks.map(function(c){return'<div class="check-row"><div class="ci '+(c.ok?'ok':'bad')+'">'+(c.ok?'✓':'✗')+'</div><div class="cl">'+esc(c.label)+'</div><div class="cd">'+esc(c.detail)+'</div></div>';}).join('')+'</div>';
  h+='<div style="margin-top:14px;display:flex;gap:8px"><button class="btn-sm" onclick="renderEnvSet(false)">重新检测</button><button class="btn-sm" onclick="renderEnvSet(true)" style="border-color:var(--accent);color:var(--accent)">深度检测（含模型接口连通）</button></div>';
  bd.innerHTML=h;}

// --- 系统日志 ---
var LOGF={level:'',source:''};
async function renderLogSet(){var bd=document.getElementById('set-body');
  try{var d=await(await fetch('/api/logs?n=200'+(LOGF.level?'&level='+LOGF.level:'')+(LOGF.source?'&source='+encodeURIComponent(LOGF.source):''))).json();}catch(e){bd.innerHTML='<div class="banner bad">加载失败</div>';return;}
  var st=d.stats||{};var up=st.uptime_seconds||0;var upTxt=up>3600?Math.floor(up/3600)+'小时'+Math.floor(up%3600/60)+'分':Math.floor(up/60)+'分钟';
  var h='<div class="stat-grid"><div class="stat-card"><div class="num">'+upTxt+'</div><div class="lbl">运行时长</div></div><div class="stat-card"><div class="num">'+(st.total_logs||0)+'</div><div class="lbl">日志条数</div></div><div class="stat-card"><div class="num" style="color:'+((st.warnings||0)>0?'#a06a1f':'inherit')+'">'+(st.warnings||0)+'</div><div class="lbl">警告</div></div><div class="stat-card"><div class="num" style="color:'+((st.errors||0)>0?'var(--rust)':'inherit')+'">'+(st.errors||0)+'</div><div class="lbl">错误</div></div></div>';
  h+='<div style="display:flex;gap:8px;margin-bottom:10px;align-items:center;flex-wrap:wrap"><select id="lg-level" onchange="LOGF.level=this.value;renderLogSet()" style="padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:.8rem"><option value="">全部级别</option><option'+(LOGF.level==='INFO'?' selected':'')+'>INFO</option><option'+(LOGF.level==='WARN'?' selected':'')+'>WARN</option><option'+(LOGF.level==='ERROR'?' selected':'')+'>ERROR</option></select>'+
    '<select id="lg-source" onchange="LOGF.source=this.value;renderLogSet()" style="padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:.8rem"><option value="">全部来源</option>'+(d.sources||[]).map(function(s){return'<option'+(LOGF.source===s?' selected':'')+'>'+esc(s)+'</option>';}).join('')+'</select>'+
    '<button class="btn-sm" onclick="renderLogSet()">刷新</button><label style="font-size:.78rem;color:var(--muted)"><input type="checkbox" id="lg-auto" '+(SET.timer?'checked':'')+' onchange="toggleLogAuto(this.checked)"> 自动刷新(5秒)</label><span style="font-size:.74rem;color:var(--muted)">日志文件在 db/logs/ 目录按天保存</span></div>';
  var logs=(d.logs||[]).slice().reverse();
  h+='<div class="card" style="padding:8px 10px;max-height:55vh;overflow-y:auto">'+(logs.length?logs.map(function(l){return'<div class="log-line"><span class="lt">'+esc((l.time||'').slice(11))+'</span><span class="lv '+esc(l.level)+'">'+esc(l.level)+'</span><span class="ls">['+esc(l.source||'')+']</span><span class="lm">'+esc(l.message)+'</span></div>';}).join(''):'<div style="color:var(--muted);font-size:.85rem;padding:16px;text-align:center">暂无日志</div>')+'</div>';
  bd.innerHTML=h;}
function toggleLogAuto(on){if(SET.timer){clearInterval(SET.timer);SET.timer=null;}
  if(on)SET.timer=setInterval(function(){if(SET.tab==='logs'&&document.getElementById('page-settings').classList.contains('show'))renderLogSet();},5000);}

// --- 守护进程 ---
async function renderDaemonSet(){var bd=document.getElementById('set-body');
  try{var d=await(await fetch('/api/daemon')).json();}catch(e){bd.innerHTML='<div class="banner bad">加载失败</div>';return;}
  var up=d.uptime_seconds||0;var upTxt=up>3600?Math.floor(up/3600)+'小时'+Math.floor(up%3600/60)+'分':Math.floor(up/60)+'分钟';
  var h='<div class="card" style="margin-bottom:14px"><div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px"><div><span class="dstat '+(d.running?'run':'off')+'">'+(d.running?'● 运行中':'○ 已停止')+'</span><span style="font-size:.8rem;color:var(--muted);margin-left:12px">'+(d.running?'已运行 '+upTxt+'，每 '+Math.round((d.check_interval||300)/60)+' 分钟自动巡检一次':'守护进程负责定期检查模型接口、知识库、磁盘，并自动保存会话')+'</span></div>'+
    '<button class="btn'+(d.running?'':'')+'" style="'+(d.running?'background:var(--rust)':'background:var(--sage)')+'" onclick="daemonCtl(\''+(d.running?'stop':'start')+'\')">'+(d.running?'停止':'启动')+'</button></div>'+
    (d.last_check?'<div style="font-size:.78rem;color:var(--muted);margin-top:8px">上次巡检: '+esc(d.last_check)+(d.consecutive_fails>0?' · <span style="color:var(--rust)">连续 '+d.consecutive_fails+' 轮发现问题</span>':' · 一切正常')+'</div>':'')+'</div>';
  var evs=(d.events||[]).slice().reverse();
  h+='<div class="card"><h4>巡检事件（最近20条）</h4>'+(evs.length?evs.map(function(e){return'<div class="log-line"><span class="lt">'+esc(e.time)+'</span><span class="lv '+(e.ok?'INFO':'WARN')+'">'+esc(e.kind)+'</span><span class="lm"'+(e.ok?'':' style="color:var(--rust)"')+'>'+esc(e.message)+'</span></div>';}).join(''):'<div style="color:var(--muted);font-size:.85rem;padding:10px">暂无事件</div>')+'</div>';
  h+='<div style="margin-top:12px"><button class="btn-sm" onclick="renderDaemonSet()">刷新</button></div>';
  bd.innerHTML=h;}
async function daemonCtl(act){try{var r=await(await fetch('/api/daemon/'+act,{method:'POST'})).json();if(!r.ok&&r.error)alert(r.error);}catch(e){}renderDaemonSet();}

async function resetAll(){
try{await fetch('/api/reset?session_id='+S.sid);}catch(e){}S.sid='u'+Date.now();S.profile=null;S.resources=null;S.path=null;S.recs=[];S.allRes=[];S.quizResults={};try{localStorage.setItem('a3_sid',S.sid);localStorage.removeItem('a3_recs');localStorage.removeItem('a3_quiz');}catch(e){};document.getElementById('chat-scroll').innerHTML='';go('chat');location.reload();}
function closeModal(){M.classList.remove('show');M.querySelector('.modal-inner').style.maxWidth='';}
M.onclick=function(e){if(e.target===this)closeModal();};
