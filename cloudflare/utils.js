/**
 * 整理订阅地址
 * @param {string} rawAddresses - 原始的订阅地址字符串
 * @returns {string[]} - 返回整理后的订阅地址数组
 */
export function organizeAddresses(rawAddresses) {
    return rawAddresses
        .split('\n')
        .map(line => line.trim())
        .filter(line => line && !line.startsWith('#')); // 去除空行和注释行
}

/**
 * 验证是否为有效的 IPv4 地址
 * @param {string} ip - 待验证的 IP 地址
 * @returns {boolean} - 是否为有效的 IPv4 地址
 */
export function isValidIPv4(ip) {
    const ipv4Regex = /^(25[0-5]|2[0-4][0-9]|[0-1]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[0-1]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[0-1]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[0-1]?[0-9][0-9]?)$/;
    return ipv4Regex.test(ip);
}

/**
 * 代理 URL 请求
 * @param {string} targetUrl - 目标 URL
 * @param {URL} requestUrl - 原始请求的 URL 对象
 * @returns {Promise<Response>} - 返回代理的响应
 */
export async function proxyURL(targetUrl, requestUrl) {
    try {
        const response = await fetch(targetUrl, {
            method: 'GET',
            headers: {
                'User-Agent': requestUrl.headers.get('User-Agent') || 'Mozilla/5.0',
            },
        });
        return response;
    } catch (error) {
        console.error('Error proxying URL:', error);
        return new Response('代理请求失败: ' + error.message, { status: 500 });
    }
}

/**
 * Base64 解码
 * @param {string} encoded - Base64 编码的字符串
 * @returns {string} - 解码后的字符串
 */
export function decodeBase64(encoded) {
    try {
        return atob(encoded);
    } catch (error) {
        console.error('Base64 解码失败:', error);
        return '';
    }
}

/**
 * Base64 编码
 * @param {string} raw - 原始字符串
 * @returns {string} - 编码后的 Base64 字符串
 */
export function encodeBase64(raw) {
    try {
        return btoa(raw);
    } catch (error) {
        console.error('Base64 编码失败:', error);
        return '';
    }
}

/**
 * 发送消息到 Telegram
 * @param {string} botToken - Telegram 机器人 Token
 * @param {string} chatID - Telegram 聊天 ID
 * @param {string} message - 要发送的消息
 * @returns {Promise<Response>} - 返回 Telegram API 的响应
 */
export async function sendMessage(botToken, chatID, message) {
    if (!botToken || !chatID) return;

    const url = `https://api.telegram.org/bot${botToken}/sendMessage?chat_id=${chatID}&text=${encodeURIComponent(message)}`;
    try {
        return await fetch(url, { method: 'GET' });
    } catch (error) {
        console.error('发送消息失败:', error);
    }
}