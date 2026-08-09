(() => {
  const hero=document.querySelector('.hero'), sticky=document.querySelector('[data-sticky]'), sheet=document.querySelector('[data-sheet]'), form=document.querySelector('#lead-form');
  let source='unknown';
  const telegramUrl=(document.body.dataset.telegramUrl||'').trim();
  if(hero&&sticky){new IntersectionObserver(([e])=>sticky.classList.toggle('is-visible',!e.isIntersecting),{threshold:.12}).observe(hero)}
  document.querySelectorAll('[data-telegram]').forEach(btn=>btn.addEventListener('click',()=>{
    source=btn.dataset.source||'unknown';
    if(telegramUrl){window.location.href=telegramUrl;return}
    sheet?.classList.add('open');sheet?.setAttribute('aria-hidden','false');document.body.style.overflow='hidden';if(form?.source)form.source.value=source;
  }));
  document.querySelectorAll('[data-connect]').forEach(btn=>btn.addEventListener('click',()=>{source=btn.dataset.source||'unknown';sheet?.classList.add('open');sheet?.setAttribute('aria-hidden','false');document.body.style.overflow='hidden';if(form?.source)form.source.value=source}));
  const close=()=>{sheet?.classList.remove('open');sheet?.setAttribute('aria-hidden','true');document.body.style.overflow=''};
  document.querySelector('[data-close]')?.addEventListener('click',close);sheet?.addEventListener('click',e=>{if(e.target===sheet)close()});document.addEventListener('keydown',e=>{if(e.key==='Escape')close()});
  form?.addEventListener('submit',async e=>{e.preventDefault();const status=form.querySelector('.form-status'),button=form.querySelector('button[type=submit]');status.textContent='Отправляем…';button.disabled=true;
    const payload=Object.fromEntries(new FormData(form).entries());payload.page=location.pathname;payload.referrer=document.referrer;payload.preferred_channel='callback';payload.utm=Object.fromEntries([...new URLSearchParams(location.search)].filter(([k])=>k.startsWith('utm_')));
    try{const r=await fetch('/api/leads',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!r.ok)throw new Error();status.textContent='Готово. Заявка сохранена — мы свяжемся с вами.';form.reset();form.source.value=source}
    catch(_){status.textContent='Не получилось отправить. Напишите нам в Telegram — там ответим быстрее.'}finally{button.disabled=false}});
})();
