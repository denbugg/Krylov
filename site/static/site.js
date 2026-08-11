(() => {
  const hero = document.querySelector('.hero');
  const sticky = document.querySelector('[data-sticky]');
  const form = document.querySelector('#lead-form');
  const phone = form?.querySelector('input[name="phone"]');
  let source = 'callback_block';

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

  if (hero && sticky) {
    new IntersectionObserver(
      ([entry]) => sticky.classList.toggle('is-visible', !entry.isIntersecting),
      { threshold: 0.12 }
    ).observe(hero);
  }

  document.querySelectorAll('[data-callback]').forEach((link) => {
    link.addEventListener('click', () => {
      source = link.dataset.source || 'callback_block';
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
    payload.lead_type = payload.lead_type || 'trial_now';
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
      status.textContent = 'Готово. Заявка принята — администратор перезвонит вам.';
      form.reset();
      source = 'callback_block';
      if (form.source) form.source.value = source;
      if (form.lead_type) form.lead_type.value = 'trial_now';
    } catch (_) {
      status.textContent = 'Не получилось отправить. Позвоните нам или напишите в Telegram.';
    } finally {
      button.disabled = false;
    }
  });
})();
