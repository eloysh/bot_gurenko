const tg = window.Telegram?.WebApp;
if (tg) tg.ready();

function qs(id){ return document.getElementById(id); }
function setBadge(text){ qs("statusBadge").textContent = text; }

function getTgId(){
  const id = tg?.initDataUnsafe?.user?.id;
  return id ? Number(id) : null;
}

async function api(path, opts={}){
  const r = await fetch(path, {
    headers: { "Content-Type":"application/json" },
    ...opts
  });
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(typeof data === "string" ? data : JSON.stringify(data));
  return data;
}

function fillSelect(sel, items){
  sel.innerHTML = "";
  for (const it of items){
    const opt = document.createElement("option");
    opt.value = it.id;
    opt.textContent = it.title || it.id;
    sel.appendChild(opt);
  }
}

async function init(){
  try{
    setBadge("Loading…");

    const models = await api("/api/models");
    fillSelect(qs("chatModel"), models.chat || []);
    fillSelect(qs("imageModel"), models.image || []);
    fillSelect(qs("videoModel"), models.video || []);
    fillSelect(qs("musicModel"), models.music || []);

    const tgId = getTgId();
    if (!tgId){
      qs("userLine").textContent = "Telegram ID не найден (открой Mini App из Telegram)";
      setBadge("NO TG");
    } else {
      const me = await api(`/api/me?tg_id=${tgId}`);
      qs("userLine").textContent = `tg_id: ${me.tg_id} • free: ${me.free_credits} • pro: ${me.pro_credits}`;
      setBadge("OK");
    }

  }catch(e){
    console.error(e);
    qs("userLine").textContent = "Ошибка загрузки: " + e.message;
    setBadge("ERR");
  }
}

function tabs(){
  document.querySelectorAll(".tab").forEach(btn=>{
    btn.addEventListener("click", ()=>{
      document.querySelectorAll(".tab").forEach(b=>b.classList.remove("active"));
      btn.classList.add("active");
      const t = btn.dataset.tab;
      ["chat","image","video","music"].forEach(x=>{
        qs(`panel-${x}`).classList.toggle("hidden", x!==t);
      });
    });
  });
}

async function chatSend(){
  const out = qs("chatOut");
  out.textContent = "…";
  try{
    const model = qs("chatModel").value;
    const message = qs("chatInput").value.trim();
    const data = await api("/api/chat", { method:"POST", body: JSON.stringify({ model, message })});
    out.textContent = data.text || "(нет текста)";
  }catch(e){
    out.textContent = "Ошибка: " + e.message;
  }
}

async function pollResult(kind, jobId, outEl){
  const start = Date.now();
  outEl.textContent = `Задача создана: ${jobId}\nОжидаю результат…`;

  while(true){
    await new Promise(r=>setTimeout(r, 3000));
    const data = await api(`/api/${kind}/result/${jobId}`);
    if (data.status === "done" && data.url){
      outEl.innerHTML = `Готово ✅\n<a href="${data.url}" target="_blank">Открыть результат</a>`;
      return;
    }
    const sec = Math.floor((Date.now()-start)/1000);
    outEl.textContent = `Ожидаю… ${sec}s\nstatus=${data.status}\n${data.url ? data.url : ""}`;
    if (sec > 7200){
      outEl.textContent = "Таймаут ожидания результата.";
      return;
    }
  }
}

async function imageSend(){
  const out = qs("imageOut");
  out.textContent = "…";
  try{
    const model = qs("imageModel").value;
    const prompt = qs("imagePrompt").value.trim();
    const data = await api("/api/image/submit", { method:"POST", body: JSON.stringify({ model, prompt })});
    if (data.status === "done" && data.url){
      out.innerHTML = `Готово ✅\n<a href="${data.url}" target="_blank">Открыть картинку</a>`;
      return;
    }
    await pollResult("image", data.job_id, out);
  }catch(e){
    out.textContent = "Ошибка: " + e.message;
  }
}

async function videoSend(){
  const out = qs("videoOut");
  out.textContent = "…";
  try{
    const model = qs("videoModel").value;
    const prompt = qs("videoPrompt").value.trim();
    const data = await api("/api/video/submit", { method:"POST", body: JSON.stringify({ model, prompt })});
    if (data.status === "done" && data.url){
      out.innerHTML = `Готово ✅\n<a href="${data.url}" target="_blank">Открыть видео</a>`;
      return;
    }
    await pollResult("video", data.job_id, out);
  }catch(e){
    out.textContent = "Ошибка: " + e.message;
  }
}

async function musicSend(){
  const out = qs("musicOut");
  out.textContent = "…";
  try{
    const model = qs("musicModel").value;
    const lyrics = qs("musicLyrics").value.trim();
    const style = qs("musicStyle").value.trim();
    const data = await api("/api/music/submit", { method:"POST", body: JSON.stringify({ model, lyrics, style })});
    if (data.status === "done" && data.url){
      out.innerHTML = `Готово ✅\n<a href="${data.url}" target="_blank">Открыть музыку</a>`;
      return;
    }
    await pollResult("music", data.job_id, out);
  }catch(e){
    out.textContent = "Ошибка: " + e.message;
  }
}

tabs();
qs("chatSend").addEventListener("click", chatSend);
qs("imageSend").addEventListener("click", imageSend);
qs("videoSend").addEventListener("click", videoSend);
qs("musicSend").addEventListener("click", musicSend);

init();
