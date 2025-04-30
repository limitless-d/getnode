import { generateSubscriptionConfig } from './subscription.js';
import { handleKVRequest } from './kvManager.js';
import { sendMessage, proxyURL } from './utils.js';
import { generateDynamicUUID } from './uuidGenerator.js';

/**
 * fetch方法是 Cloudflare Workers 的标准入口点，用于处理传入的 HTTP 请求。
 * @param {Request} request - 传入的 HTTP 请求对象。
 * @param {ExecutionContext} env - 环境变量对象，包含部署时设置的变量。
 * @param {ExecutionContext} ctx - 执行上下文对象。
 * @returns {Promise<Response>} - 返回 HTTP 响应。
 */
export async function fetchHandler(request, env, ctx) {
    try {
        const url = new URL(request.url);
        const userAgent = (request.headers.get('User-Agent') || 'null').toLowerCase();

        // 动态 UUID 生成
        let userID = env.UUID || env.PASSWORD || env.pswd || '';
        let dynamicUUID = null;
        if (env.KEY || env.TOKEN || (userID && !isValidUUID(userID))) {
            dynamicUUID = env.KEY || env.TOKEN || userID;
            const [currentUUID] = await generateDynamicUUID(dynamicUUID, env);
            userID = currentUUID;
        }

        if (!userID) {
            return new Response('请设置你的UUID变量，或检查变量是否生效？', {
                status: 404,
                headers: { "Content-Type": "text/plain;charset=utf-8" },
            });
        }

        // 路径处理
        const path = url.pathname.toLowerCase();
        if (path === '/') {
            if (env.URL302) {
                return Response.redirect(env.URL302, 302);
            } else if (env.URL) {
                return await proxyURL(env.URL, url);
            } else {
                return new Response(JSON.stringify(request.cf, null, 4), {
                    status: 200,
                    headers: { 'content-type': 'application/json' },
                });
            }
        } else if (path === `/${userID}` || path === `/${dynamicUUID}`) {
            await sendMessage(`#获取订阅`, request.headers.get('CF-Connecting-IP'), `UA: ${userAgent}`);
            const config = await generateSubscriptionConfig(userID, request.headers.get('Host'), url, env);
            return new Response(config, {
                status: 200,
                headers: {
                    "Content-Type": "text/plain;charset=utf-8",
                    "Cache-Control": "no-store",
                },
            });
        } else if (path === `/${userID}/edit` || path === `/${dynamicUUID}/edit`) {
            return await handleKVRequest(request, env);
        } else {
            return new Response('路径未找到，请检查请求路径是否正确。', { status: 404 });
        }
    } catch (error) {
        console.error('Error in fetchHandler:', error);
        return new Response(`服务器错误: ${error.message}`, { status: 500 });
    }
}

/**
 * 校验 UUID 格式
 * @param {string} uuid - 待校验的 UUID。
 * @returns {boolean} - 是否为有效的 UUID。
 */
function isValidUUID(uuid) {
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    return uuidRegex.test(uuid);
}