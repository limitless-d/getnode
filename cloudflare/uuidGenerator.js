
/**
 * 生成动态 UUID
 * @param {string} key - 用于生成 UUID 的密钥
 * @param {ExecutionContext} env - 环境变量对象
 * @returns {Promise<string[]>} - 返回动态生成的 UUID 数组
 */
export async function generateDynamicUUID(key, env) {
    const timestamp = Math.floor(Date.now() / 1000); // 当前时间戳（秒）
    const hash1 = await doubleHash(`${key}${timestamp}`);
    const hash2 = await doubleHash(`${key}${timestamp - 1}`);
    return [hash1, hash2];
}

/**
 * 双重哈希函数
 * @param {string} input - 输入字符串
 * @returns {Promise<string>} - 返回哈希后的字符串
 */
async function doubleHash(input) {
    const hash1 = await hashString(input);
    return hashString(hash1);
}

/**
 * 哈希字符串
 * @param {string} input - 输入字符串
 * @returns {Promise<string>} - 返回哈希后的字符串
 */
async function hashString(input) {
    const encoder = new TextEncoder();
    const data = encoder.encode(input);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    return bufferToHex(hashBuffer);
}

/**
 * 将 ArrayBuffer 转换为十六进制字符串
 * @param {ArrayBuffer} buffer - 输入的 ArrayBuffer
 * @returns {string} - 返回十六进制字符串
 */
function bufferToHex(buffer) {
    return Array.from(new Uint8Array(buffer))
        .map(byte => byte.toString(16).padStart(2, '0'))
        .join('');
}