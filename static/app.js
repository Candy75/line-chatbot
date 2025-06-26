const chatBox = document.getElementById('chat');
const input   = document.getElementById('msg');
const btn     = document.getElementById('send');

function append(role, text) {
  const p = document.createElement('p');
  p.className = role;
  p.textContent = (role==='user'?'你：':'機器人：') + text;
  chatBox.appendChild(p);
  chatBox.scrollTop = chatBox.scrollHeight;
}

btn.onclick = async () => {
  const msg = input.value.trim();
  if (!msg) return;
  append('user', msg);
  input.value = '';
  
  // 呼叫後端
  const res = await fetch('/chat', {
    method:'POST',
    headers:{ 'Content-Type':'application/json' },
    body: JSON.stringify({ message: msg })
  });
  const data = await res.json();
  append('bot', data.reply);
};
