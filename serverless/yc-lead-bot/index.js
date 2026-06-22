'use strict';
/*
 * Yandex Cloud Function — приём заявок с сайта и отправка в Telegram-бот.
 * Runtime: nodejs18 (или новее). Точка входа: index.handler
 *
 * Переменные окружения (задаются в консоли функции, НЕ в коде):
 *   TG_TOKEN      — токен бота из @BotFather
 *   TG_CHAT_ID    — chat_id, куда слать заявки
 *   ALLOW_ORIGIN  — https://skvortsovadv.ru (для CORS)
 */
const https = require('https');

const TOKEN = process.env.TG_TOKEN || '';
const CHAT_ID = process.env.TG_CHAT_ID || '';
const ALLOW_ORIGIN = process.env.ALLOW_ORIGIN || '*';

const cors = {
  'Access-Control-Allow-Origin': ALLOW_ORIGIN,
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type'
};

function tg(method, payload) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(payload);
    const req = https.request({
      hostname: 'api.telegram.org',
      path: '/bot' + TOKEN + '/' + method,
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) }
    }, (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => resolve({ status: res.statusCode, body: data }));
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

module.exports.handler = async (event) => {
  const method = (event && event.httpMethod) || 'POST';
  if (method === 'OPTIONS') return { statusCode: 204, headers: cors, body: '' };
  try {
    let raw = (event && event.body) || '{}';
    if (event && event.isBase64Encoded) raw = Buffer.from(raw, 'base64').toString('utf8');
    let d = {};
    try { d = JSON.parse(raw || '{}'); } catch (e) { d = {}; }

    const clip = (v, n) => (v == null ? '' : String(v)).slice(0, n);
    const name = clip(d.name, 200);
    const phone = clip(d.phone, 100);
    const email = clip(d.email, 200);
    const task = clip(d.task, 2000);
    const page = clip(d.page, 300);

    if (!name || !phone) {
      return { statusCode: 400, headers: cors, body: JSON.stringify({ ok: false, error: 'name_and_phone_required' }) };
    }

    const text =
      '🆕 Заявка с сайта skvortsovadv.ru\n\n' +
      '👤 Имя: ' + name + '\n' +
      '📞 Телефон: ' + phone + '\n' +
      '✉️ Email: ' + (email || '—') + '\n' +
      '📝 Задача: ' + (task || '—') + '\n' +
      '🔗 ' + (page || '—');

    const r = await tg('sendMessage', { chat_id: CHAT_ID, text: text, disable_web_page_preview: true });
    if (r.status !== 200) {
      return { statusCode: 502, headers: cors, body: JSON.stringify({ ok: false, error: 'telegram_error', detail: r.body }) };
    }
    return { statusCode: 200, headers: cors, body: JSON.stringify({ ok: true }) };
  } catch (e) {
    return { statusCode: 500, headers: cors, body: JSON.stringify({ ok: false, error: String((e && e.message) || e) }) };
  }
};
