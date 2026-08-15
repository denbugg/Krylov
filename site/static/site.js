(() => {
  const hero = document.querySelector('.hero');
  const sticky = document.querySelector('[data-sticky]');
  const form = document.querySelector('#lead-form');
  const phone = form?.querySelector('input[name="phone"]');
  let source = 'callback_block';
  let leadType = 'trial_now';

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
    new IntersectionObserver(
      ([entry]) => sticky.classList.toggle('is-visible', !entry.isIntersecting),
      { threshold: 0.12 }
    ).observe(hero);
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