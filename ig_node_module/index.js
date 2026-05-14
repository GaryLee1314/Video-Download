const axios = require('axios');
const fs = require('fs');
const path = require('path');
let SocksProxyAgent = null;
try {
    ({ SocksProxyAgent } = require('socks-proxy-agent'));
} catch (e) {
    // Optional dependency. Instagram can still try direct access without it.
}

const instagramProxyUrl = process.env.IG_PROXY_URL || 'socks5h://127.0.0.1:40000';
const cookiesFile = path.join(__dirname, '..', 'cookies.txt');

function loadInstagramCookies() {
    if (!fs.existsSync(cookiesFile)) return [];
    const lines = fs.readFileSync(cookiesFile, 'utf8').split(/\r?\n/);
    const cookies = [];
    for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#')) continue;
        const parts = trimmed.split('\t');
        if (parts.length >= 7) {
            const [domain, , cookiePath, secure, expires, name, ...valueParts] = parts;
            if (!domain.includes('instagram.com')) continue;
            cookies.push({
                name,
                value: valueParts.join('\t'),
                domain: domain.startsWith('.') ? domain : `.${domain}`,
                path: cookiePath || '/',
                secure: secure.toUpperCase() === 'TRUE',
                expires: Number(expires) || undefined
            });
            continue;
        }
        const equalIndex = trimmed.indexOf('=');
        if (equalIndex > 0) {
            cookies.push({
                name: trimmed.slice(0, equalIndex).trim(),
                value: trimmed.slice(equalIndex + 1).replace(/;$/, '').trim(),
                domain: '.instagram.com',
                path: '/'
            });
        }
    }
    return cookies;
}

function buildCookieHeader() {
    return loadInstagramCookies()
        .filter(cookie => cookie.name && cookie.value)
        .map(cookie => `${cookie.name}=${cookie.value}`)
        .join('; ');
}

// ========================================================
// [Monkey Patch] instagram-url-direct 请求头增强
// ========================================================
const originalRequest = axios.request;
axios.request = async function (config) {
    config.headers = config.headers || {};
    if (SocksProxyAgent && process.env.IG_DISABLE_PROXY !== '1') {
        const agent = new SocksProxyAgent(instagramProxyUrl);
        config.httpAgent = agent;
        config.httpsAgent = agent;
        config.proxy = false;
    }
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
    // 核心修复：把 X-CSRFToken 镜像到 Cookie 中
    let currentCookie = config.headers['Cookie'] || '';
    const fileCookie = buildCookieHeader();
    if (fileCookie) {
        currentCookie = currentCookie ? `${currentCookie}; ${fileCookie}` : fileCookie;
    }
    if (config.headers['X-CSRFToken']) {
        const token = config.headers['X-CSRFToken'];
        if (!currentCookie.includes('csrftoken=')) {
            currentCookie += `csrftoken=${token}; `;
        }
    }
    if (!currentCookie.includes('ig_did')) currentCookie += 'ig_did=4F658E2E-7B93-4B07-B654-7B0909A67C41; ';
    if (!currentCookie.includes('ig_nrcb')) currentCookie += 'ig_nrcb=1; ';
    if (!currentCookie.includes('mid')) currentCookie += 'mid=Z_a_ZQAALAA123; ';
    config.headers['Cookie'] = currentCookie.trim();
    return originalRequest.apply(this, arguments);
};

// 必须在 Axios 被 Patch 后再加载
const ig = require('instagram-url-direct');

// ========================================================
// 通道 A：instagram-url-direct (GraphQL，快速但可能被封)
// ========================================================
async function extractViaGraphQL(url) {
    const res = await ig.instagramGetUrl(url);
    return res;
}

// ========================================================
// 通道 B：Puppeteer 无头浏览器 (慢但 100% 可靠)
// ========================================================
async function extractViaPuppeteer(url) {
    // 动态查找 Chrome 路径
    const chromePaths = [
        process.env.PUPPETEER_EXECUTABLE_PATH,
        'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
        'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
        '/usr/bin/google-chrome',
        '/usr/bin/chromium-browser',
        '/usr/bin/chromium',
    ];
    let chromePath = null;
    for (const p of chromePaths) {
        if (p && fs.existsSync(p)) { chromePath = p; break; }
    }
    if (!chromePath) {
        try {
            const puppeteerPackage = require('puppeteer');
            const bundledChromePath = puppeteerPackage.executablePath();
            if (bundledChromePath && fs.existsSync(bundledChromePath)) {
                chromePath = bundledChromePath;
            }
        } catch (e) {
            // Keep the explicit error below if no browser is available.
        }
    }
    if (!chromePath) {
        throw new Error('Chrome 浏览器未安装，无法使用 Puppeteer 降级方案');
    }

    const puppeteer = require('puppeteer');
    const launchArgs = ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu', '--disable-dev-shm-usage'];
    if (SocksProxyAgent && process.env.IG_DISABLE_PROXY !== '1') {
        launchArgs.push(`--proxy-server=${instagramProxyUrl}`);
    }

    const browser = await puppeteer.launch({
        headless: 'new',
        executablePath: chromePath,
        args: launchArgs
    });

    try {
        const page = await browser.newPage();
        const cookies = loadInstagramCookies();
        if (cookies.length > 0) {
            await page.setCookie(...cookies);
        }
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36');
        await page.setViewport({ width: 1280, height: 720 });

        let videoUrl = null;
        let thumbnailUrl = null;

        // 拦截网络响应捕获视频 CDN
        page.on('response', (response) => {
            const respUrl = response.url();
            if ((respUrl.includes('cdninstagram.com') || respUrl.includes('fbcdn.net')) && respUrl.includes('.mp4') && !videoUrl) {
                videoUrl = respUrl;
            }
        });

        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
        await new Promise(resolve => setTimeout(resolve, 5000));

        // 尝试从 DOM 获取 video 元素
        try {
            await page.waitForSelector('video, meta[property="og:video"], meta[property="og:video:url"], meta[property="og:image"]', { timeout: 8000 });
            const videoData = await page.evaluate(() => {
                const video = document.querySelector('video');
                const videoMeta = document.querySelector('meta[property="og:video"], meta[property="og:video:url"], meta[property="og:video:secure_url"]');
                const imageMeta = document.querySelector('meta[property="og:image"]');
                return {
                    src: (video && (video.src || video.currentSrc)) || (videoMeta && videoMeta.getAttribute('content')) || null,
                    poster: (video && video.poster) || (imageMeta && imageMeta.getAttribute('content')) || null
                };
            });
            if (videoData) {
                if (videoData.src && !videoUrl) videoUrl = videoData.src;
                if (videoData.poster) thumbnailUrl = videoData.poster;
            }
        } catch (e) { /* 如果没有 video 元素，继续 */ }

        // 从 meta 标签获取缩略图和标题
        if (!thumbnailUrl) {
            thumbnailUrl = await page.evaluate(() => {
                const meta = document.querySelector('meta[property="og:image"]');
                return meta ? meta.getAttribute('content') : null;
            });
        }
        const title = await page.evaluate(() => {
            const meta = document.querySelector('meta[property="og:title"]');
            return meta ? meta.getAttribute('content') : document.title;
        });

        if (!videoUrl) {
            throw new Error('浏览器渲染后仍未找到视频地址');
        }

        // 组装为与 instagram-url-direct 一致的输出格式
        return {
            results_number: 1,
            url_list: [videoUrl],
            post_info: {
                owner_username: '',
                owner_fullname: '',
                caption: title || 'Instagram Video'
            },
            media_details: [{
                type: 'video',
                url: videoUrl,
                thumbnail: thumbnailUrl || ''
            }]
        };
    } finally {
        await browser.close();
    }
}

// ========================================================
// 主函数：双通道策略
// ========================================================
async function main() {
    const url = process.argv[2];
    if (!url) {
        console.error("No url provided");
        process.exit(1);
    }

    let result = null;

    // 通道 A：先尝试 GraphQL（快，约 2-3 秒）
    try {
        result = await extractViaGraphQL(url);
        // 验证返回值确实包含视频
        if (result && result.url_list && result.url_list.length > 0 && result.url_list[0]) {
            console.log(JSON.stringify(result, null, 2));
            return;
        }
    } catch (e) {
        // GraphQL 失败（401/403/429 等），降级到通道 B
        process.stderr.write(`[GraphQL 通道失败: ${e.message}] 正在切换到浏览器降级通道...\n`);
    }

    // 通道 B：Puppeteer 无头浏览器（慢，约 8-15 秒，但极度可靠）
    try {
        result = await extractViaPuppeteer(url);
        console.log(JSON.stringify(result, null, 2));
    } catch (e) {
        console.error(e.message);
        process.exit(1);
    }
}

main();
