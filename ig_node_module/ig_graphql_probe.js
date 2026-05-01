const axios = require('axios');

const originalRequest = axios.request;
axios.request = async function (config) {
  config.headers = config.headers || {};
  const defaultHeaders = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'X-Requested-With': 'XMLHttpRequest',
    'Accept-Language': 'en-US,en;q=0.9'
  };
  for (const [key, val] of Object.entries(defaultHeaders)) {
    if (!config.headers[key]) config.headers[key] = val;
  }
  let currentCookie = config.headers['Cookie'] || '';
  if (config.headers['X-CSRFToken']) {
    const token = config.headers['X-CSRFToken'];
    if (!currentCookie.includes('csrftoken=')) currentCookie += `csrftoken=${token}; `;
  }
  if (!currentCookie.includes('ig_did')) currentCookie += 'ig_did=4F658E2E-7B93-4B07-B654-7B0909A67C41; ';
  if (!currentCookie.includes('ig_nrcb')) currentCookie += 'ig_nrcb=1; ';
  if (!currentCookie.includes('mid')) currentCookie += 'mid=Z_a_ZQAALAA123; ';
  config.headers['Cookie'] = currentCookie.trim();
  return originalRequest.apply(this, arguments);
};

const ig = require('instagram-url-direct');
const url = process.argv[2];
if (!url) {
  console.error('No url provided');
  process.exit(2);
}

(async () => {
  try {
    const res = await ig.instagramGetUrl(url);
    console.log(JSON.stringify({ ok: true, resultCount: res?.url_list?.length || 0, sample: res?.url_list?.[0] || null }, null, 2));
  } catch (e) {
    const out = {
      ok: false,
      name: e?.name || null,
      message: e?.message || String(e),
      stack: e?.stack || null,
      responseStatus: e?.response?.status || null,
      responseHeaders: e?.response?.headers || null,
      responseData: e?.response?.data || null,
      code: e?.code || null
    };
    console.log(JSON.stringify(out, null, 2));
    process.exit(1);
  }
})();
