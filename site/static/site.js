(() => {
  const rescueCss = document.createElement('link');
  rescueCss.rel = 'stylesheet';
  rescueCss.href = '/static/visual-rescue.css';
  document.head.appendChild(rescueCss);

  const hero = document.querySelector('.hero');
  const sticky = document.querySelector('[data-sticky]');
  const trial = document.querySelector('#trial');
  const form = document.querySelector('#lead-form');
  const phone = form?.querySelector('input[name="phone"]');
  let source = 'callback_block';
  let leadType = 'trial_now';

  const heroTitle = hero?.querySelector('h1');
  if (heroTitle) heroTitle.innerHTML = 'Первый шаг в<br><em>гимнастику</em>';

  const trialCopy = trial?.querySelector('.trial-copy > p');
  if (trialCopy) trialCopy.textContent = 'Администратор поможет выбрать подходящую группу, ответит на вопросы и согласует удобное время.';

  const polechkaActions = document.querySelector('.polechka-actions');
  if (polechkaActions) {
    const links = [...polechkaActions.querySelectorAll('a')];
    const clubLink = links.find((link) => link.hasAttribute('data-callback'));
    const watchLink = links.find((link) => !link.hasAttribute('data-callback'));
    if (clubLink) {
      clubLink.textContent = 'Попробовать в клубе';
      clubLink.className = 'btn light';
    }
    if (watchLink) {
      watchLink.textContent = 'Смотреть Полечку на YouTube';
      watchLink.href = 'https://www.youtube.com/channel/UCONm9-FBKX-27uhrf647ZCQ';
      watchLink.className = 'btn ghost';
    }
    if (clubLink && watchLink) polechkaActions.replaceChildren(clubLink, watchLink);
  }

  const faq = document.querySelector('#faq');
  if (faq && !document.querySelector('.article-teaser')) {
    const section = document.createElement('section');
    section.className = 'section article-teaser';
    section.setAttribute('aria-labelledby', 'article-teaser-title');
    section.innerHTML = `
      <div class="shell article-teaser-grid">
        <div class="article-teaser-card">
          <span class="eyebrow">РОДИТЕЛЯМ · 5 МИНУТ ЧТЕНИЯ</span>
          <h2 id="article-teaser-title">Гимнастика с 3 лет:<br><span class="serif">когда ребёнок готов</span></h2>
          <p>Разобрали самые частые вопросы перед первым занятием: возраст, адаптацию к группе и тренеру, признаки интереса и то, как поддержать ребёнка без давления.</p>
          <div class="article-teaser-points">
            <span>Как понять, что в 3 года уже можно начинать</span>
            <span>Что нормально на первых занятиях и в период адаптации</span>
            <span>Как сохранить интерес и не превратить спорт в обязанность</span>
          </div>
          <a class="btn" href="/article/hudozhestvennaya-gimnastika-s-3-let">Читать статью</a>
        </div>
        <div class="article-teaser-mark" aria-hidden="true"></div>
      </div>`;
    faq.before(section);
  }

  const telegramUrl = (document.body.dataset.telegramUrl || '').trim();
  const telegramForSource = (src) => {
    if (!telegramUrl) return '';
    try {
      const url = new URL(telegramUrl);
      if (url.hostname === 't.me' && url.searchParams.has('start')) {
        url.searchParams.set('start', (src || 'site').slice(0, 64).replace(/[^A-Za-z0-9_-]/g, '_'));
      }
      return url.toString();
    } catch (_) {
      return telegramUrl;
    }
  };

  const setLeadType = (value) => {
    leadType = value === 'future_group' ? 'future_group' : 'trial_now';
    form?.querySelectorAll('input[name="lead_type"]').forEach((input) => {
      input.checked = input.value === leadType;
    });
  };

  form?.querySelectorAll('input[name="lead_type"]').forEach((input) => {
    input.addEventListener('change', () => {
      if (input.checked) setLeadType(input.value);
    });
  });

  if (hero && sticky) {
    let heroVisible = true;
    let trialVisible = false;
    const syncSticky = () => {
      sticky.classList.toggle('is-visible', !heroVisible && !trialVisible);
      sticky.classList.toggle('is-suppressed', trialVisible);
    };
    new IntersectionObserver(([entry]) => {
      heroVisible = entry.isIntersecting;
      syncSticky();
    }, { threshold: 0.12 }).observe(hero);
    if (trial) {
      new IntersectionObserver(([entry]) => {
        trialVisible = entry.isIntersecting;
        syncSticky();
      }, { threshold: 0.08 }).observe(trial);
    }
  }

  document.querySelectorAll('[data-callback]').forEach((link) => {
    link.addEventListener('click', () => {
      source = link.dataset.source || 'callback_block';
      setLeadType(link.dataset.leadType || (source.includes('group_6_10') ? 'future_group' : 'trial_now'));
      const sourceInput = form?.querySelector('input[name="source"]');
      if (sourceInput) sourceInput.value = source;
      window.setTimeout(() => phone?.focus({ preventScroll: true }), 450);
    });
  });

  document.querySelectorAll('[data-telegram-link]').forEach((link) => {
    link.addEventListener('click', (event) => {
      const href = telegramForSource(link.dataset.source || 'site');
      if (!href) return;
      event.preventDefault();
      window.location.href = href;
    });
  });

  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = form.querySelector('.form-status');
    const button = form.querySelector('button[type="submit"]');
    const payload = Object.fromEntries(new FormData(form).entries());
    payload.page = location.pathname;
    payload.referrer = document.referrer;
    payload.preferred_channel = 'callback';
    payload.source = payload.source || source;
    payload.lead_type = payload.lead_type || leadType;
    payload.utm = Object.fromEntries(
      [...new URLSearchParams(location.search)].filter(([key]) => key.startsWith('utm_'))
    );

    status.textContent = 'Отправляем…';
    button.disabled = true;
    try {
      const response = await fetch('/api/leads', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error('lead_submit_failed');
      status.textContent = payload.lead_type === 'future_group'
        ? 'Готово. Мы сохранили заявку и сообщим о наборе в старшую группу.'
        : 'Готово. Администратор свяжется с вами для записи на пробное.';
      form.reset();
      source = 'callback_block';
      const sourceInput = form.querySelector('input[name="source"]');
      if (sourceInput) sourceInput.value = source;
      setLeadType('trial_now');
    } catch (_) {
      status.textContent = 'Не получилось отправить заявку. Попробуйте ещё раз или напишите в Telegram.';
    } finally {
      button.disabled = false;
    }
  });
})();