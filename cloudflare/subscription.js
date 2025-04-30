import { organizeAddresses, isValidIPv4 } from './utils.js';

/**
 * 生成订阅配置信息
 * @param {string} userID - 用户的 UUID
 * @param {string} hostName - 请求的主机名
 * @param {URL} url - 请求的 URL 对象
 * @param {ExecutionContext} env - 环境变量对象
 * @returns {Promise<string>} - 返回生成的订阅配置
 */
export async function generateSubscriptionConfig(userID, hostName, url, env) {
    const subParams = ['sub', 'b64', 'clash', 'sb', 'loon'];
    const userAgent = (url.searchParams.get('ua') || '').toLowerCase();

    if (userAgent.includes('mozilla') && !subParams.some(param => url.searchParams.has(param))) {
        return generateSubscriptionPage(userID, hostName, env);
    } else {
        const fakeHostName = generateFakeHostName(hostName, env);
        const addresses = await fetchSubscriptionAddresses(fakeHostName, userID, env);
        return generateSubscriptionContent(addresses, userID, fakeHostName, env);
    }
}

/**
 * 生成订阅页面 HTML
 * @param {string} userID - 用户的 UUID
 * @param {string} hostName - 请求的主机名
 * @param {ExecutionContext} env - 环境变量对象
 * @returns {string} - 返回订阅页面的 HTML
 */
function generateSubscriptionPage(userID, hostName, env) {
    const proxyHost = env.PROXY_HOST || 'proxy.example.com';
    return `
        <!DOCTYPE html>
        <html>
        <head>
            <title>订阅配置</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
        </head>
        <body>
            <h1>订阅地址</h1>
            <p>自适应订阅地址: <a href="https://${proxyHost}/${userID}?sub">点击复制</a></p>
            <p>Base64 订阅地址: <a href="https://${proxyHost}/${userID}?b64">点击复制</a></p>
            <p>Clash 订阅地址: <a href="https://${proxyHost}/${userID}?clash">点击复制</a></p>
        </body>
        </html>
    `;
}

/**
 * 生成伪装的主机名
 * @param {string} hostName - 请求的主机名
 * @param {ExecutionContext} env - 环境变量对象
 * @returns {string} - 返回伪装的主机名
 */
function generateFakeHostName(hostName, env) {
    if (hostName.includes('.workers.dev')) {
        return `${env.FAKE_HOST || 'fake'}.workers.dev`;
    } else if (hostName.includes('.pages.dev')) {
        return `${env.FAKE_HOST || 'fake'}.pages.dev`;
    } else {
        return `${env.FAKE_HOST || 'fake'}.example.com`;
    }
}

/**
 * 获取订阅地址
 * @param {string} fakeHostName - 伪装的主机名
 * @param {string} userID - 用户的 UUID
 * @param {ExecutionContext} env - 环境变量对象
 * @returns {Promise<string[]>} - 返回订阅地址数组
 */
async function fetchSubscriptionAddresses(fakeHostName, userID, env) {
    const apiUrls = env.API_URLS ? env.API_URLS.split(',') : [];
    const addresses = await Promise.all(apiUrls.map(async apiUrl => {
        try {
            const response = await fetch(`${apiUrl}?host=${fakeHostName}&uuid=${userID}`);
            if (response.ok) {
                return await response.text();
            }
        } catch (error) {
            console.error(`Error fetching subscription from ${apiUrl}:`, error);
        }
        return '';
    }));
    return organizeAddresses(addresses.join('\n'));
}

/**
 * 生成订阅内容
 * @param {string[]} addresses - 整理后的订阅地址
 * @param {string} userID - 用户的 UUID
 * @param {string} fakeHostName - 伪装的主机名
 * @param {ExecutionContext} env - 环境变量对象
 * @returns {string} - 返回订阅内容
 */
function generateSubscriptionContent(addresses, userID, fakeHostName, env) {
    const protocol = env.PROTOCOL || 'vmess';
    return addresses.map(address => {
        const [host, port] = address.split(':');
        if (!isValidIPv4(host)) return '';
        return `${protocol}://${userID}@${host}:${port}?host=${fakeHostName}`;
    }).join('\n');
}