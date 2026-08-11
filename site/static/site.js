(() => {
  const enhancementCss = document.createElement('link');
  enhancementCss.rel = 'stylesheet';
  enhancementCss.href = '/static/conversion-v2.css';
  document.head.appendChild(enhancementCss);

  const hero = document.querySelector('.hero');
  const sticky = document.querySelector('[data-sticky]');
  const form = document.querySelector('#lead-form');
  const phone = form?.querySelector('input[name="phone"]');
  let source = 'callback_block';
  let leadType = 'trial_now';

  const leadTypeLabels = {
    trial_now: 'Запись в младшую группу · 3–6 лет',
    future_group: 'Заявка в будущую старшую группу',
  };

  const telegramUrl = (document.body.dataset.telegramUrl || '').trim();
  const telegramForSource = (src) => {
    if (!telegramUrl) return '';
    try {
      const url = new URL(telegramUrl);
      if (url.hostname === 't.me' && url.searchParams.has('start')) {
        url.searchParams.set(
          'start',
          (src || 'site').slice(0, 64).replace(/[^A-Za-z0-9_-]/g, '_')
        );
      }
      return url.toString();
    } catch (_) {
      return telegramUrl;
    }
  };

  const intentForSource = (src) => {
    if ((src || '').includes('group_6_10') || (src || '').includes('future')) return 'future_group';
    return 'trial_now';
  };

  const setLeadType = (value) => {
    leadType = value === 'future_group' ? 'future_group' : 'trial_now';
    form?.querySelectorAll('input[name="lead_type"]').forEach((input) => {
      input.checked = input.value === leadType;
    });
    const note = form?.querySelector('.form-intent-note');
    if (note) note.textContent = leadTypeLabels[leadType];
  };

  if (form) {
    const existingLeadType = form.querySelector('input[name="lead_type"]');
    if (existingLeadType) existingLeadType.remove();
    const intent = document.createElement('fieldset');
    intent.className = 'intent-switch';
    intent.innerHTML = `
      <legend>Цель обращения</legend>
      <div class="intent-options">
        <label class="intent-option"><input type="radio" name="lead_type" value="trial_now" checked><span>Пробное занятие<br>3–6 лет</span></label>
        <label class="intent-option"><input type="radio" name="lead_type" value="future_group"><span>Будущая<br>старшая группа</span></label>
      </div>
    `;
    const firstLabel = form.querySelector('label');
    form.insertBefore(intent, firstLabel || form.firstChild);
    const note = document.createElement('div');
    note.className = 'form-intent-note';
    note.textContent = leadTypeLabels.trial_now;
    intent.insertAdjacentElement('afterend', note);
    intent.addEventListener('change', (event) => {
      if (event.target instanceof HTMLInputElement && event.target.name === 'lead_type') {
        setLeadType(event.target.value);
      }
    });

    const submit = form.querySelector('button[type="submit"]');
    if (submit) submit.textContent = 'Перезвоните мне';

    const trialCard = form.closest('.trial-card');
    const telegramLink = document.querySelector('.trial-copy [data-telegram-link]');
    if (trialCard && telegramLink && telegramUrl) {
      const divider = document.createElement('div');
      divider.className = 'contact-divider';
      divider.textContent = 'или';
      const telegram = document.createElement('a');
      telegram.className = 'telegram-large';
      telegram.href = telegramForSource('trial_tg');
      telegram.target = '_blank';
      telegram.rel = 'noopener';
      telegram.dataset.telegramLink = '';
      telegram.dataset.source = 'trial_tg';
      telegram.innerHTML = '<span>Написать в Telegram</span><small>Быстро открыть Elite менеджер</small>';
      form.insertAdjacentElement('afterend', divider);
      divider.insertAdjacentElement('afterend', telegram);
    }
  }

  const groups = document.querySelectorAll('.group');
  if (groups[0]) {
    const age = groups[0].querySelector('strong');
    const cta = groups[0].querySelector('[data-callback]');
    if (age) age.textContent = '3–6';
    if (cta) {
      cta.textContent = 'Пробное бесплатно';
      cta.dataset.leadType = 'trial_now';
    }
  }
  if (groups[1]) {
    const age = groups[1].querySelector('strong');
    const heading = groups[1].querySelector('h3');
    const cta = groups[1].querySelector('[data-callback]');
    if (age) age.textContent = 'Скоро';
    if (heading) heading.textContent = 'Будущая старшая группа';
    if (cta) {
      cta.textContent = 'Оставить заявку';
      cta.dataset.leadType = 'future_group';
    }
  }

  document.querySelectorAll('.hero-actions .btn').forEach((button) => button.classList.add('btn-major'));

  if (hero && sticky) {
    new IntersectionObserver(
      ([entry]) => sticky.classList.toggle('is-visible', !entry.isIntersecting),
      { threshold: 0.12 }
    ).observe(hero);
  }

  document.querySelectorAll('[data-callback]').forEach((link) => {
    link.addEventListener('click', () => {
      source = link.dataset.source || 'callback_block';
      setLeadType(link.dataset.leadType || intentForSource(source));
      if (form?.source) form.source.value = source;
      window.setTimeout(() => phone?.focus({ preventScroll: true }), 500);
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
        ? 'Готово. Заявка в будущую старшую группу сохранена.'
        : 'Готово. Заявка принята — администратор перезвонит вам.';
      form.reset();
      source = 'callback_block';
      if (form.source) form.source.value = source;
      setLeadType('trial_now');
    } catch (_) {
      status.textContent = 'Не получилось отправить. Позвоните нам или напишите в Telegram.';
    } finally {
      button.disabled = false;
    }
  });
})();
